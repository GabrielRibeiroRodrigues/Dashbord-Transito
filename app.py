from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import psycopg2
from datetime import datetime, timedelta
import json
from decimal import Decimal

app = Flask(__name__)
CORS(app)

# Configuração de conexão com PostgreSQL
DB_CONFIG = {
    'dbname': 'pci_transito',
    'user': 'postgres',
    'password': '123456',
    'host': 'localhost',
    'port': '5432'
}

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, obj).default(obj)

def get_db_connection():
    try:
        connection = psycopg2.connect(**DB_CONFIG)
        return connection
    except psycopg2.Error as e:
        print(f"Erro ao conectar com o banco: {e}")
        return None

def group_plates_by_time_window(plates_data, time_window=5):
    """
    Algoritmo simples e eficiente para agrupar placas por janela de tempo.
    
    1. Ordena todas as placas por timestamp
    2. Para cada placa, verifica se pode ser agrupada com a anterior
    3. Se a diferença de tempo for <= time_window, agrupa; senão, inicia novo grupo
    4. Retorna apenas a placa com maior confiança de cada grupo
    """
    if not plates_data:
        return []
    
    # Ordenar por timestamp
    plates_data.sort(key=lambda x: datetime.fromisoformat(x['data_hora'].replace('Z', '+00:00')))
    
    groups = []
    current_group = []
    
    for i, plate in enumerate(plates_data):
        current_time = datetime.fromisoformat(plate['data_hora'].replace('Z', '+00:00'))
        
        if not current_group:
            # Primeiro grupo ou primeiro item de um novo grupo
            current_group = [plate]
        else:
            # Verificar se pode ser adicionado ao grupo atual
            last_plate_in_group = current_group[-1]
            last_time = datetime.fromisoformat(last_plate_in_group['data_hora'].replace('Z', '+00:00'))
            time_diff = (current_time - last_time).total_seconds()
            
            if time_diff <= time_window:
                # Adicionar ao grupo atual
                current_group.append(plate)
            else:
                # Finalizar grupo atual e iniciar novo
                if current_group:
                    groups.append(current_group)
                current_group = [plate]
    
    # Adicionar o último grupo
    if current_group:
        groups.append(current_group)
    
    # Para cada grupo, retornar apenas a placa com maior confiança
    result = []
    for group in groups:
        best_plate = max(group, key=lambda x: x['license_number_score'])
        best_plate['group_size'] = len(group)
        best_plate['grouped_plates'] = list(set([p['license_number'] for p in group]))  # Remove duplicatas
        
        # Adicionar informações de tempo do grupo
        times = [datetime.fromisoformat(p['data_hora'].replace('Z', '+00:00')) for p in group]
        best_plate['group_time_span'] = round((max(times) - min(times)).total_seconds(), 1)
        
        result.append(best_plate)
    
    # Ordenar resultado por timestamp (mais recente primeiro)
    result.sort(key=lambda x: datetime.fromisoformat(x['data_hora'].replace('Z', '+00:00')), reverse=True)
    
    return result

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/placas')
def get_placas():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    search = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    deduplicate = request.args.get('deduplicate', 'false').lower() == 'true'
    time_window = int(request.args.get('time_window', 5))  # Janela de tempo em segundos
    similarity_threshold = float(request.args.get('similarity_threshold', 0.8))  # Limiar de similaridade
    
    if deduplicate:
        return get_placas_deduplicated(page, per_page, search, date_from, date_to, time_window, similarity_threshold)
    
    offset = (page - 1) * per_page
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Erro de conexão com o banco'}), 500
    
    try:
        cursor = connection.cursor()
        
        # Query base
        base_query = """
            FROM transito_leitura_placa 
            WHERE 1=1
        """
        
        params = []
        
        # Filtro por placa
        if search:
            base_query += " AND license_number ILIKE %s"
            params.append(f'%{search}%')
        
        # Filtro por data
        if date_from:
            base_query += " AND DATE(data_hora) >= %s"
            params.append(date_from)
            
        if date_to:
            base_query += " AND DATE(data_hora) <= %s"
            params.append(date_to)
        
        # Contar total de registros
        count_query = "SELECT COUNT(*) " + base_query
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]
        
        # Query principal com paginação
        main_query = f"""
            SELECT id, frame_nmr, car_id, license_number, license_number_score, 
                   data_hora
            {base_query}
            ORDER BY data_hora DESC
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])
        
        cursor.execute(main_query, params)
        placas = cursor.fetchall()
        
        # Formatando os resultados
        result = []
        for placa in placas:
            result.append({
                'id': placa[0],
                'frame_nmr': placa[1],
                'car_id': placa[2],
                'license_number': placa[3],
                'license_number_score': float(placa[4]) if placa[4] else 0,
                'data_hora': placa[5].isoformat() if placa[5] else None,
               
            })
        
        return jsonify({
            'data': result,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page,
            'deduplicated': False
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

def get_placas_deduplicated(page, per_page, search, date_from, date_to, time_window, similarity_threshold=0.8):
    """
    Função para retornar placas deduplicadas baseada APENAS em janela de tempo.
    Agrupa TODAS as placas dentro de uma janela de tempo e 
    retorna apenas a leitura com maior confiança para cada janela.
    """
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Erro de conexão com o banco'}), 500
    
    try:
        cursor = connection.cursor()
        
        # Query base para buscar TODOS os dados primeiro (sem paginação)
        where_conditions = ["1=1"]
        params = []
        
        # Filtro por placa
        if search:
            where_conditions.append("license_number ILIKE %s")
            params.append(f'%{search}%')
        
        # Filtro por data
        if date_from:
            where_conditions.append("DATE(data_hora) >= %s")
            params.append(date_from)
            
        if date_to:
            where_conditions.append("DATE(data_hora) <= %s")
            params.append(date_to)
        
        where_clause = " AND ".join(where_conditions)
        
        # Buscar todos os dados para processamento em Python
        query = f"""
            SELECT id, frame_nmr, car_id, license_number, license_number_score, data_hora
            FROM transito_leitura_placa 
            WHERE {where_clause}
            ORDER BY data_hora DESC
        """
        
        cursor.execute(query, params)
        raw_results = cursor.fetchall()
        
        if not raw_results:
            return jsonify({
                'data': [],
                'total': 0,
                'page': page,
                'per_page': per_page,
                'total_pages': 0,
                'deduplicated': True,
                'time_window': time_window,
                'similarity_threshold': similarity_threshold
            })
        
        # Converter para formato de dicionário para processamento
        plates_data = []
        for row in raw_results:
            plates_data.append({
                'id': row[0],
                'frame_nmr': row[1],
                'car_id': row[2],
                'license_number': row[3],
                'license_number_score': float(row[4]) if row[4] else 0,
                'data_hora': row[5].isoformat() if row[5] else None,
            })
        
        # Aplicar algoritmo de agrupamento por janela de tempo
        deduplicated_plates = group_plates_by_time_window(
            plates_data, 
            time_window=time_window
        )
        
        # Aplicar paginação nos resultados processados
        total = len(deduplicated_plates)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_results = deduplicated_plates[start_index:end_index]
        
        return jsonify({
            'data': paginated_results,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page,
            'deduplicated': True,
            'time_window': time_window,
            'original_count': len(raw_results),
            'reduction_percentage': round((1 - total / len(raw_results)) * 100, 2) if raw_results else 0
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@app.route('/api/stats/daily')
def get_daily_stats():
    days = int(request.args.get('days', 30))
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Erro de conexão com o banco'}), 500
    
    try:
        cursor = connection.cursor()
        
        query = """
            SELECT DATE(data_hora) as data, COUNT(*) as quantidade
            FROM transito_leitura_placa
            WHERE data_hora >= %s
            GROUP BY DATE(data_hora)
            ORDER BY DATE(data_hora) DESC
        """
        
        start_date = datetime.now() - timedelta(days=days)
        cursor.execute(query, (start_date,))
        results = cursor.fetchall()
        
        data = []
        for row in results:
            data.append({
                'date': row[0].isoformat(),
                'count': row[1]
            })
        
        return jsonify(data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@app.route('/api/stats/hourly')
def get_hourly_stats():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Erro de conexão com o banco'}), 500
    
    try:
        cursor = connection.cursor()
        
        query = """
            SELECT EXTRACT(hour FROM data_hora) as hora, COUNT(*) as quantidade
            FROM transito_leitura_placa
            WHERE DATE(data_hora) = %s
            GROUP BY EXTRACT(hour FROM data_hora)
            ORDER BY EXTRACT(hour FROM data_hora)
        """
        
        cursor.execute(query, (date,))
        results = cursor.fetchall()
        
        data = []
        for row in results:
            data.append({
                'hour': int(row[0]),
                'count': row[1]
            })
        
        return jsonify(data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@app.route('/api/stats/top-plates')
def get_top_plates():
    limit = int(request.args.get('limit', 10))
    days = int(request.args.get('days', 7))
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Erro de conexão com o banco'}), 500
    
    try:
        cursor = connection.cursor()
        
        query = """
            SELECT license_number, COUNT(*) as quantidade,
                   AVG(license_number_score) as confianca_media,
                   MAX(data_hora) as ultima_leitura
            FROM transito_leitura_placa
            WHERE data_hora >= %s
            GROUP BY license_number
            ORDER BY COUNT(*) DESC
            LIMIT %s
        """
        
        start_date = datetime.now() - timedelta(days=days)
        cursor.execute(query, (start_date, limit))
        results = cursor.fetchall()
        
        data = []
        for row in results:
            data.append({
                'license_number': row[0],
                'count': row[1],
                'avg_confidence': float(row[2]) if row[2] else 0,
                'last_seen': row[3].isoformat() if row[3] else None
            })
        
        return jsonify(data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@app.route('/api/stats/overview')
def get_overview_stats():
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Erro de conexão com o banco'}), 500
    
    try:
        cursor = connection.cursor()
        
        # Total de leituras
        cursor.execute("SELECT COUNT(*) FROM transito_leitura_placa")
        total_reads = cursor.fetchone()[0]
        
        # Leituras hoje
        cursor.execute("""
            SELECT COUNT(*) FROM transito_leitura_placa 
            WHERE DATE(data_hora) = CURRENT_DATE
        """)
        today_reads = cursor.fetchone()[0]
        
        # Placas únicas
        cursor.execute("SELECT COUNT(DISTINCT license_number) FROM transito_leitura_placa")
        unique_plates = cursor.fetchone()[0]
        
        # Confiança média
        cursor.execute("SELECT AVG(license_number_score) FROM transito_leitura_placa")
        avg_confidence = cursor.fetchone()[0]
        
        # Última leitura
        cursor.execute("""
            SELECT data_hora FROM transito_leitura_placa 
            ORDER BY data_hora DESC LIMIT 1
        """)
        last_read_result = cursor.fetchone()
        last_read = last_read_result[0].isoformat() if last_read_result else None
        
        return jsonify({
            'total_reads': total_reads,
            'today_reads': today_reads,
            'unique_plates': unique_plates,
            'avg_confidence': float(avg_confidence) if avg_confidence else 0,
            'last_read': last_read
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
