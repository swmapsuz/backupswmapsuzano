import subprocess
import time
from datetime import datetime
import sys
import os

def run_command(command, error_message):
    """Executa um comando no shell e trata erros."""
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
        log_message(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        log_message(f"Erro: {error_message}\n{e.stderr}")
        print(f"Erro: {error_message}\n{e.stderr}")
        return False

def log_message(message):
    """Salva mensagens no arquivo de log."""
    with open("deploy_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()}: {message}\n")

def ensure_git_config():
    """Garante que o diretório é seguro e o repositório está configurado."""
    run_command("git config --global --add safe.directory /", "Falha ao configurar diretório seguro")
    run_command("git remote set-url origin https://github.com/swmapsuz/backupswmapsuzano.git", 
                "Falha ao configurar repositório remoto")

def create_gitignore():
    """Cria ou atualiza o .gitignore se necessário."""
    gitignore_content = """
node_modules/
*.lnk
.env
*.exe
__pycache__/
*.pyc
"""
    if not os.path.exists(".gitignore"):
        with open(".gitignore", "w") as f:
            f.write(gitignore_content)
        log_message("Arquivo .gitignore criado.")
        print("Arquivo .gitignore criado.")
    else:
        with open(".gitignore", "r") as f:
            if "node_modules/" not in f.read():
                with open(".gitignore", "a") as f:
                    f.write(gitignore_content)
                log_message("Arquivo .gitignore atualizado.")
                print("Arquivo .gitignore atualizado.")

def create_gitattributes():
    """Cria ou atualiza o .gitattributes para evitar avisos de LF/CRLF."""
    gitattributes_content = """
* text=auto
*.json text eol=lf
*.js text eol=lf
*.py text eol=lf
"""
    if not os.path.exists(".gitattributes"):
        with open(".gitattributes", "w") as f:
            f.write(gitattributes_content)
        log_message("Arquivo .gitattributes criado.")
        print("Arquivo .gitattributes criado.")
        # Reaplica as alterações para corrigir finais de linha
        run_command("git rm --cached -r .", "Falha ao limpar cache")
        run_command("git reset --hard", "Falha ao resetar")
        run_command("git add .", "Falha ao adicionar arquivos")
        run_command('git commit -m "Corrige finais de linha"', "Falha ao commitar correção de finais de linha")

def deploy():
    """Executa o processo de deploy."""
    print(f"\nIniciando deploy às {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    log_message(f"Iniciando deploy às {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Adiciona todos os arquivos modificados
    if not run_command("git add .", "Falha ao adicionar arquivos"):
        return

    # Verifica se há mudanças para commitar
    status = subprocess.run("git status --porcelain", shell=True, text=True, capture_output=True)
    if not status.stdout:
        print("Nenhuma mudança para commitar.")
        log_message("Nenhuma mudança para commitar.")
        return

    # Loga os arquivos alterados
    print("Arquivos alterados:")
    print(status.stdout)
    log_message(f"Arquivos alterados:\n{status.stdout}")

    # Cria commit com mensagem automática
    commit_message = f"Backup automatizado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if not run_command(f'git commit -m "{commit_message}"', "Falha ao criar commit"):
        return

    # Faz o push
    run_command("git push origin main", "Falha ao fazer push")
    print("Deploy concluído com sucesso!")
    log_message("Deploy concluído com sucesso!")

def main():
    """Loop principal que executa o deploy a cada 6 horas."""
    # Configurações iniciais
    ensure_git_config()
    create_gitignore()
    create_gitattributes()

    # Loop infinito com intervalo
    while True:
        deploy()
        print("Aguardando para o próximo deploy...")
        log_message("Aguardando para o próximo deploy...")
        time.sleep(60) 

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScript interrompido pelo usuário.")
        log_message("Script interrompido pelo usuário.")
        sys.exit(0)