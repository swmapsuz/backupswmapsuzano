import json
import aiohttp
import os
import time
import logging
import asyncio

logger = logging.getLogger(__name__)

CAMINHO_RESULTADOS_JSON = r"c:\ENTUITY\resultados.json"
URL_JSON = "https://api-security-swmap.vercel.app/APIhosts.json"
HOSTNAMES_FILE = r"c:\ENTUITY\hostnames.json"

def carregar_resultados():
    try:
        with open(CAMINHO_RESULTADOS_JSON, "r", encoding="utf-8") as arquivo:
            data = json.load(arquivo)
            # Garantir que o resultado é uma lista
            if not isinstance(data, list):
                logger.error(f"resultados.json deve ser uma lista, encontrado: {type(data)}")
                return []
            return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erro ao carregar resultados.json: {str(e)}")
        return []

async def obter_hostnames_confiaveis():
    async with aiohttp.ClientSession() as session:
        try:
            logger.debug(f"Tentando buscar hostnames de {URL_JSON}")
            async with session.get(URL_JSON, timeout=aiohttp.ClientTimeout(total=5), ssl=False) as response:
                logger.debug(f"Resposta do servidor: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    hostnames = data.get("hostnames", [])
                    logger.debug(f"Hostnames recebidos: {hostnames}")
                    return hostnames
                else:
                    logger.error(f"Falha na requisição: Status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Erro ao buscar hostnames: {type(e).__name__}: {str(e)}")
            return []

def atualizar_valores_dos_hosts(data_manager, auto_create_hosts=False):
    resultados = carregar_resultados()
    if not resultados:
        logger.warning("Nenhum resultado carregado de resultados.json")
        return False
    
    dados = data_manager.get_data()
    hosts_dict = {host["ip"]: host for host in dados.get("hosts", [])}
    
    updated_ips = []
    for resultado in resultados:
        ip = resultado.get("IP")
        if not ip or ip == "IP não encontrado":
            logger.warning(f"Ignorando entrada com IP inválido: Nome SW {resultado.get('Nome SW', 'desconhecido')}")
            continue
        if ip not in hosts_dict and auto_create_hosts:
            # Criar novo host se não existir
            new_host = {
                "ip": ip,
                "nome": resultado.get("Nome SW", f"Host_{ip}"),
                "ativo": "green",
                "conexoes": [],
                "local": "",
                "ship": "",
                "tipo": "sw",
                "tempo_resposta": -1,
                "valores": [],
                "ports": []
            }
            hosts_dict[ip] = new_host
            logger.info(f"Criado novo host para IP {ip}: {new_host['nome']}")
        if ip in hosts_dict:
            hosts_dict[ip]["valores"] = resultado.get("Valores", [])
            ports = resultado.get("Ports", [])
            if not all(isinstance(port, dict) for port in ports):
                logger.error(f"Formato inválido de Ports para IP {ip}: {ports}")
                hosts_dict[ip]["ports"] = []
            else:
                hosts_dict[ip]["ports"] = ports
                updated_ips.append(ip)
                logger.info(f"Atualizado valores e ports para IP {ip}")
        else:
            logger.debug(f"IP {ip} não encontrado em hosts_dict")
    
    dados["hosts"] = list(hosts_dict.values())
    data_manager.update_data(dados)
    if updated_ips:
        logger.info(f"Hosts atualizados com sucesso: {updated_ips}")
        return True
    else:
        logger.warning("Nenhum host foi atualizado com valores ou ports")
        return False

def load_hostnames():
    try:
        with open(HOSTNAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("hostnames", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erro ao carregar hostnames: {str(e)}")
        return {}