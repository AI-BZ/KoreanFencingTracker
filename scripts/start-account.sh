#!/bin/bash
# Account Service Startup Script (for launchd)
# Uses /opt/fencingmind/ paths to avoid macOS TCC ~/Documents EINTR issue
# Python 3.13 ARM64-native

BASE="/Users/gyejinpark/opt/fencingmind/account"

export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${BASE}:${BASE}/packages:${BASE}/services/account"
export COOKIE_DOMAIN=".fencingmind.ai"

cd "${BASE}"

# Load .env if exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

exec /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    -m uvicorn services.account.app.server:app --host 0.0.0.0 --port 9070
