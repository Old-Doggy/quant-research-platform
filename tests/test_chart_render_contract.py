"""Every Plotly entry uses the same interaction and export configuration."""
import ast
from pathlib import Path


def test_every_plotly_entry_uses_shared_chart_configuration():
    root=Path(__file__).resolve().parents[1]/'portfolio_app'
    missing=[]
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for call in ast.walk(tree):
            if not (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                    and call.func.attr=='plotly_chart'):
                continue
            config=next((k.value for k in call.keywords if k.arg=='config'),None)
            if not isinstance(config,ast.Name) or config.id!='CHART_CONFIG':
                missing.append(f'{path.name}:{call.lineno}')
    assert not missing,'Inconsistent chart interactions: '+', '.join(missing)
