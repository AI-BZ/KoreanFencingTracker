#!/bin/bash
# FencingMind Data Server 관리 스크립트
# launchd (com.fencingmind.data) 연동 + 수동 관리 지원
#
# 사용법: ./scripts/fencingmind-server.sh {start|stop|restart|status|logs|tail}

SERVICE_NAME="com.fencingmind.data"
PLIST="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"
PORT=9071
LOG_DIR="$HOME/Library/Logs/FencingMind"
LOG_FILE="${LOG_DIR}/data-server.log"
ERROR_LOG="${LOG_DIR}/data-server.error.log"

# 로그 디렉토리 생성
mkdir -p "${LOG_DIR}"

get_pid() {
    local pid=$(pgrep -f "uvicorn.*app.server:app.*--port ${PORT}" 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        echo "$pid"
        return 0
    fi
    return 1
}

is_launchd_loaded() {
    launchctl list 2>/dev/null | grep -q "$SERVICE_NAME"
}

do_start() {
    local pid=$(get_pid)
    if [ -n "$pid" ]; then
        echo "✅ 이미 실행 중 (PID: $pid, PORT: $PORT)"
        return 0
    fi

    echo "🚀 FencingMind Data Server 시작..."

    # 로그 로테이션 (10MB 초과 시)
    for f in "$LOG_FILE" "$ERROR_LOG"; do
        if [ -f "$f" ] && [ $(stat -f%z "$f" 2>/dev/null || echo 0) -gt 10485760 ]; then
            mv "$f" "${f}.$(date +%Y%m%d_%H%M%S)"
            echo "📋 로그 로테이션: $(basename $f)"
        fi
    done

    if [ -f "$PLIST" ]; then
        # launchd로 시작 (권장)
        if ! is_launchd_loaded; then
            launchctl load "$PLIST" 2>&1
        else
            launchctl kickstart "gui/$(id -u)/$SERVICE_NAME" 2>&1 || \
            launchctl start "$SERVICE_NAME" 2>&1
        fi
        echo "   방식: launchd (자동 재시작 활성화)"
    else
        echo "⚠️ launchd plist 없음, 수동 시작..."
        local PROJECT_DIR="/Users/gyejinpark/Documents/GitHub/FencingMind-data/services/data"
        local PYTHON="/Users/gyejinpark/opt/anaconda3/bin/python"
        cd "$PROJECT_DIR"
        PYTHONPATH="${PROJECT_DIR}:${PROJECT_DIR}/../../packages" \
            nohup "$PYTHON" -m uvicorn app.server:app --host 0.0.0.0 --port "$PORT" \
            >> "$LOG_FILE" 2>> "$ERROR_LOG" &
        echo "   방식: 수동 (PID: $!)"
    fi

    echo "   포트: $PORT"
    echo "   로그: $LOG_FILE"

    # 서버 준비 대기 (최대 60초)
    echo -n "   대기 중"
    for i in $(seq 1 60); do
        sleep 1
        echo -n "."
        if curl -s -o /dev/null -w "" http://localhost:${PORT}/ 2>/dev/null; then
            echo ""
            local new_pid=$(get_pid)
            echo "✅ 서버 시작 완료 (PID: $new_pid)"
            return 0
        fi
    done
    echo ""
    echo "⚠️ 서버 로딩 중... (데이터 로드에 시간이 걸릴 수 있음)"
}

do_stop() {
    local pid=$(get_pid)
    if [ -z "$pid" ]; then
        echo "⏹ 서버가 실행 중이 아닙니다."
        return 0
    fi

    echo "⏹ 서버 중지 중 (PID: $pid)..."

    # launchd 언로드 (KeepAlive 재시작 방지)
    if is_launchd_loaded; then
        launchctl unload "$PLIST" 2>/dev/null
        echo "   launchd 서비스 언로드됨 (자동 재시작 비활성화)"
    else
        kill "$pid" 2>/dev/null
    fi

    # 종료 대기
    for i in $(seq 1 10); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "✅ 서버 중지 완료"
            return 0
        fi
        sleep 1
    done

    kill -9 "$pid" 2>/dev/null
    echo "✅ 서버 강제 중지 완료"
}

do_restart() {
    do_stop
    sleep 2
    do_start
}

do_status() {
    local pid=$(get_pid)
    if [ -n "$pid" ]; then
        echo "✅ FencingMind Data Server 실행 중"
        echo "   PID: $pid"
        echo "   PORT: $PORT"
        echo "   메모리: $(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.0f MB", $1/1024}')"
        echo "   시작: $(ps -o lstart= -p "$pid" 2>/dev/null | xargs)"
        echo "   로그: $LOG_FILE"

        if is_launchd_loaded; then
            echo "   launchd: ✅ 등록됨 (자동 재시작 활성화)"
        else
            echo "   launchd: ⚠️ 미등록 (수동 모드)"
        fi

        local http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${PORT}/ 2>/dev/null)
        if [ "$http_code" = "200" ] || [ "$http_code" = "302" ]; then
            echo "   HTTP: ✅ 응답 정상 ($http_code)"
        else
            echo "   HTTP: ⚠️ 응답 이상 ($http_code)"
        fi

        # 로그 파일 크기
        if [ -f "$LOG_FILE" ]; then
            local size=$(du -sh "$LOG_FILE" 2>/dev/null | cut -f1)
            echo "   로그 크기: $size"
        fi
    else
        echo "⏹ FencingMind Data Server 중지 상태"
        if is_launchd_loaded; then
            echo "   launchd: ✅ 등록됨 (시작 시도 중일 수 있음)"
        else
            echo "   launchd: ❌ 미등록"
        fi
    fi
}

do_logs() {
    if [ -f "$LOG_FILE" ]; then
        less +G "$LOG_FILE"
    else
        echo "로그 파일 없음: $LOG_FILE"
    fi
}

do_tail() {
    local lines=${2:-50}
    if [ -f "$LOG_FILE" ]; then
        echo "📋 로그 파일: $LOG_FILE"
        echo "   에러 로그: $ERROR_LOG"
        echo "   Ctrl+C로 종료"
        echo "---"
        tail -f -n "$lines" "$LOG_FILE"
    else
        echo "로그 파일 없음: $LOG_FILE"
    fi
}

do_enable() {
    if [ ! -f "$PLIST" ]; then
        echo "❌ plist 없음: $PLIST"
        return 1
    fi
    launchctl load "$PLIST" 2>&1
    echo "✅ launchd 서비스 활성화 (부팅 시 자동 시작)"
}

do_disable() {
    launchctl unload "$PLIST" 2>/dev/null
    echo "✅ launchd 서비스 비활성화 (수동 시작만 가능)"
}

case "$1" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    logs)    do_logs ;;
    tail)    do_tail "$@" ;;
    enable)  do_enable ;;
    disable) do_disable ;;
    *)
        echo "FencingMind Data Server 관리"
        echo "사용법: $0 {start|stop|restart|status|logs|tail|enable|disable}"
        echo ""
        echo "  start   - 서버 시작 (launchd 우선)"
        echo "  stop    - 서버 중지 (launchd 언로드 포함)"
        echo "  restart - 서버 재시작"
        echo "  status  - 서버 상태 확인"
        echo "  logs    - 로그 보기 (less)"
        echo "  tail    - 실시간 로그 (tail -f)"
        echo "  enable  - launchd 자동 시작 활성화"
        echo "  disable - launchd 자동 시작 비활성화"
        exit 1
        ;;
esac
