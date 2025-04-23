from flask import jsonify, request, render_template, Response
import socket
import time
import logging
from datetime import datetime
from utils import obter_hostnames_confiaveis, atualizar_valores_dos_hosts, load_hostnames
import asyncio
import json

logger = logging.getLogger(__name__)

def register_routes(app, data_manager, limiter):
    # @app.route("/get-data", methods=["GET"])
    # @limiter.limit("50 per minute")
    # def get_data():
    #     start_time = time.time()
    #     try:
    #         hostname_cliente = socket.gethostbyaddr(request.remote_addr)[0] if request.remote_addr else "Desconhecido"
    #     except socket.herror:
    #         hostname_cliente = "Desconhecido"
    #         logger.debug(f"Não foi possível resolver hostname para {request.remote_addr}")

    #     dados = data_manager.get_data()
    #     hostnames_confiaveis = dados.get("trusted_hostnames", [])
    #     if hostname_cliente not in hostnames_confiaveis:
    #         logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - 🚫 ACESSO NEGADO para {hostname_cliente}")
    #         return jsonify({"erro": "Acesso não autorizado"}), 403

    #     logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ✅ Dados consultados por {hostname_cliente}")
    #     total_time = time.time() - start_time
    #     logger.debug(f"Tempo total de /get-data: {total_time:.3f}s")
    #     return jsonify(dados)

    @app.route("/prioritize-pings", methods=["POST"])
    @limiter.limit("20 per minute")
    def prioritize_pings():
        try:
            data = request.get_json()
            ips = data.get("ips", [])
            if not isinstance(ips, list):
                return jsonify({"erro": "O campo 'ips' deve ser uma lista"}), 400

            dados = data_manager.get_data()
            priority_ips = dados.get("priority_ips", {})
            current_time = datetime.now().isoformat()
            valid_ips = {host["ip"] for host in dados["hosts"]}
            accepted_ips = []
            rejected_ips = []

            for ip in ips:
                if ip in valid_ips:
                    priority_ips[ip] = current_time
                    accepted_ips.append(ip)
                else:
                    rejected_ips.append(ip)

            dados["priority_ips"] = priority_ips
            data_manager.update_data(dados)
            
            logger.info(f"{len(accepted_ips)} IPs marcados para priorização, {len(rejected_ips)} rejeitados")
            return jsonify({
                "mensagem": f"{len(accepted_ips)} IPs marcados",
                "accepted": accepted_ips,
                "rejected": rejected_ips
            }), 200
        except Exception as e:
            logger.error(f"Erro ao priorizar IPs: {str(e)}")
            return jsonify({"erro": "Falha ao priorizar IPs"}), 500

    @app.route("/refresh-trusted-hostnames", methods=["POST"])
    def refresh_trusted_hostnames():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            hostnames = loop.run_until_complete(obter_hostnames_confiaveis())
            loop.close()
            
            dados = data_manager.get_data()
            dados["trusted_hostnames"] = hostnames
            data_manager.update_data(dados)
            logger.info("Hostnames confiáveis atualizados manualmente")
            return jsonify({"mensagem": "Hostnames atualizados com sucesso"}), 200
        except Exception as e:
            logger.error(f"Erro ao atualizar hostnames: {str(e)}")
            return jsonify({"erro": "Falha ao atualizar hostnames"}), 500

    @app.route("/download-dados", methods=["GET"])
    @limiter.limit("50 per minute")
    def download_dados():
        start_time = time.time()
        try:
            hostname_cliente = socket.gethostbyaddr(request.remote_addr)[0] if request.remote_addr else "Desconhecido"
        except socket.herror:
            hostname_cliente = "Desconhecido"
            logger.debug(f"Não foi possível resolver hostname para {request.remote_addr}")

        dados = data_manager.get_data()
        hostnames_confiaveis = dados.get("trusted_hostnames", [])
        if hostname_cliente not in hostnames_confiaveis:
            logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - 🚫 ACESSO NEGADO para {hostname_cliente} em /download-dados")
            return jsonify({"erro": "Acesso não autorizado"}), 403

        json_data = json.dumps(dados, indent=4, ensure_ascii=False)
        logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ✅ Dados baixados por {hostname_cliente}")
        total_time = time.time() - start_time
        logger.debug(f"Tempo total de /download-dados: {total_time:.3f}s")
        return Response(
            json_data,
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=dados.json"}
        )

    @app.route("/editar-host", methods=["PUT"])
    @limiter.limit("20 per minute")
    def editar_host():
        try:
            dados_formulario = request.get_json()
            ip = dados_formulario.get("ip")
            novos_dados = {k: v for k, v in dados_formulario.items() if v is not None and k != "ip"}

            if not ip:
                return jsonify({"erro": "O campo 'ip' é obrigatório"}), 400

            dados = data_manager.get_data()
            hosts_dict = {host["ip"]: host for host in dados["hosts"]}
            if ip not in hosts_dict:
                return jsonify({"erro": "Host não encontrado"}), 404

            edit_id = str(len(dados.get("pending_edits", [])) + 1)
            solicitacao = {
                "id": edit_id,
                "ip": ip,
                **novos_dados,
                "solicitante": socket.gethostname(),
                "data_solicitacao": datetime.now().isoformat(),
                "status": "pendente"
            }

            dados["pending_edits"] = dados.get("pending_edits", []) + [solicitacao]
            data_manager.update_data(dados)
            logger.info(f"Solicitação de edição enviada para IP {ip} (ID: {edit_id})")
            return jsonify({"mensagem": "Solicitação enviada!", "solicitacao": solicitacao}), 200
        except Exception as e:
            logger.error(f"Erro ao editar host: {str(e)}")
            return jsonify({"erro": "Falha ao enviar solicitação"}), 500

    @app.route("/pending-edits", methods=["GET"])
    @limiter.limit("50 per minute")
    def listar_pendentes():
        dados = data_manager.get_data()
        pendentes = [edit for edit in dados.get("pending_edits", []) if edit["status"] == "pendente"]
        logger.debug(f"Listando {len(pendentes)} edições pendentes")
        return jsonify(pendentes), 200

    @app.route("/approve-edit/<edit_id>", methods=["POST"])
    @limiter.limit("20 per minute")
    def aprovar_edicao(edit_id):
        try:
            dados = data_manager.get_data()
            edit = next((e for e in dados["pending_edits"] if e["id"] == edit_id and e["status"] == "pendente"), None)
            if not edit:
                return jsonify({"erro": "Edição não encontrada ou já processada"}), 404

            hosts_dict = {host["ip"]: host for host in dados["hosts"]}
            if edit["ip"] in hosts_dict:
                hosts_dict[edit["ip"]].update(
                    {k: v for k, v in edit.items() if k not in ["id", "solicitante", "data_solicitacao", "status"]}
                )
            edit["status"] = "aprovado"
            dados["hosts"] = list(hosts_dict.values())
            data_manager.update_data(dados)
            logger.info(f"Edição {edit_id} aprovada para IP {edit['ip']}")
            return jsonify({"mensagem": "Edição aprovada!"}), 200
        except Exception as e:
            logger.error(f"Erro ao aprovar edição {edit_id}: {str(e)}")
            return jsonify({"erro": "Falha ao aprovar edição"}), 500

    @app.route("/reject-edit/<edit_id>", methods=["DELETE"])
    @limiter.limit("20 per minute")
    def rejeitar_edicao(edit_id):
        try:
            dados = data_manager.get_data()
            edit = next((e for e in dados["pending_edits"] if e["id"] == edit_id and e["status"] == "pendente"), None)
            if not edit:
                return jsonify({"erro": "Edição não encontrada ou já processada"}), 404

            edit["status"] = "rejeitado"
            data_manager.update_data(dados)
            logger.info(f"Edição {edit_id} rejeitada para IP {edit['ip']}")
            return jsonify({"mensagem": "Edição rejeitada!"}), 200
        except Exception as e:
            logger.error(f"Erro ao rejeitar edição {edit_id}: {str(e)}")
            return jsonify({"erro": "Falha ao rejeitar edição"}), 500

    @app.route("/", methods=["GET"])
    def index():
        return render_template("realtime.html")

    @app.route("/status", methods=["GET"])
    @limiter.limit("100 per minute")
    def obter_status():
        return get_data()

    @app.route("/adicionar-host", methods=["POST"])
    @limiter.limit("20 per minute")
    def adicionar_host():
        try:
            dados_formulario = request.get_json()
            novo_host = {
                "ativo": dados_formulario.get("ativo", "green"),
                "conexoes": dados_formulario.get("conexoes", []),
                "ip": dados_formulario.get("ip"),
                "local": dados_formulario.get("local", ""),
                "nome": dados_formulario.get("nome"),
                "ship": dados_formulario.get("ship", ""),
                "tipo": dados_formulario.get("tipo", "sw"),
                "tempo_resposta": -1
            }

            if not novo_host["ip"] or not novo_host["nome"]:
                return jsonify({"erro": "Campos 'ip' e 'nome' obrigatórios"}), 400

            dados = data_manager.get_data()
            hosts_dict = {host["ip"]: host for host in dados["hosts"]}
            if novo_host["ip"] in hosts_dict:
                return jsonify({"erro": "Host já existe"}), 400

            dados["hosts"] = dados["hosts"] + [novo_host]
            data_manager.update_data(dados)
            logger.info(f"Host {novo_host['ip']} adicionado com sucesso")
            return jsonify({"mensagem": "Host adicionado!", "host": novo_host}), 201
        except Exception as e:
            logger.error(f"Erro ao adicionar host: {str(e)}")
            return jsonify({"erro": "Falha ao adicionar host"}), 500

    @app.route("/get-user-info", methods=["GET"])
    @limiter.limit("100 per minute")
    def get_user_info():
        try:
            hostname_cliente = socket.gethostbyaddr(request.remote_addr)[0] if request.remote_addr else "Desconhecido"
        except socket.herror:
            hostname_cliente = "Desconhecido"
            logger.debug(f"Não foi possível resolver hostname para {request.remote_addr}")

        hostnames_dict = load_hostnames()
        user_type = hostnames_dict.get(hostname_cliente, "guest")

        logger.info(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ℹ️ Informações consultadas por {hostname_cliente} ({user_type})")
        return jsonify({
            "hostname": hostname_cliente,
            "user_type": user_type
        }), 200