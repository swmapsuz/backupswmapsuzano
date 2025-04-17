import asyncio
from icmplib import async_ping
import time
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from typing import Dict, List, Tuple, Set
from datetime import datetime
from flask_socketio import SocketIO  # ALTERAÇÃO: Importar SocketIO

logger = logging.getLogger(__name__)

async def verificar_ping(ip: str, is_priority: bool = False) -> Tuple[str, int]:
    """
    Verifica o status de um IP via ping.
    
    Args:
        ip: Endereço IP a ser verificado
        is_priority: Se True, usa parâmetros mais agressivos para IPs prioritários
    
    Returns:
        Tuple (status, tempo_resposta): 
        - status: "#00d700" (online), "red" (offline)
        - tempo_resposta: Em ms ou -1 se offline
    """
    attempts = 3 if is_priority else 2
    timeout = 1 if is_priority else 2
    try:
        result = await async_ping(ip, count=attempts, timeout=timeout, privileged=False)
        if result.is_alive:
            return "#00d700", int(result.avg_rtt)  # Online
        logger.debug(f"IP {ip} offline: tempo_resposta=-1")  # ALTERAÇÃO: Log para IPs offline
        return "red", -1  # Offline
    except Exception as e:
        logger.debug(f"Ping {ip}: ERRO - {str(e)}")
        return "red", -1

async def processar_chunk(chunk: List[Dict], priority_ips_set: Set[str]) -> Dict[str, Tuple[str, int]]:
    """
    Processa um conjunto de hosts e suas conexões em paralelo, retornando apenas os resultados de ping.
    
    Args:
        chunk: Lista de hosts para verificar
        priority_ips_set: Conjunto de IPs prioritários
    
    Returns:
        Dict mapeando IP para (status, tempo_resposta)
    """
    tasks = []
    ip_map = []  # Para mapear tasks aos IPs
    
    for host in chunk:
        ip = host["ip"]
        tasks.append(verificar_ping(ip, ip in priority_ips_set))
        ip_map.append(ip)
        
        if "conexoes" in host:
            for conexao in host["conexoes"]:
                if conexao.get("ip"):
                    tasks.append(verificar_ping(conexao["ip"], conexao["ip"] in priority_ips_set))
                    ip_map.append(conexao["ip"])
    
    results = await asyncio.gather(*tasks)
    return dict(zip(ip_map, results))

def init_ping_service(data_manager, socketio: SocketIO) -> None:  # ALTERAÇÃO: Adicionar socketio como parâmetro
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    max_workers = min(os.cpu_count() or 1, 4)
    chunk_size = 50
    
    @socketio.on('host_updated')  # ALTERAÇÃO: Escutar evento host_updated
    def handle_host_updated(data):
        ip = data['ip']
        logger.info(f"Forçando ping para IP atualizado: {ip}")
        priority_ips = data_manager.get_data().get('priority_ips', {})
        status, tempo = loop.run_until_complete(verificar_ping(ip, ip in priority_ips))
        dados = data_manager.get_data()
        for host in dados['hosts']:
            if host['ip'] == ip:
                host['ativo'] = status
                host['tempo_resposta'] = tempo
                logger.debug(f"IP {ip} atualizado: status={status}, tempo={tempo}")
                break
        data_manager.update_data(dados)

    while True:
        try:
            start_time = time.time()
            dados = data_manager.get_data()
            hosts_originais = dados.get("hosts", [])
            priority_ips = dados.get("priority_ips", {})
            priority_ips_set = set(priority_ips.keys())
            
            if not hosts_originais:
                logger.warning("Nenhum host encontrado para processar")
                time.sleep(60)
                continue

            logger.info(f"Iniciando atualização de pings para {len(hosts_originais)} hosts")
            
            hosts_para_processar = hosts_originais.copy()
            ping_results = {}
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for i in range(0, len(hosts_para_processar), chunk_size):
                    chunk = hosts_para_processar[i:i + chunk_size]
                    futures.append(
                        executor.submit(
                            lambda c: loop.run_until_complete(
                                processar_chunk(c, priority_ips_set)
                            ),
                            chunk
                        )
                    )
                
                for future in futures:
                    ping_results.update(future.result())
            
            # Obter os dados mais recentes após os pings
            dados_atualizados = data_manager.get_data()
            total_validados = 0
            total_ips = len(ping_results)
            
            # Atualizar apenas os campos gerenciados pelo ping_service
            for host in dados_atualizados["hosts"]:
                ip = host["ip"]
                if ip in ping_results:
                    status, tempo = ping_results[ip]
                    host["ativo"] = status
                    host["tempo_resposta"] = tempo
                    if status == "#00d700":
                        total_validados += 1
                
                if "conexoes" in host:
                    for conexao in host["conexoes"]:
                        conn_ip = conexao.get("ip")
                        if conn_ip in ping_results:
                            status, tempo = ping_results[conn_ip]
                            conexao["ativo"] = status
                            conexao["tempo_resposta"] = tempo
                            if status == "#00d700":
                                total_validados += 1
            
            # Adicionar timestamp da última atualização
            dados_atualizados["last_update"] = datetime.utcnow().isoformat() + "Z"
            
            logger.debug("Enviando dados atualizados para DataManager")
            data_manager.update_data(dados_atualizados)
            
            elapsed_time = time.time() - start_time
            logger.info(
                f"Atualização concluída em {elapsed_time:.2f}s | "
                f"Online: {total_validados}/{total_ips} | "
                f"IPs prioritários: {len(priority_ips_set)}"
            )
            
            base_interval = 10 if priority_ips_set else 30  # ALTERAÇÃO: Reduzir intervalo para 30s
            sleep_time = max(base_interval, elapsed_time * 1.5)
            time.sleep(sleep_time)
            
        except Exception as e:
            logger.error(f"Erro crítico no ping_service: {str(e)}", exc_info=True)
            time.sleep(60)