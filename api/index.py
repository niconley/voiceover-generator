import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from frontend.app import app

# Vercel expects a WSGI callable named 'app' or 'handler'
handler = app
