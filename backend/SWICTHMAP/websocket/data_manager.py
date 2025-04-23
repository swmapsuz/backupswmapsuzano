import json
import os
import threading
import hashlib
import time
from datetime import datetime
from rwlock import RWLock
import logging
from copy import deepcopy  # Importar deepcopy

logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self, filepath, socketio):
        self.filepath = filepath
        self.trusted_hostnames_path = os.path.join(os.path.dirname(filepath), "trusted_hostnames.json")
        self.rwlock = RWLock()
        self.data = self._load_initial_data()
        self._dirty = False
        self.last_hash = self._get_file_hash()
        self.last_trusted_hash = self._get_trusted_file_hash()
        self.socketio = socketio
        threading.Thread(target=self._sync_to_disk, daemon=True).start()
        threading.Thread(target=self._monitor_file_changes, daemon=True).start()
        threading.Thread(target=self._monitor_trusted_hostnames_changes, daemon=True).start()
        threading.Thread(target=self._cleanup_priority_ips, daemon=True).start()

    def _load_initial_data(self):
        try:
            with open(self.filepath, "r", encoding="utf-8") as arquivo:
                data = json.load(arquivo)
                if "priority_ips" not in data:
                    data["priority_ips"] = {}
                if "trusted_hostnames" not in data:
                    data["trusted_hostnames"] = self._load_trusted_hostnames()
                hosts = data.get("hosts", [])
                unique_hosts = {host["ip"]: host for host in hosts if "ip" in host}.values()
                data["hosts"] = list(unique_hosts)
                if len(data["hosts"]) < len(hosts):
                    logger.warning(f"Removidas {len(hosts) - len(data['hosts'])} entradas duplicadas em hosts")
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            initial_data = {"hosts": [], "pending_edits": [], "priority_ips": {}, "trusted_hostnames": self._load_trusted_hostnames()}
            with open(self.filepath, "w", encoding="utf-8") as arquivo:
                json.dump(initial_data, arquivo, indent=4, ensure_ascii=False)
            return initial_data

    def _load_trusted_hostnames(self):
        try:
            with open(self.trusted_hostnames_path, "r", encoding="utf-8") as arquivo:
                return json.load(arquivo)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(f"Arquivo {self.trusted_hostnames_path} não encontrado ou inválido, usando lista vazia")
            return []

    def get_data(self):
        with self.rwlock.reader_lock:
            return deepcopy(self.data)  # Usar deepcopy para evitar referências

    def update_data(self, new_data):
        with self.rwlock.writer_lock:
            if "hosts" in new_data:
                hosts = new_data["hosts"]
                unique_hosts = {host["ip"]: host for host in hosts if "ip" in host}.values()
                new_data["hosts"] = list(unique_hosts)
                if len(new_data["hosts"]) < len(hosts):
                    logger.warning(f"Removidas {len(hosts) - len(new_data['hosts'])} entradas duplicadas em update_data")
            
            if new_data != self.data:
                logger.debug("Dados mudaram, atualizando arquivo")
                self.data = deepcopy(new_data)  # Garantir que self.data seja uma nova cópia
                self._dirty = True
                self._sync_to_disk_immediate()
            else:
                logger.debug("Dados não mudaram, nenhuma gravação necessária")
        self.socketio.emit('data_updated', new_data, namespace='/')

    def _sync_to_disk_immediate(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as arquivo:
                json.dump(self.data, arquivo, indent=4, ensure_ascii=False)
            logger.debug(f"Dados gravados em {self.filepath}")
            self._dirty = False
            self.last_hash = self._get_file_hash()
        except Exception as e:
            logger.error(f"Erro ao gravar dados.json: {str(e)}")
            
    def _sync_to_disk(self):
        while True:
            if self._dirty:
                self._sync_to_disk_immediate()
            time.sleep(10)

    def _get_file_hash(self):
        try:
            with open(self.filepath, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except FileNotFoundError:
            return ""

    def _get_trusted_file_hash(self):
        try:
            with open(self.trusted_hostnames_path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except FileNotFoundError:
            return ""

    def _monitor_file_changes(self):
        while True:
            current_hash = self._get_file_hash()
            if current_hash != self.last_hash and current_hash:
                logger.info(f"Detectada mudança externa em dados.json")
                with self.rwlock.writer_lock:
                    try:
                        with open(self.filepath, "r", encoding="utf-8") as arquivo:
                            new_data = json.load(arquivo)
                            # Remover duplicatas ao detectar mudanças externas
                            hosts = new_data.get("hosts", [])
                            unique_hosts = {host["ip"]: host for host in hosts if "ip" in host}.values()
                            new_data["hosts"] = list(unique_hosts)
                            self.data = new_data
                            self.socketio.emit('data_updated', self.get_data(), namespace='/')
                    except json.JSONDecodeError:
                        logger.error("Erro ao carregar dados.json após mudança")
                self.last_hash = current_hash
            time.sleep(5)

    def _monitor_trusted_hostnames_changes(self):
        while True:
            current_hash = self._get_trusted_file_hash()
            if current_hash != self.last_trusted_hash and current_hash:
                logger.info(f"Detectada mudança externa em trusted_hostnames.json")
                with self.rwlock.writer_lock:
                    self.data["trusted_hostnames"] = self._load_trusted_hostnames()
                    self._dirty = True
                    self._sync_to_disk_immediate()
                    self.socketio.emit('data_updated', self.get_data(), namespace='/')
                self.last_trusted_hash = current_hash
            time.sleep(5)

    def _cleanup_priority_ips(self):
        while True:
            with self.rwlock.writer_lock:
                current_time = datetime.now()
                priority_ips = self.data.get("priority_ips", {})
                expired_ips = [
                    ip for ip, timestamp in priority_ips.items()
                    if (current_time - datetime.fromisoformat(timestamp)).total_seconds() > 300
                ]
                if expired_ips:
                    for ip in expired_ips:
                        del priority_ips[ip]
                    self.data["priority_ips"] = priority_ips
                    self._dirty = True
                    logger.info(f"Removidos {len(expired_ips)} IPs prioritários expirados")
            time.sleep(60)