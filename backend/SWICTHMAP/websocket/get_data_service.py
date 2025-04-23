from flask import Flask, jsonify, request
import socket
import logging
import json
import os
import time
import requests
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("get_data_logs.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DATA_FILE = r"dados.json"
RESULTADOS_FILE = r"A:\SwitchMap\backend\ENTUITY\resultados.json"
TRUSTED_HOSTNAMES_URL = "https://api-security-swmap.vercel.app/APIhosts.json"

trusted_hostnames_cache = None
last_fetch_time = 0
CACHE_DURATION = 300

def load_json_data(file_path):
    """Carrega um arquivo JSON com tratamento de erros."""
    try:
        if not os.path.exists(file_path):
            logger.error(f"Arquivo {file_path} não encontrado.")
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.debug(f"Dados carregados de {file_path} com sucesso.")
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON em {file_path}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Erro ao carregar {file_path}: {str(e)}")
        return None

def fetch_trusted_hostnames():
    """Obtém hostnames confiáveis da URL remota ou cache."""
    global trusted_hostnames_cache, last_fetch_time
    current_time = time.time()

    if trusted_hostnames_cache is not None and (current_time - last_fetch_time) < CACHE_DURATION:
        logger.debug("Usando hostnames confiáveis do cache.")
        return trusted_hostnames_cache

    try:
        response = requests.get(TRUSTED_HOSTNAMES_URL, timeout=5, verify=False)
        response.raise_for_status()
        data = response.json()
        hostnames = data.get("hostnames", [])
        if isinstance(hostnames, list):
            trusted_hostnames_cache = hostnames
            last_fetch_time = current_time
            logger.info(f"Hostnames confiáveis atualizados do endpoint remoto: {hostnames}")
            return hostnames
        else:
            logger.error("A chave 'hostnames' no JSON remoto não contém uma lista válida.")
            return trusted_hostnames_cache or []
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar hostnames de {TRUSTED_HOSTNAMES_URL}: {str(e)}")
        return trusted_hostnames_cache or []
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON remoto: {str(e)}")
        return trusted_hostnames_cache or []

def merge_data(dados, resultados):
    """Mescla dados de resultados.json com dados.json em memória."""
    if not dados or not isinstance(dados.get("hosts", []), list):
        logger.error("Estrutura inválida de dados.json: 'hosts' não é uma lista.")
        return dados

    if not resultados or not isinstance(resultados, list):
        logger.error("Estrutura inválida de resultados.json: não é uma lista.")
        return dados

    # Criar uma cópia profunda para evitar modificar o original
    merged_data = json.loads(json.dumps(dados))
    hosts_dict = {host["ip"]: host for host in merged_data.get("hosts", [])}
    
    updated_ips = []
    for resultado in resultados:
        ip = resultado.get("IP")
        if not ip or ip == "IP não encontrado":
            logger.warning(f"Ignorando entrada com IP inválido: Nome SW {resultado.get('Nome SW', 'desconhecido')}")
            continue
        if ip in hosts_dict:
            hosts_dict[ip]["valores"] = resultado.get("Valores", [])
            ports = resultado.get("Ports", [])
            if not all(isinstance(port, dict) for port in ports):
                logger.error(f"Formato inválido de Ports para IP {ip}: {ports}")
                hosts_dict[ip]["ports"] = []
            else:
                hosts_dict[ip]["ports"] = ports
                updated_ips.append(ip)
                logger.info(f"Mesclado valores e ports para IP {ip}")
        else:
            logger.debug(f"IP {ip} não encontrado em hosts_dict")

    merged_data["hosts"] = list(hosts_dict.values())
    if updated_ips:
        logger.info(f"Hosts mesclados com sucesso: {updated_ips}")
    else:
        logger.warning("Nenhum host foi mesclado com valores ou ports")
    
    return merged_data

@app.route("/get-data", methods=["GET"])
def get_data():
    start_time = time.time()
    try:
        hostname_cliente = socket.gethostbyaddr(request.remote_addr)[0] if request.remote_addr else "Desconhecido"
        logger.debug(f"Hostname resolvido para {request.remote_addr}: {hostname_cliente}")
    except socket.herror:
        hostname_cliente = "Desconhecido"
        logger.debug(f"Não foi possível resolver hostname para {request.remote_addr}")

    # Carregar dados.json
    dados = load_json_data(DATA_FILE)
    if not dados:
        return jsonify({"erro": "Falha ao carregar dados.json"}), 500

    # Carregar resultados.json
    resultados = load_json_data(RESULTADOS_FILE)
    if not resultados:
        logger.warning("resultados.json não carregado; retornando dados.json sem mesclagem")
        # Prosseguir com dados.json mesmo sem resultados.json

    # Mesclar dados
    logger.info("Mesclando dados.json com resultados.json")
    merged_data = merge_data(dados, resultados)

    # Autenticação
    hostnames_confiaveis = fetch_trusted_hostnames()
    if not hostnames_confiaveis:
        hostnames_confiaveis = dados.get("trusted_hostnames", [])
        logger.warning("Usando hostnames confiáveis do arquivo local como fallback.")

    hostname_cliente_lower = hostname_cliente.lower()
    hostnames_confiaveis_lower = [h.lower() for h in hostnames_confiaveis]
    logger.debug(f"Hostnames confiáveis (lower): {hostnames_confiaveis_lower}")
    logger.debug(f"Hostname cliente (lower): {hostname_cliente_lower}")

    if hostname_cliente_lower not in hostnames_confiaveis_lower:
        logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - 🚫 ACESSO NEGADO para {hostname_cliente}")
        return jsonify({"erro": "Acesso não autorizado"}), 403

    # Adicionar metadados
    merged_data["timestamp"] = time.strftime('%Y-%m-%d %H:%M:%S')
    merged_data["source"] = "merged_data"

    logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ✅ Dados mesclados consultados por {hostname_cliente}")
    total_time = time.time() - start_time
    logger.debug(f"Tempo total de /get-data: {total_time:.3f}s")
    return jsonify(merged_data), 200, {'Cache-Control': 'no-cache'}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)