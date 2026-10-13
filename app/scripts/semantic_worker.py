"""Use the same local model as the bundled application worker."""
import sys
from pathlib import Path
app=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(app))
from backend.semantic import serve
serve(app.parent)
