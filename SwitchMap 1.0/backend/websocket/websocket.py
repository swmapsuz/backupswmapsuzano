import logging

logger = logging.getLogger(__name__)

def register_websocket(socketio, data_manager):
    @socketio.on("connect")
    def handle_connect():
        logger.debug("Cliente conectado ao WebSocket")
        socketio.emit('data_updated', data_manager.get_data())

    @socketio.on("subscribe_to_updates")
    def handle_subscription():
        logger.debug("Cliente inscrito para atualizações em tempo real")