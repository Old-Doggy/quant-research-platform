import numpy as np
import pandas as pd
import pytest


def sample():
    return pd.DataFrame(dict(symbol=list('ABCD')*3,trade_date=pd.to_datetime(
        ['2025-01-02']*4+['2025-01-03']*4+['2025-01-06']*4),
        first=[1.,2.,3.,4.]*3,second=[4.,3.,2.,1.,1.,2.,3.,4.,1.,1.,1.,1.],
        forward_label=[.1,.2,.3,.4,.1,.2,.3,.4,.4,.3,.2,.1]))


def test_cross_section_is_daily_not_pooled_and_keeps_constant_missing():
    from portfolio_app.factor_comparison import compare_factor_values,comparison_sample
    result=compare_factor_values(sample(),factors=['first','second'],min_assets=3,min_ic_dates=3)
    matrix=result['cross_section'].iloc[0]
    assert matrix['correlation']==pytest.approx(0.)
    assert matrix.valid_sessions==2 and matrix.common_n==12
    daily=result['daily']
    assert daily.correlation.iloc[:2].tolist()==pytest.approx([-1.,1.])
    assert pd.isna(daily.correlation.iloc[-1]) and daily.status.iloc[-1]=='constant_factor'
    scatter=comparison_sample(result,left='first',right='second',session='2025-01-03')
    assert scatter.symbol.tolist()==list('ABCD')
    assert scatter.left_value.tolist()==[1.,2.,3.,4.]
    assert result['ic_correlation'].iloc[0].status=='insufficient_observations'


def test_ic_sequence_correlation_uses_only_common_dates():
    from portfolio_app.factor_comparison import compare_factor_values
    data=sample()
    data.loc[data.trade_date.eq('2025-01-06'),'second']=[1.,2.,3.,4.]
    result=compare_factor_values(data,factors=['first','second'],min_assets=3,min_ic_dates=3)
    # First ICs [1,1,-1]; second [-1,1,-1], rank corr = 0.5.
    assert result['ic_correlation'].iloc[0].correlation==pytest.approx(.5)
    assert result['ic_correlation'].iloc[0].common_n==3


def test_real_factors_recomputed_and_past_outputs_ignore_future_input():
    from portfolio_app.factor_comparison import research_factor_comparison
    from test_factor_compute import make_bars
    data=pd.concat([make_bars().assign(symbol=s,close=make_bars().close+i*np.sin(np.arange(80)))
        for i,s in enumerate('ABCD')],ignore_index=True)
    selected=['basic.return_5d','basic.ma_deviation_20d']
    result=research_factor_comparison(data,factor_ids=selected,horizon=5,
        start='2026-02-02',end='2026-03-02',min_assets=3)
    changed=data.copy()
    changed.loc[changed.trade_date.gt('2026-03-02'),'close']=10000.
    other=research_factor_comparison(changed,factor_ids=selected,horizon=5,
        start='2026-02-02',end='2026-03-02',min_assets=3)
    pd.testing.assert_frame_equal(result['values'],other['values'])
    assert result['values']['forward_label'].iloc[-1] is np.nan or pd.isna(result['values']['forward_label'].iloc[-1])
    assert result['factor_ids']==selected


@pytest.mark.parametrize('change',[dict(min_assets=True),dict(min_assets=1),
    dict(factors=['first','first']),dict(factors=['first','missing'])])
def test_invalid_comparison_rejected(change):
    from portfolio_app.factor_comparison import compare_factor_values
    with pytest.raises(ValueError):
        compare_factor_values(sample(),**{**dict(factors=['first','second'],min_assets=3),**change})


def test_duplicate_keys_and_non_numeric_not_accepted():
    from portfolio_app.factor_comparison import compare_factor_values
    bad=sample().astype({'first':object})
    bad.loc[0,'first']='bad'
    for data in [bad,pd.concat([sample(),sample().iloc[:1]])]:
        with pytest.raises(ValueError):
            compare_factor_values(data,factors=['first','second'],min_assets=3)


def test_saved_comparison_replays_all_tables_and_refuses_changed_cell(tmp_path):
    import copy
    from portfolio_app.factor_comparison import research_factor_comparison
    from portfolio_app.result_replay import comparison_replay_inputs,replay_saved
    from portfolio_app.result_store import ResultStore
    from test_result_replay import save
    from test_factor_compute import make_bars
    frame=pd.concat([make_bars().assign(symbol=s) for s in 'ABCD'],ignore_index=True)
    config=dict(factor_ids=['basic.return_5d','basic.reversal_5d'],horizon=5,
        start='2026-01-02',end='2026-04-23',min_assets=3)
    value=dict(comparison=research_factor_comparison(frame,**config),
        replay=comparison_replay_inputs(frame,config=config))
    store=ResultStore(tmp_path)
    save(store,value)
    assert replay_saved(store,'replay')['kind']=='factor_comparison'
    bad=copy.deepcopy(value)
    bad['comparison']['values'].loc[40,'return_5d']+=1.
    save(store,bad,'changed')
    with pytest.raises(ValueError,match='不一致'):
        replay_saved(store,'changed')
