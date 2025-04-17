import eventlet
eventlet.monkey_patch()

import urllib3
from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from flask_compress import Compress
import threading
import socket
import os
import sys
import logging
from data_manager import DataManager
from ping_service import init_ping_service  # Usando init_ping_service conforme corrigido
from api_routes import register_routes
from websocket import register_websocket
from utils import atualizar_valores_dos_hosts  # Mantido, mas removido obter_hostnames_confiaveis

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ping_logs.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
app.config['COMPRESS_MIMETYPES'] = ['application/json']
app.config['COMPRESS_LEVEL'] = 6
Compress(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet", engineio_logger=False)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://"
)

CAMINHO_DADOS_JSON = os.path.join(os.getcwd(), "dados.json")

ascii_art = """
 ____          _ _       _     __  __             
/ ___|_      _(_) |_ ___| |__ |  \/  | __ _ _ __  
\___ \ \ /\ / / | __/ __| '_ \| |\/| |/ _` | '_ \ 
 ___) \ V  V /| | || (__| | | | |  | | (_| | |_) |
|____/ \_/\_/ |_|\__\___|_| |_|_|  |_|__,_| .__/ 
                                           |_|    
Desenvolvido por Pedro Lucas Sousa Moura
"""
print(ascii_art)

data_manager = DataManager(CAMINHO_DADOS_JSON, socketio)

if __name__ == "__main__":
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        logger.info(f"Servidor iniciando em {local_ip}:5000")
    except Exception as e:
        logger.error(f"Erro ao determinar IP local: {str(e)}")
        local_ip = "0.0.0.0"

    # ALTERAÇÃO: Removido carregamento de hostnames via API
    # Carregar dados iniciais e atualizar valores dos hosts (se necessário)
    logger.info("Inicializando dados e atualizando valores dos hosts")
    atualizar_valores_dos_hosts(data_manager)
    
    register_routes(app, data_manager, limiter)
    register_websocket(socketio, data_manager)
    
    logger.info("Iniciando serviço de ping em thread separada")
    ping_thread = threading.Thread(target=init_ping_service, args=(data_manager, socketio), daemon=True)
    ping_thread.start()
    
    socketio.run(app, host="0.0.0.0", port=5000, use_reloader=False)