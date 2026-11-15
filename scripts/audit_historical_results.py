"""Write a reproducible aggregate audit without loading private research inputs."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portfolio_app.historical_result_audit import audit_published_results

if __name__ == '__main__':
    result = audit_published_results(ROOT)
    destination = ROOT / 'output/m1-historical-audit.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(f"{result['status']}: {len(result['models'])} models, {len(result['curves'])} curves")
    raise SystemExit(0 if result['status'] == 'passed' else 1)
