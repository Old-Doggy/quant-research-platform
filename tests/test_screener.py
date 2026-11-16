import pandas as pd
import pytest

from test_market_overview import snapshot, daily_frame


def frame():
    return daily_frame(dict(symbol=['AAA','BBB','CCC'],trade_date=pd.to_datetime(['2025-01-03']*3),
        close=[11.,9.,10.],pre_close=[10.,10.,None],amount=[100.,200.,None],volume=[10.,20.,30.]))


def config(**changes):
    return {**dict(schema='daily-screener.v1',session='2025-01-03',snapshot_id='fixture-version',
        universe_policy='snapshot_listed_on_session',conditions=[]),**changes}


def test_filters_are_ordered_missing_explicit_and_never_use_future_rows():
    from portfolio_app.screener import screen_daily
    options = config(conditions=[dict(field='amount',op='ge',value=100.,missing='exclude'),
        dict(field='price_change',op='ge',value=0.,missing='exclude')])
    data = frame()
    future = data.copy()
    future['trade_date'] = pd.Timestamp('2025-01-06')
    future['amount'] = 10000.
    data = pd.concat([data,future],ignore_index=True)
    result = screen_daily(data,manifest=snapshot(),config=options)
    assert result['symbols']==['AAA']
    assert [(s['before'],s['after'],s['missing']) for s in result['steps']]==[(3,2,1),(2,1,0)]
    assert result['details'].symbol.tolist()==['AAA']
    assert result['details'].price_change.iloc[0]==pytest.approx(.1)
    assert result['research_ready'] is False
    assert result['session']=='2025-01-03'


def test_keep_missing_is_saved_rule_but_cannot_make_missing_values_look_valid():
    from portfolio_app.screener import screen_daily
    options=config(conditions=[dict(field='amount',op='ge',value=150.,missing='keep')])
    result=screen_daily(frame(),manifest=snapshot(),config=options)
    assert result['symbols']==['BBB','CCC']
    assert result['steps'][0]['missing']==1
    assert pd.isna(result['details'].iloc[-1].amount)
    assert screen_daily(frame(),manifest=snapshot(),config=config())['symbols']==['AAA','BBB','CCC']


@pytest.mark.parametrize('condition',[
    dict(field='roe',op='ge',value=.1,missing='exclude'),
    dict(field='close',op='eval',value=10.,missing='exclude'),
    dict(field='amount',op='ge',value=True,missing='exclude'),
    dict(field='close',op='ge',value=float('inf'),missing='exclude'),
    dict(field='volume',op='ge',value=1.,missing='zero'),
    dict(field='close',op='ge',value=10.,missing='exclude',extra='x'),
])
def test_unknown_or_unsafe_conditions_do_not_silently_fall_back(condition):
    from portfolio_app.screener import screen_daily
    with pytest.raises(ValueError):
        screen_daily(frame(),manifest=snapshot(),config=config(conditions=[condition]))


def test_exact_snapshot_and_date_scope_are_mandatory():
    from portfolio_app.screener import screen_daily
    for change in (dict(snapshot_id='latest'),dict(session='2025-01-04'),
                   dict(universe_policy='current_survivors'),dict(schema='unknown')):
        with pytest.raises(ValueError):
            screen_daily(frame(),manifest=snapshot(),config=config(**change))
