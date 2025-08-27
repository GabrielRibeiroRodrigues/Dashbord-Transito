from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import psycopg2
from datetime import datetime, timedelta
import json
from decimal import Decimal
import difflib
from collections import defaultdict

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

def calculate_plate_similarity(plate1, plate2):
    """
    Calcula a similaridade entre duas placas usando SequenceMatcher.
    Retorna um valor entre 0 e 1, onde 1 é idêntico.
    """
    if not plate1 or not plate2:
        return 0.0
    
    # Normalizar placas (maiúsculo, remover espaços)
    plate1 = plate1.upper().strip()
    plate2 = plate2.upper().strip()
    
    if plate1 == plate2:
        return 1.0
    
    # Usar SequenceMatcher para calcular similaridade
    similarity = difflib.SequenceMatcher(None, plate1, plate2).ratio()
    return similarity

def find_similar_plates(target_plate, plate_list, threshold=0.8):
    """
    Encontra placas similares à placa alvo na lista fornecida.
    Retorna lista de placas que têm similaridade >= threshold.
    """
    similar_plates = []
    for plate in plate_list:
        similarity = calculate_plate_similarity(target_plate, plate)
        if similarity >= threshold:
            similar_plates.append((plate, similarity))
    
    return similar_plates

def group_similar_plates(plates_data, similarity_threshold=0.8, time_window=5):
    """
    Agrupa placas similares dentro de uma janela de tempo e retorna
    apenas a com maior confiança para cada grupo.
    
    plates_data: lista de dicionários com dados das placas
    similarity_threshold: limiar de similaridade (0.8 = 80%)
    time_window: janela de tempo em segundos
    """
    # Ordenar por timestamp
    plates_data.sort(key=lambda x: x['data_hora'])
    
    # Grupos de placas similares
    groups = []
    processed_plates = set()
    
    for i, current_plate in enumerate(plates_data):
        if current_plate['id'] in processed_plates:
            continue
        
        # Criar novo grupo com a placa atual
        current_group = [current_plate]
        processed_plates.add(current_plate['id'])
        
        current_time = datetime.fromisoformat(current_plate['data_hora'].replace('Z', '+00:00'))
        
        # Procurar por placas similares na janela de tempo
        for j, other_plate in enumerate(plates_data[i+1:], i+1):
            if other_plate['id'] in processed_plates:
                continue
                
            other_time = datetime.fromisoformat(other_plate['data_hora'].replace('Z', '+00:00'))
            time_diff = abs((other_time - current_time).total_seconds())
            
            # Se está fora da janela de tempo, parar busca
            if time_diff > time_window:
                break
                
            # Calcular similaridade
            similarity = calculate_plate_similarity(
                current_plate['license_number'], 
                other_plate['license_number']
            )
            
            if similarity >= similarity_threshold:
                current_group.append(other_plate)
                processed_plates.add(other_plate['id'])
        
        # Escolher a placa com maior confiança do grupo
        best_plate = max(current_group, key=lambda x: x['license_number_score'])
        best_plate['group_size'] = len(current_group)
        best_plate['similar_plates'] = [p['license_number'] for p in current_group if p != best_plate]
        
        groups.append(best_plate)
    
    return groups

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
    Função aprimorada para retornar placas deduplicadas baseada em janela de tempo e similaridade.
    Agrupa placas similares (ex: PWS4919 e PUS4919) dentro de uma janela de tempo e 
    retorna apenas a leitura com maior confiança.
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
        
        # Aplicar algoritmo de agrupamento por similaridade e tempo
        deduplicated_plates = group_similar_plates(
            plates_data, 
            similarity_threshold=similarity_threshold, 
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
            'similarity_threshold': similarity_threshold,
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
