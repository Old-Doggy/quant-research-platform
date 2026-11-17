import numpy as np
import pandas as pd
import pytest

from portfolio_app.research_display import page_frame, envelope_sample, check_research_size


def test_pagination_all_rows_once_and_invalid_page_rejected():
    frame = pd.DataFrame({'id': range(1003)})
    restored = pd.concat([page_frame(frame, page=p, page_size=100) for p in range(11)])
    pd.testing.assert_frame_equal(frame, restored)
    with pytest.raises(ValueError):
        page_frame(frame, page=-1, page_size=100)


def test_display_sampling_preserves_extremes_gaps_endpoints_and_source():
    frame = pd.DataFrame({'date': range(10000), 'ic': np.zeros(10000)})
    frame.loc[405, 'ic'] = 99
    frame.loc[406, 'ic'] = -88
    frame.loc[700, 'ic'] = np.nan
    original = frame.copy(deep=True)
    shown = envelope_sample(frame, value='ic', max_points=200)
    assert len(shown) <= 200
    assert {0, 9999, 405, 406, 700} <= set(shown.index)
    pd.testing.assert_frame_equal(frame, original)


def test_memory_budget_explains_rejection_before_research_allocation():
    with pytest.raises(ValueError, match='缩小'):
        check_research_size(pd.DataFrame({'x': range(10)}), max_rows=5)
    check_research_size(pd.DataFrame({'x': [1]}))


def test_multi_series_sampling_preserves_independent_extremes_and_gaps():
    frame=pd.DataFrame({'unit_nav':np.ones(10000),'drawdown':np.zeros(10000)})
    frame.loc[401,'unit_nav']=1.8
    frame.loc[410,'drawdown']=-.6
    frame.loc[500,'unit_nav']=np.nan
    frame.loc[600,'drawdown']=np.nan
    original=frame.copy(deep=True)
    single=envelope_sample(frame,value='unit_nav',max_points=200)
    assert 410 not in single.index  # A NAV-only envelope can hide the drawdown low.
    shown=envelope_sample(frame,value=['unit_nav','drawdown'],max_points=200)
    assert len(shown)<=200
    assert {0,9999,401,410,500,600}<=set(shown.index)
    pd.testing.assert_frame_equal(frame,original)


def test_multi_series_sampling_rejects_insufficient_budget():
    with pytest.raises(ValueError,match='budget'):
        envelope_sample(pd.DataFrame({'a':[1]*20,'b':[2]*20}),value=['a','b'],max_points=5)
