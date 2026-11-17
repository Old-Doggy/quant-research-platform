from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest
from portfolio_app.local_project_curves import load_project_curve
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("workspace", ["watch", "factors", "strategy", "portfolio", "data", "experiments", "showcase"])
def test_fresh_checkout_opens_every_workspace(monkeypatch, tmp_path, workspace):
 monkeypatch.setenv("PORTFOLIO_MODE", "local")
 monkeypatch.setenv("PORTFOLIO_STATE_DIR", str(tmp_path / "state"))
 monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(tmp_path / "no-market"))
 app=AppTest.from_file(str(ROOT / "streamlit_app.py"),default_timeout=40)
 app.run()
 app.radio(key='workspace_route_selector').set_value(workspace).run()
 assert not app.exception
 assert app.sidebar.radio[0].options == ["看盘", "因子", "策略", "组合", "数据", "实验", "作品"]
 assert app.radio(key='workspace_route_selector').value==workspace
 assert not any('无效工作区链接' in item.value for item in app.warning)
 assert not app.error


def test_all_published_curves_load_without_private_research_tree():
 paths=list((ROOT/'public_evidence/curves').glob('*.json'))
 assert len(paths)==11
 for path in paths:
  source=json.loads(path.read_text(encoding='utf-8'))
  actual=load_project_curve(ROOT,source['model'],source['scenario'])
  assert actual['status']=='available'
  assert actual['points']==source['points']
  assert not any((ROOT/p).exists() for p in ['data/output','模型7','股票库筛选'])


def test_published_curve_rejects_changed_drawdown(tmp_path):
 import shutil
 source=next((ROOT/'public_evidence/curves').glob('*.json'))
 target=tmp_path/'public_evidence/curves'/source.name;target.parent.mkdir(parents=True)
 data=json.loads(source.read_text(encoding='utf-8'));data['points'][3]['drawdown']=-.9
 target.write_text(json.dumps(data),encoding='utf-8')
 assert load_project_curve(tmp_path,data['model'],data['scenario'])['status']=='missing_or_invalid'
