#!/usr/bin/env bash
# =============================================================================
# 战舰棋 —— 外网中转（经云服务器）
# =============================================================================
# 为什么需要它：
#   本机到 GitHub / PyPI 的连接**时通时断**（同一分钟内 `git ls-remote` 会
#   一次成功、一次 Connection reset；winget 拉 GitHub Releases 直接失败），
#   而云服务器可以稳定直连 GitHub（仓库已配 Deploy Key）。
#   因此把云服务器当作外网出口：本机开一个 SSH 动态转发（SOCKS5），
#   所有 HTTP(S) 流量借它出去。
#
# 实测带宽（2026-09-15，同一时段）：
#   中转 SOCKS5  → GitHub   1.2 MB/s
#   本机直连     → GitHub   1.9 MB/s（但会随机 reset）
#   清华 PyPI 镜像          4.2 MB/s  ← 纯下载用镜像最快，不必中转
#   结论：git 之类「小而必须可靠」的走中转；大文件下载优先用国内镜像。
#
# 用法：
#   bash tools/relay.sh start          启动 SOCKS5 代理（默认 127.0.0.1:1080）
#   bash tools/relay.sh stop           停掉
#   bash tools/relay.sh status         看状态
#   bash tools/relay.sh test           连通性 + 速度实测
#   bash tools/relay.sh env            打印可直接 eval 的环境变量
#   bash tools/relay.sh git <git参数>  经代理执行 git（例：git fetch origin）
#   bash tools/relay.sh pip <pip参数>  用清华镜像执行 pip（例：install -r requirements.txt）
#
# 由 DSH 代理维护。
# =============================================================================

set -uo pipefail

SERVER_HOST="${RELAY_HOST:-8.133.180.159}"
SERVER_USER="${RELAY_USER:-root}"
SERVER_PORT="${RELAY_SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_aliyun}"
SOCKS_PORT="${RELAY_PORT:-1080}"
PID_FILE="$HOME/.battleship-relay.pid"
LOG_FILE="$HOME/.battleship-relay.log"
PIP_MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
log()  { echo "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo "${GREEN}  ✓${NC} $*"; }
warn() { echo "${YELLOW}  !${NC} $*"; }
err()  { echo "${RED}  ✗${NC} $*" >&2; }

proxy_url() { echo "socks5h://127.0.0.1:$SOCKS_PORT"; }

# 代理是否在监听（用 curl 真连一次，比看 PID 靠谱）
proxy_alive() {
  curl -s -o /dev/null --max-time 8 -x "$(proxy_url)" https://github.com/ 2>/dev/null
}

pid_of() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE" 2>/dev/null || true
}

running() {
  local p; p="$(pid_of)"
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}

cmd_start() {
  if running && proxy_alive; then
    ok "代理已在运行（PID $(pid_of)，端口 $SOCKS_PORT）"
    return 0
  fi
  if running; then
    warn "PID $(pid_of) 还在但代理不通，重启"
    cmd_stop >/dev/null 2>&1
  fi

  log "建立 SSH 动态转发 → $SERVER_USER@$SERVER_HOST:$SOCKS_PORT"
  # ServerAliveInterval：防止空闲被中间设备断开；ExitOnForwardFailure：端口占用时立刻失败而不是静默假成功
  nohup ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 \
      -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o ExitOnForwardFailure=yes \
      -N -D "$SOCKS_PORT" -p "$SERVER_PORT" "$SERVER_USER@$SERVER_HOST" \
      >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  local i
  for i in $(seq 1 20); do
    sleep 0.5
    if proxy_alive; then
      ok "代理就绪：$(proxy_url)  (PID $(pid_of)，日志 $LOG_FILE)"
      return 0
    fi
    running || { err "SSH 进程已退出，日志："; tail -5 "$LOG_FILE" >&2; rm -f "$PID_FILE"; return 1; }
  done
  err "代理 10 秒内未就绪，日志："; tail -5 "$LOG_FILE" >&2; return 1
}

cmd_stop() {
  if running; then
    kill "$(pid_of)" 2>/dev/null
    sleep 1
    running && kill -9 "$(pid_of)" 2>/dev/null
    ok "已停止（PID $(pid_of)）"
  else
    warn "没有在运行的代理"
  fi
  rm -f "$PID_FILE"
}

cmd_status() {
  echo "  服务器   : $SERVER_USER@$SERVER_HOST:$SERVER_PORT"
  echo "  代理地址 : $(proxy_url)"
  if running; then
    ok "SSH 进程存活（PID $(pid_of)）"
    if proxy_alive; then ok "代理连通（经它访问 github.com 成功）"; else err "代理不通"; fi
  else
    err "未运行（bash tools/relay.sh start 启动）"
  fi
  if [ -f "$LOG_FILE" ]; then
    echo "  最近日志 :"; tail -3 "$LOG_FILE" | sed 's/^/    /'
  fi
}

# 5MB 抽测：直连 vs 中转，同一素材
speed_test() {
  local url="https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip"
  local extra="$1" label="$2"
  printf "  %-14s " "$label"
  # -w 里只用 ASCII：中文经函数调用后在某些控制台会被按 GBK 解码成乱码
  # shellcheck disable=SC2086
  curl -sL -o /dev/null --max-time 45 $extra -r 0-5000000 \
    -w "HTTP %{http_code}  %{speed_download} B/s\n" "$url" 2>/dev/null || echo "failed"
}

cmd_test() {
  echo "${BOLD}== 中继连通性 ==${NC}"
  if proxy_alive; then ok "经代理访问 github.com 成功"; else err "经代理不通（先 start）"; fi
  echo
  echo "${BOLD}== 速度对比（同一下载，5MB）==${NC}"
  speed_test "" "本机直连"
  speed_test "-x $(proxy_url)" "经服务器中转"
  printf "  %-14s " "清华 PyPI 镜像"
  # 同上：-w 只用 ASCII，中文在这种嵌套调用里会被控制台按 GBK 解码成乱码
  curl -s -o /dev/null --max-time 30 -w "HTTP %{http_code}  %{speed_download} B/s\n" "$PIP_MIRROR/" 2>/dev/null || echo "failed"
  echo
  echo "${BOLD}== git 经代理 ==${NC}"
  if proxy_alive; then
    git -c "http.proxy=$(proxy_url)" ls-remote https://github.com/xiaoxiaoyiiii/battle_ship1.0 refs/heads/main 2>&1 | sed 's/^/    /'
  else
    warn "代理未运行，跳过"
  fi
}

cmd_env() {
  echo "export ALL_PROXY=$(proxy_url)"
  echo "export HTTPS_PROXY=$(proxy_url)"
  echo "export HTTP_PROXY=$(proxy_url)"
  echo "export NO_PROXY=localhost,127.0.0.1"
}

cmd_git() {
  running || { err "代理未运行，先执行: bash tools/relay.sh start"; exit 1; }
  git -c "http.proxy=$(proxy_url)" "$@"
}

cmd_pip() {
  # 注意：pip 走 SOCKS 需要 PySocks，本机没有；纯下载用国内镜像又快又稳，不必中转。
  exec python -m pip "$@" --index-url "$PIP_MIRROR" --trusted-host "$(echo "$PIP_MIRROR" | sed -E 's#https?://([^/]+).*#\1#')"
}

case "${1:-status}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  test)   cmd_test ;;
  env)    cmd_env ;;
  git)    shift; cmd_git "$@" ;;
  pip)    shift; cmd_pip "$@" ;;
  -h|--help|help) sed -n '2,40p' "$0" ;;
  *) err "未知命令: $1（可用: start stop status test env git pip）"; exit 2 ;;
esac
