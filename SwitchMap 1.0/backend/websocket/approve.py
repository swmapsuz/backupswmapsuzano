import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO
import logging
import os
import json
from datetime import datetime
from data_manager import DataManager
import re

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("approve_logs.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Inicialização do aplicativo Flask
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Caminhos para os arquivos de dados
CAMINHO_DADOS_JSON = os.path.join(os.getcwd(), "dados.json")
CAMINHO_APROVACOES = os.path.join(os.getcwd(), "aprovacoes_pendentes.json")
CAMINHO_HISTORICO = os.path.join(os.getcwd(), "alteracoes.json")

# Instância do DataManager
data_manager = DataManager(CAMINHO_DADOS_JSON, socketio)

# Função para validar IP
def is_valid_ip(ip):
    pattern = r'^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$'
    return re.match(pattern, ip) is not None

# Função para salvar no histórico
def save_to_history(request_data):
    try:
        history = []
        if os.path.exists(CAMINHO_HISTORICO):
            with open(CAMINHO_HISTORICO, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    history = json.loads(content)
                else:
                    logger.warning("Arquivo alteracoes.json está vazio, inicializando com lista vazia")
        history.append(request_data)
        with open(CAMINHO_HISTORICO, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar alteracoes.json, inicializando com nova entrada: {str(e)}")
        history = [request_data]
        with open(CAMINHO_HISTORICO, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Erro ao salvar no histórico: {str(e)}")

# Classe para gerenciar as aprovações
class EditManager:
    def __init__(self, approvals_path):
        self.approvals_path = approvals_path

    def load_approvals(self):
        try:
            with open(self.approvals_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def save_approvals(self, approvals):
        with open(self.approvals_path, 'w', encoding='utf-8') as f:
            json.dump(approvals, f, ensure_ascii=False, indent=4)

# Instância do EditManager
edit_manager = EditManager(CAMINHO_APROVACOES)

# Rota para submeter edição
@app.route('/submit-edit', methods=['POST'])
def submit_edit():
    try:
        edit_data = request.get_json(silent=True)
        if not edit_data or 'changes' not in edit_data:
            return jsonify({'error': 'Dados inválidos'}), 400

        ip = edit_data['changes'].get('ip')
        if ip and not is_valid_ip(ip):
            logger.error(f"IP inválido na solicitação: {ip}")
            return jsonify({'error': 'IP inválido'}), 400

        approval_request = {
            'id': f"edit_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'timestamp': datetime.now().isoformat(),
            'changes': edit_data['changes'],
            'status': 'pending',
            'submitted_by': edit_data.get('user', 'anonymous')
        }

        approvals = edit_manager.load_approvals()
        approvals.append(approval_request)
        edit_manager.save_approvals(approvals)

        save_to_history(approval_request)

        socketio.emit('new_edit_request', approval_request)
        logger.info(f"Nova solicitação de edição recebida: {approval_request['id']}")
        return jsonify({'message': 'Solicitação de edição submetida', 'request_id': approval_request['id']}), 200

    except Exception as e:
        logger.error(f"Erro ao processar edição: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para editar host
@app.route('/editar-host', methods=['PUT'])
def editar_host():
    try:
        edit_data = request.get_json(silent=True)
        if not edit_data or 'ip' not in edit_data:
            logger.error(f"Corpo da requisição inválido: {request.data}")
            return jsonify({'error': 'Dados inválidos ou campo "ip" ausente'}), 400

        ip = edit_data.get('ip')
        if not is_valid_ip(ip):
            logger.error(f"IP inválido na solicitação: {ip}")
            return jsonify({'error': 'IP inválido'}), 400

        approval_request = {
            'id': f"edit_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'timestamp': datetime.now().isoformat(),
            'changes': {
                'ip': ip,
                'nome': edit_data.get('nome', ''),
                'local': edit_data.get('local', ''),
                'observacao': edit_data.get('observacao', ''),
                'tipo': edit_data.get('tipo', 'sw'),
                'ativo': edit_data.get('ativo', '#00d700')
            },
            'status': 'pending',
            'submitted_by': 'anonymous'
        }

        approvals = edit_manager.load_approvals()
        approvals.append(approval_request)
        edit_manager.save_approvals(approvals)

        save_to_history(approval_request)

        socketio.emit('new_edit_request', approval_request)
        logger.info(f"Nova solicitação de edição recebida em /editar-host: {approval_request['id']}")
        return jsonify({'message': 'Solicitação de edição submetida', 'request_id': approval_request['id']}), 200

    except Exception as e:
        logger.error(f"Erro ao processar edição em /editar-host: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para listar edições pendentes
@app.route('/pending-edits', methods=['GET'])
def get_pending_edits():
    try:
        approvals = edit_manager.load_approvals()
        pending = [req for req in approvals if req['status'] == 'pending']
        return jsonify(pending), 200
    except Exception as e:
        logger.error(f"Erro ao listar edições pendentes: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para aprovar edição
@app.route('/approve-edit/<id>', methods=['POST'])
def approve_edit_by_id(id):
    try:
        approvals = edit_manager.load_approvals()
        target_request = next((req for req in approvals if req['id'] == id), None)
        
        if not target_request:
            return jsonify({'error': 'Solicitação não encontrada'}), 404

        if target_request['status'] != 'pending':
            return jsonify({'error': 'Solicitação já processada'}), 400

        target_request['status'] = 'approve'
        target_request['processed_at'] = datetime.now().isoformat()
        target_request['processed_by'] = 'anonymous'

        current_data = data_manager.get_data()
        if 'hosts' not in current_data:
            current_data['hosts'] = []

        target_ip = target_request['changes']['ip']
        host_found = False
        for host in current_data['hosts']:
            if host.get('ip') == target_ip:
                for key, value in target_request['changes'].items():
                    if key != 'ativo' and value is not None:
                        host[key] = value
                host_found = True
                break

        if not host_found:
            new_host = {k: v for k, v in target_request['changes'].items() if k != 'ativo' and v is not None}
            current_data['hosts'].append(new_host)

        data_manager.update_data(current_data)
        edit_manager.save_approvals(approvals)

        save_to_history(target_request)

        socketio.emit('edit_status_update', target_request)
        socketio.emit('host_updated', {'ip': target_ip})
        logger.info(f"Edição aprovada: {id}, IP={target_ip}, mudanças={target_request['changes']}")
        return jsonify({'message': 'Edição aprovada com sucesso'}), 200

    except Exception as e:
        logger.error(f"Erro ao aprovar edição: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para rejeitar edição
@app.route('/reject-edit/<id>', methods=['DELETE'])
def reject_edit_by_id(id):
    try:
        approvals = edit_manager.load_approvals()
        target_request = next((req for req in approvals if req['id'] == id), None)
        
        if not target_request:
            return jsonify({'error': 'Solicitação não encontrada'}), 404

        if target_request['status'] != 'pending':
            return jsonify({'error': 'Solicitação já processada'}), 400

        target_request['status'] = 'reject'
        target_request['processed_at'] = datetime.now().isoformat()
        target_request['processed_by'] = 'anonymous'

        edit_manager.save_approvals(approvals)

        save_to_history(target_request)

        socketio.emit('edit_status_update', target_request)
        logger.info(f"Edição rejeitada: {id}")
        return jsonify({'message': 'Edição rejeitada com sucesso'}), 200

    except Exception as e:
        logger.error(f"Erro ao rejeitar edição: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para consultar o histórico
@app.route('/history', methods=['GET'])
def get_history():
    try:
        history = []
        if os.path.exists(CAMINHO_HISTORICO):
            with open(CAMINHO_HISTORICO, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    history = json.loads(content)
                else:
                    logger.warning("Arquivo alteracoes.json está vazio")
        else:
            logger.info("Arquivo alteracoes.json não existe")
        return jsonify(history), 200
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar alteracoes.json: {str(e)}")
        return jsonify(history), 200
    except Exception as e:
        logger.error(f"Erro ao consultar histórico: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ALTERAÇÃO: Rota para limpar o histórico usando GET
@app.route('/clear-history', methods=['GET'])
def clear_history():
    try:
        # Redefinir alteracoes.json para uma lista vazia
        with open(CAMINHO_HISTORICO, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=4)
        logger.info("Histórico em alteracoes.json foi limpo com sucesso via GET")
        socketio.emit('history_cleared', {'message': 'Histórico limpo'})
        return jsonify({'message': 'Histórico limpo com sucesso'}), 200
    except Exception as e:
        logger.error(f"Erro ao limpar histórico: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Evento WebSocket para conexão
@socketio.on('connect')
def handle_connect():
    logger.info('Cliente WebSocket conectado')
    socketio.emit('connection_established', {'message': 'Conectado ao servidor de aprovações'})

if __name__ == "__main__":
    logger.info("Iniciando servidor de aprovações na porta 5002...")
    socketio.run(app, host="0.0.0.0", port=5002, use_reloader=False)