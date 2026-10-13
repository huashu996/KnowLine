"""Write a discovery manifest from service receipts, without reports or network calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.discovery_finish import finalize
from backend.layout import project_root


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('context')
    parser.add_argument('--reason', help='Actual reason when the frozen full-text target cannot be met')
    args = parser.parse_args()
    print(json.dumps(finalize(project_root(Path(__file__).resolve().parents[1]), args.context, args.reason), ensure_ascii=False))
