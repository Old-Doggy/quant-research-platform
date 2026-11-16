import pandas as pd


def test_matrix_cells_include_pair_identity_and_missing_not_zero():
    from portfolio_app.factor_comparison import compare_factor_values
    from portfolio_app.factor_comparison_view import comparison_matrix,selected_pair
    from test_factor_comparison import sample
    result=compare_factor_values(sample(),factors=['first','second'],min_assets=3)
    figure=comparison_matrix(result,'ic_correlation',names={})
    assert figure.data[0].z[0][1] is None
    assert figure.data[0].customdata[0][1][:2]==['first','second']
    assert figure.data[1].type=='scatter'
    assert selected_pair([dict(customdata=['second','first',3,'ok'])],result)==('second','first')
    assert selected_pair([dict(customdata=['first','first',3,'ok'])],result) is None
    assert selected_pair([dict(customdata=['first','missing',3,'ok'])],result) is None


def test_actual_ui_runs_only_on_request_and_preserves_previous_on_edit(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_factor_compute import make_bars
    frame=pd.concat([make_bars().assign(symbol=s) for s in 'ABCD'])
    frame.to_parquet(tmp_path/'bars.parquet',index=False)
    monkeypatch.setenv('COMPARE_TEST_FRAME',str(tmp_path/'bars.parquet'))
    app=AppTest.from_string('''
import os
import pandas as pd
from portfolio_app.factor_comparison_view import render_factor_comparison
frame=pd.read_parquet(os.environ['COMPARE_TEST_FRAME'])
render_factor_comparison(frame,names={},public_mode=True)
''',default_timeout=30).run()
    assert not app.exception and not app.get('plotly_chart')
    app.button(key='factor_compare_run').click().run()
    import time
    for _ in range(30):
        if app.exception or app.get('plotly_chart') or app.error:
            break
        time.sleep(.1)
        app.run()
    assert not app.exception and app.get('plotly_chart')
    app.multiselect(key='factor_compare_ids').set_value(['basic.return_5d','basic.return_20d']).run()
    assert not app.exception and not app.get('plotly_chart')
    assert any('重新计算' in info.value for info in app.info)
