"""Club Service Configuration"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Server
PORT = int(os.getenv("CLUB_PORT", "72"))
HOST = os.getenv("CLUB_HOST", "0.0.0.0")
DEBUG = os.getenv("CLUB_DEBUG", "true").lower() == "true"

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Kakao (Phase 2)
KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID", "")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", f"http://localhost:{PORT}/auth/kakao/callback")

# Data Service (선수 데이터 API 호출용)
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://localhost:71")

# FCM (Firebase Cloud Messaging)
FCM_CREDENTIALS_PATH = os.getenv("FCM_CREDENTIALS_PATH", "")  # Firebase service account JSON

# Kakao Alimtalk (비즈메시지 API)
ALIMTALK_API_KEY = os.getenv("ALIMTALK_API_KEY", "")
ALIMTALK_API_SECRET = os.getenv("ALIMTALK_API_SECRET", "")
ALIMTALK_SENDER_PHONE = os.getenv("ALIMTALK_SENDER_PHONE", "")
KAKAO_CHANNEL_ID = os.getenv("KAKAO_CHANNEL_ID", "")  # 카카오톡 채널 pfId

# PortOne (결제)
PORTONE_API_SECRET = os.getenv("PORTONE_API_SECRET", "")
PORTONE_STORE_ID = os.getenv("PORTONE_STORE_ID", "")
PORTONE_CHANNEL_KEY = os.getenv("PORTONE_CHANNEL_KEY", "")

# Test Mode
TEST_MODE = os.getenv("CLUB_TEST_MODE", "0") == "1"
DEFAULT_ORG_ID = int(os.getenv("DEFAULT_ORG_ID", "401"))  # 최병철펜싱클럽
