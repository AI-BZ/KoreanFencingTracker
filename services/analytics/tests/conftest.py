"""Analytics test configuration - adds services/analytics to sys.path."""
import sys
from pathlib import Path

# Ensure services/analytics is on PYTHONPATH for imports
analytics_root = Path(__file__).resolve().parent.parent
if str(analytics_root) not in sys.path:
    sys.path.insert(0, str(analytics_root))
