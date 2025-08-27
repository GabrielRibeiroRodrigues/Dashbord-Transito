import os
import cv2
import time
import gc
import signal  # Import for signal handling
from util import (
    ler_placas2,
    salvar_no_postgres,
    flush_buffer_leituras,
    close_db_connection,
)  # Import new functions

pasta_base = os.path.join(os.path.expanduser("~"), "Desktop", "placas_detectadas")
confianca_gravar_texto = 0.1  # Mantido, mas a lógica de correção pode ajudar placas com menor confiança inicial


def processar_imagem(caminho_arquivo):
    nome = os.path.basename(caminho_arquivo)
    try:
        partes = nome.split("_")
        # Adicionar mais validações para evitar IndexError
        if len(partes) > 3:
            frame_nmr_str = partes[1]
            car_id_str = partes[3]
            frame_nmr = int(frame_nmr_str) if frame_nmr_str.isdigit() else -1
            # Tratar caso onde car_id_str pode não ser um número válido antes de float()
            if "." in car_id_str:
                try:
                    car_id = int(float(car_id_str))
                except ValueError:
                    car_id = -1  # ID inválido se não puder converter
            elif car_id_str.isdigit():
                car_id = int(car_id_str)
            else:
                car_id = -1  # ID inválido
        else:
            frame_nmr = -1
            car_id = -1
    except Exception as e:
        print(f"[WARN] Erro ao parsear nome do arquivo '{nome}': {e}")
        frame_nmr = -1
        car_id = -1

    try:
        # Carregar a imagem.
        img = cv2.imread(caminho_arquivo, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"[ERRO] Não foi possível ler a imagem: {caminho_arquivo}. O arquivo será removido na limpeza final.")
            # Não tenta remover aqui; o finally cuidará disso.
            # Apenas retorna para evitar processamento adicional da imagem nula.
            return

        texto_detectado, confianca_texto_detectado = ler_placas2(img)

        # Libera a imagem da memória explicitamente
        del img

        if (
            texto_detectado is not None
            and confianca_texto_detectado is not None
            and confianca_texto_detectado > confianca_gravar_texto # Typo corrigido aqui
        ):
            print(
                f"[INFO] Frame: {frame_nmr}, Carro ID: {car_id}, Placa: {texto_detectado}, Confiança: {confianca_texto_detectado:.2f}"
            )
            salvar_no_postgres(frame_nmr, car_id, texto_detectado, confianca_texto_detectado) # Typo corrigido aqui
        # else:
        # print(f"[INFO] Placa não detectada ou confiança baixa para {nome}. Conf: {confianca_texto_detectado}")

    except cv2.error as e_cv:
        print(f"[ERRO_CV2] Erro de OpenCV ao processar {caminho_arquivo}: {e_cv}")
    except Exception as e_proc:
        print(f"[ERRO_PROC] Erro inesperado ao processar imagem {caminho_arquivo}: {e_proc}")
    finally:
        # Centraliza a tentativa de remoção do arquivo aqui.
        # Este bloco é executado independentemente de como o bloco try/except terminou.
        try:
            if os.path.exists(caminho_arquivo):
                os.remove(caminho_arquivo)
                # print(f"[INFO] Arquivo removido: {caminho_arquivo}")
            # else:
                # print(f"[INFO] Arquivo já não existia para remoção no finally: {caminho_arquivo}")
        except PermissionError as e_perm:
            print(f"[ERRO_PERMISSAO] Falha ao remover {caminho_arquivo} devido a permissões: {e_perm}")
        except OSError as e_os: # Captura outras IOErrors relacionadas, como 'arquivo em uso'
            print(f"[ERRO_OS] Falha ao remover {caminho_arquivo}: {e_os}")
        except Exception as e_rem_final: # Para qualquer outra exceção inesperada durante a remoção
            print(f"[ERRO_INESPERADO_REMOCAO] Falha ao remover {caminho_arquivo}: {e_rem_final}")

        gc.collect()  # Coleta de lixo


def main():
    arquivos_ignorados = {".tmp", ".part", ".crdownload"}  # Adicionado .crdownload
    print("[INFO] Iniciando leitor de placas...")
    print(f"[INFO] Monitorando pasta: {pasta_base}")
    print(f"[INFO] Confiança mínima para gravação: {confianca_gravar_texto}")

    processed_files_in_current_run = set()  # Para evitar reprocessar arquivos já vistos nesta execução

    try:
        while True:
            encontrou_novos_arquivos = False
            # Garante que a pasta base existe
            if not os.path.exists(pasta_base):
                print(f"[ERRO] Pasta base {pasta_base} não encontrada. Aguardando...")
                time.sleep(30)  # Espera mais se a pasta base sumir
                continue

            # Listar datas (subpastas)
            try:
                subpastas_data = sorted(
                    [d for d in os.listdir(pasta_base) if os.path.isdir(os.path.join(pasta_base, d))]
                )
            except FileNotFoundError:
                print(f"[WARN] Pasta base {pasta_base} desapareceu durante listagem. Tentando novamente.")
                time.sleep(5)
                continue

            for data_dir in subpastas_data:
                pasta_data = os.path.join(pasta_base, data_dir)

                try:
                    # Ordenar por data de modificação para processar os mais antigos primeiro
                    arquivos_na_pasta = sorted(
                        [
                            f
                            for f in os.listdir(pasta_data)
                            if os.path.isfile(os.path.join(pasta_data, f))
                            and not any(f.endswith(ext) for ext in arquivos_ignorados)
                            and not f.startswith("~")
                        ],
                        key=lambda x: os.path.getmtime(os.path.join(pasta_data, x)),
                    )
                except FileNotFoundError:
                    print(f"[WARN] Subpasta {pasta_data} desapareceu durante listagem. Pulando.")
                    continue  # Pula para a próxima subpasta_data

                for nome_arquivo in arquivos_na_pasta:
                    caminho_arquivo = os.path.join(pasta_data, nome_arquivo)

                    if caminho_arquivo in processed_files_in_current_run:
                        continue  # Já processado nesta sessão

                    # Checagem adicional de arquivo temporário (ex: lock files do windows)
                    if nome_arquivo.startswith("~$") or nome_arquivo.endswith(".lock"):
                        print(f"[INFO] Ignorando arquivo de lock/temporário: {nome_arquivo}")
                        continue

                    print(f"[INFO] Processando arquivo: {caminho_arquivo}")
                    processar_imagem(caminho_arquivo)
                    processed_files_in_current_run.add(caminho_arquivo)  # Adiciona ao set de processados
                    encontrou_novos_arquivos = True
                    # Pequena pausa para não sobrecarregar I/O ou CPU, e permitir que o buffer do DB seja enviado
                    # time.sleep(0.1)

            # Se não encontrou novos arquivos, descarrega o buffer e espera mais tempo
            if not encontrou_novos_arquivos:
                flush_buffer_leituras()  # Garante que o buffer seja salvo antes de uma longa espera
                # print("[INFO] Nenhum arquivo novo encontrado. Aguardando...")
                time.sleep(10)  # Tempo de espera original
            else:
                # Se encontrou arquivos, pode ser que haja mais chegando, espera um pouco menos
                # ou apenas continua o loop para verificar rapidamente.
                # flush_buffer_leituras() # Salva o que tiver no buffer após um ciclo de processamento
                time.sleep(1)  # Espera curta se houve processamento

            # Limpar o set de arquivos processados periodicamente para evitar consumo excessivo de memória
            # se o script rodar por muitos dias e processar milhões de arquivos únicos.
            if len(processed_files_in_current_run) > 10000:  # Ajuste este número conforme necessário
                print("[INFO] Limpando cache de nomes de arquivos processados.")
                processed_files_in_current_run.clear()
                gc.collect()

    except KeyboardInterrupt:
        print("\n[INFO] Interrupção pelo usuário detectada. Finalizando...")
    except Exception as e_main:
        print(f"[ERRO_FATAL] Erro inesperado no loop principal: {e_main}")
    finally:
        print("[INFO] Finalizando o programa. Salvando leituras pendentes e fechando conexão com DB.")
        close_db_connection()  # Garante que tudo seja salvo e a conexão fechada
        print("[INFO] Programa finalizado.")


# Handler para sinais de terminação (ex: systemctl stop)
def signal_handler(signum, frame):
    print(f"[INFO] Sinal {signal.Signals(signum).name} recebido. Finalizando graciosamente...")
    # Isso vai quebrar o loop while True e ir para o finally block
    raise KeyboardInterrupt  # Reutiliza a lógica de KeyboardInterrupt para limpeza


if __name__ == "__main__":
    # Registrar handlers para SIGINT (Ctrl+C) e SIGTERM (finalização)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()