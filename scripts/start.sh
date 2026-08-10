#!/bin/bash
# FencingMind Service Manager
# Usage: ./scripts/start.sh [start|stop|status]

set -euo pipefail

# Project root: resolve from script location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PID_DIR="$ROOT/.pids"
LOG_DIR="$ROOT/logs"

# Service definitions: name:port
# Ports 9070-9076 reserved for FencingMind (unprivileged; no sudo needed)
# nginx listens on 9090 and proxies to these ports
SERVICES=("account:9070" "data:9071" "club:9072")

# Analytics lives in a separate worktree
ANALYTICS_ROOT="/Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics"
ANALYTICS_PORT=9076

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

ensure_dirs() {
    mkdir -p "$PID_DIR" "$LOG_DIR"
}

is_running() {
    local pidfile="$PID_DIR/$1.pid"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        # Stale PID file
        rm -f "$pidfile"
    fi
    return 1
}

start_nginx() {
    if is_running nginx; then
        log_warn "nginx is already running"
        return
    fi
    log_info "Starting nginx..."
    # nginx now listens on unprivileged 9090 — sudo no longer required
    nginx
    # nginx manages its own PID, but store master PID for our tracking
    if pgrep -x nginx > /dev/null; then
        pgrep -x nginx | head -1 > "$PID_DIR/nginx.pid"
        log_info "nginx started (PID $(cat "$PID_DIR/nginx.pid"))"
    else
        log_error "Failed to start nginx"
    fi
}

stop_nginx() {
    log_info "Stopping nginx..."
    nginx -s stop 2>/dev/null || true
    rm -f "$PID_DIR/nginx.pid"
    log_info "nginx stopped"
}

start_cloudflared() {
    if is_running cloudflared; then
        log_warn "cloudflared is already running"
        return
    fi
    log_info "Starting cloudflared tunnel..."
    nohup cloudflared tunnel run > "$LOG_DIR/cloudflared.log" 2>&1 &
    echo $! > "$PID_DIR/cloudflared.pid"
    log_info "cloudflared started (PID $!)"
}

stop_cloudflared() {
    if is_running cloudflared; then
        local pid
        pid=$(cat "$PID_DIR/cloudflared.pid")
        log_info "Stopping cloudflared (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        rm -f "$PID_DIR/cloudflared.pid"
        log_info "cloudflared stopped"
    else
        log_warn "cloudflared is not running"
    fi
}

start_service() {
    local name="$1"
    local port="$2"

    if is_running "$name"; then
        log_warn "$name service is already running"
        return
    fi

    local pythonpath="${ROOT}:${ROOT}/packages:${ROOT}/services/${name}"

    log_info "Starting $name service on port $port..."
    PYTHONPATH="$pythonpath" nohup python -m uvicorn \
        "services.${name}.app.server:app" \
        --host 0.0.0.0 \
        --port "$port" \
        > "$LOG_DIR/${name}.log" 2>&1 &
    echo $! > "$PID_DIR/${name}.pid"
    log_info "$name started (PID $!)"
}

stop_service() {
    local name="$1"

    if is_running "$name"; then
        local pid
        pid=$(cat "$PID_DIR/$name.pid")
        log_info "Stopping $name service (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        rm -f "$PID_DIR/$name.pid"
        log_info "$name stopped"
    else
        log_warn "$name service is not running"
    fi
}

start_analytics() {
    if is_running analytics; then
        log_warn "analytics service is already running"
        return
    fi

    log_info "Starting analytics service on port $ANALYTICS_PORT..."
    PYTHONPATH="$ANALYTICS_ROOT" nohup "$ANALYTICS_ROOT/.venv/bin/python3" -m uvicorn \
        "app.server:app" \
        --host 127.0.0.1 \
        --port "$ANALYTICS_PORT" \
        > "$LOG_DIR/analytics.log" 2>&1 &
    echo $! > "$PID_DIR/analytics.pid"
    log_info "analytics started (PID $!)"
}

stop_analytics() {
    stop_service analytics
}

do_start() {
    ensure_dirs
    log_info "Starting FencingMind services..."
    echo ""

    start_nginx
    start_cloudflared

    for svc in "${SERVICES[@]}"; do
        local name="${svc%%:*}"
        local port="${svc##*:}"
        start_service "$name" "$port"
    done

    start_analytics

    echo ""
    log_info "All services started. Use '$0 status' to check."
}

do_stop() {
    log_info "Stopping FencingMind services..."
    echo ""

    stop_analytics

    for svc in "${SERVICES[@]}"; do
        local name="${svc%%:*}"
        stop_service "$name"
    done

    stop_cloudflared
    stop_nginx

    echo ""
    log_info "All services stopped."
}

do_status() {
    echo ""
    echo "FencingMind Service Status"
    echo "=========================="

    # nginx
    if is_running nginx; then
        echo -e "  nginx         ${GREEN}RUNNING${NC}  (PID $(cat "$PID_DIR/nginx.pid"))"
    else
        echo -e "  nginx         ${RED}STOPPED${NC}"
    fi

    # cloudflared
    if is_running cloudflared; then
        echo -e "  cloudflared   ${GREEN}RUNNING${NC}  (PID $(cat "$PID_DIR/cloudflared.pid"))"
    else
        echo -e "  cloudflared   ${RED}STOPPED${NC}"
    fi

    # FastAPI services
    for svc in "${SERVICES[@]}"; do
        local name="${svc%%:*}"
        local port="${svc##*:}"
        local padded
        padded=$(printf "%-13s" "$name")
        if is_running "$name"; then
            echo -e "  ${padded} ${GREEN}RUNNING${NC}  (PID $(cat "$PID_DIR/$name.pid"), port $port)"
        else
            echo -e "  ${padded} ${RED}STOPPED${NC}  (port $port)"
        fi
    done

    # Analytics (separate worktree)
    if is_running analytics; then
        echo -e "  analytics       ${GREEN}RUNNING${NC}  (PID $(cat "$PID_DIR/analytics.pid"), port $ANALYTICS_PORT)"
    else
        echo -e "  analytics       ${RED}STOPPED${NC}  (port $ANALYTICS_PORT)"
    fi

    echo ""
}

# Main
case "${1:-start}" in
    start)  do_start ;;
    stop)   do_stop ;;
    status) do_status ;;
    *)
        echo "Usage: $0 [start|stop|status]"
        exit 1
        ;;
esac
