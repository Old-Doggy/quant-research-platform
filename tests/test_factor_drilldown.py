import copy

import pandas as pd
import pytest


def sample():
    return dict(run_id='known', config={'min_assets_per_date': 3, 'label_horizon_sessions': 5},
        analysis={'ic_series': [dict(trade_date='2025-01-02', ic=.5, status='ok', observations=3),
            dict(trade_date='2025-01-03', ic=-1., status='ok', observations=3),
            dict(trade_date='2025-04-01', ic=None, status='constant_factor', observations=3)]},
        detail=[dict(trade_date=day, symbol=symbol, factor=factor, forward_label=label)
            for day, factors, labels in [('2025-01-02', [1., 2., 3.], [.1, .3, .2]),
                ('2025-01-03', [1., 2., 3.], [.3, .2, .1]),
                ('2025-04-01', [1., 1., 1.], [.1, .2, .3])]
            for symbol, factor, label in zip(['AAA', 'BBB', 'CCC'], factors, labels)])


def test_date_scatter_ranks_reproduce_saved_ic_and_preserve_result():
    from portfolio_app.factor_drilldown import factor_cross_section
    result = sample(); before = copy.deepcopy(result)
    section = factor_cross_section(result, '2025-01-02')
    assert section['ic'] == pytest.approx(.5)
    assert section['samples'] == 3
    assert section['frame'].label_rank.tolist() == [1., 3., 2.]
    assert section['frame'].factor_rank.corr(section['frame'].label_rank) == pytest.approx(.5)
    assert result == before


def test_period_statistics_use_valid_days_and_keep_empty_periods():
    from portfolio_app.factor_drilldown import factor_periods
    periods = factor_periods(sample()).set_index('period')
    assert periods.loc['2025Q1', 'ic_mean'] == pytest.approx(-.25)
    assert periods.loc['2025Q1', 'positive_ratio'] == .5
    assert periods.loc['2025Q1', 'ic_std'] == pytest.approx(pd.Series([.5, -1.]).std())
    assert periods.loc['2025Q2', 'sessions'] == 1
    assert periods.loc['2025Q2', 'valid_sessions'] == 0
    assert pd.isna(periods.loc['2025Q2', 'ic_mean'])


def test_invalid_date_tampered_ic_duplicate_security_and_unavailable_values():
    from portfolio_app.factor_drilldown import factor_cross_section
    result = sample()
    with pytest.raises(ValueError, match='日期'): factor_cross_section(result, '2025-01-06')
    result['analysis']['ic_series'][0]['ic'] = .6
    with pytest.raises(ValueError, match='不一致'): factor_cross_section(result, '2025-01-02')
    result = sample(); result['detail'].append(result['detail'][0])
    with pytest.raises(ValueError, match='重复'): factor_cross_section(result, '2025-01-02')
    unavailable = factor_cross_section(sample(), '2025-04-01')
    assert unavailable['ic'] is None
    assert unavailable['status'] == 'constant_factor'


def test_ties_use_average_ranks_without_inventing_a_valid_ic():
    from portfolio_app.factor_drilldown import factor_cross_section
    result = sample()
    result['detail'][0]['factor'] = 2.
    result['analysis']['ic_series'][0]['ic'] = 0.
    section = factor_cross_section(result, '2025-01-02')
    assert section['frame'].factor_rank.tolist() == [1.5, 1.5, 3.]
    assert section['ic'] == pytest.approx(0.)


def test_page_changes_cross_section_and_quarter_table_without_recalculation(tmp_path, monkeypatch):
    import json
    from streamlit.testing.v1 import AppTest
    path = tmp_path / 'factor.json'
    path.write_text(json.dumps(sample()), encoding='utf8')
    monkeypatch.setenv('FACTOR_DRILL_FIXTURE', str(path))
    app = AppTest.from_string('''
import json,os
from pathlib import Path
from portfolio_app.factor_drilldown_view import render_ic_drilldown
render_ic_drilldown(json.loads(Path(os.environ['FACTOR_DRILL_FIXTURE']).read_text(encoding='utf8')))
''').run()
    assert not app.exception
    assert app.metric[0].value == '—'
    app.selectbox(key='factor_ic_date_known').select('2025-01-02').run()
    assert not app.exception
    assert app.metric[0].value == '0.5000'
    app.segmented_control(key='factor_period_display').set_value('表格').run()
    assert not app.exception
    assert any('valid_sessions' in table.value.columns for table in app.dataframe)
