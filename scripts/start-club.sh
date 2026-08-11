#!/bin/bash
# Club Service Startup Script (for launchd)
# Uses /opt/fencingmind/ paths to avoid macOS TCC ~/Documents EINTR issue
# Python 3.13 ARM64-native

BASE="/Users/gyejinpark/opt/fencingmind/club"

export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${BASE}:${BASE}/packages:${BASE}/services/club"
export CLUB_TEST_MODE=1
export ACCOUNT_SERVICE_URL="https://account.fencingmind.ai"

cd "${BASE}"

# Load .env if exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

exec /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    -m uvicorn services.club.app.server:app --host 0.0.0.0 --port 9072
