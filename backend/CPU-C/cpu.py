from flask import Flask, render_template
from flask_socketio import SocketIO
import psutil
import eventlet
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route("/")
def index():
    return render_template("index.html")

def get_port_info(ports):
    """Obtém informações sobre processos nas portas especificadas."""
    port_data = {}
    for port in ports:
        port_data[port] = {"status": "Livre", "process": None, "pid": None}
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                try:
                    process = psutil.Process(conn.pid)
                    port_data[port] = {
                        "status": "Em uso",
                        "process": process.name(),
                        "pid": conn.pid
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    port_data[port] = {
                        "status": "Em uso",
                        "process": "Desconhecido",
                        "pid": conn.pid
                    }
                break
    return port_data

def send_system_stats():
    """Envia estatísticas do sistema e informações de portas em tempo real."""
    monitored_ports = [5000, 3000, 8080]
    last_net_io = psutil.net_io_counters()
    last_time = time.time()

    while True:
        # Uso da CPU, memória e disco
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Uso de rede (KB/s)
        current_net_io = psutil.net_io_counters()
        current_time = time.time()
        time_diff = current_time - last_time
        bytes_sent_diff = current_net_io.bytes_sent - last_net_io.bytes_sent
        bytes_recv_diff = current_net_io.bytes_recv - last_net_io.bytes_recv
        net_usage = (bytes_sent_diff + bytes_recv_diff) / 1024 / time_diff  # KB/s

        last_net_io = current_net_io
        last_time = current_time

        # Informações das portas
        port_info = get_port_info(monitored_ports)

        # Envia todos os dados para o frontend
        stats = {
            "cpu": cpu_usage,
            "memory": memory.percent,
            "disk": disk.percent,
            "network": net_usage,  # Substitui temperatura por uso de rede
            "ports": port_info
        }
        socketio.emit("system_stats", stats)
        eventlet.sleep(1)

@socketio.on("connect")
def handle_connect():
    print("Cliente conectado!")
    eventlet.spawn(send_system_stats)

if __name__ == "__main__":
    socketio.run(app, host="172.16.196.36", port=8050, debug=True)