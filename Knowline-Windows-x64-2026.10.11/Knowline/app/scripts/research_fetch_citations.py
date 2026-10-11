"""Compatibility CLI for the bundled, provider-independent citation auditor."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.citation_audit import main
if __name__=='__main__':main()
