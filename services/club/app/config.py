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
PORT = int(os.getenv("CLUB_PORT", "75"))
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

# Test Mode
TEST_MODE = os.getenv("CLUB_TEST_MODE", "1") == "1"
DEFAULT_ORG_ID = int(os.getenv("DEFAULT_ORG_ID", "401"))  # 최병철펜싱클럽
