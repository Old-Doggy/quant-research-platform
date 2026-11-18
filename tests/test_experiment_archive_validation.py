from io import BytesIO
import hashlib
import json
from zipfile import ZipFile

import pytest

from portfolio_app.experiments import build_experiment, open_experiment, save_experiment


def valid_archive():
    from test_strategy_timing_gate import bars
    return build_experiment(bars().drop(columns=['roe', 'pb']), dict(
        mode='single', symbols=['AAA'], strategy_key='trend', transaction_cost=.001))


def rewrite(data, change):
    with ZipFile(BytesIO(data)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(files['manifest.json'])
    change(manifest, files)
    files['manifest.json'] = json.dumps(manifest).encode()
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as out:
        for name, body in files.items():
            out.writestr(name, body)
    return buffer.getvalue()


@pytest.mark.parametrize('field,value', [('metrics', []), ('metrics', {'total_return':'bad'}),
    ('spec', []), ('name', None), ('created_at', 123)])
def test_invalid_presentation_metadata_is_rejected(field, value):
    data = rewrite(valid_archive(), lambda meta, files: meta.update({field: value}))
    with pytest.raises(ValueError):
        open_experiment(data)


def test_missing_curve_columns_with_valid_checksum_are_rejected():
    def change(meta, files):
        files['result.csv'] = b'trade_date,value\n2025-01-02,1\n'
        meta['result_sha256'] = hashlib.sha256(files['result.csv']).hexdigest()
    with pytest.raises(ValueError):
        open_experiment(rewrite(valid_archive(), change))


def test_invalid_experiment_does_not_hide_good_saved_curve(tmp_path):
    from streamlit.testing.v1 import AppTest
    save_experiment(tmp_path, valid_archive())
    (tmp_path/'bad.zip').write_bytes(rewrite(valid_archive(), lambda meta, files: meta.update(metrics=[])))
    app = AppTest.from_string('''
from pathlib import Path
import pandas as pd
import streamlit as st
from portfolio_app.experiment_view import render_experiments
render_experiments(pd.DataFrame(), dict(mode='single',strategy_key='trend',symbols=['AAA']), Path(st.session_state['root']))
''')
    app.session_state['root'] = str(tmp_path)
    app.run()
    assert not app.exception
    assert len(app.get('plotly_chart')) == 1
    assert any('跳过' in warning.value for warning in app.warning)
