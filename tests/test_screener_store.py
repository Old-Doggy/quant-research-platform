import json

import pytest

from test_screener import config,frame
from test_market_overview import snapshot


def test_saved_screen_restores_exact_version_conditions_and_members(tmp_path):
    from portfolio_app.screener_store import ScreenerStore
    from portfolio_app.screener import screen_daily
    store=ScreenerStore(tmp_path)
    result=screen_daily(frame(),manifest=snapshot(),config=config())
    saved=store.save('价量观察',result,x='amount',y='price_change')
    assert store.save('价量观察',result,x='amount',y='price_change')==saved
    reopened=ScreenerStore(tmp_path)
    assert reopened.records()==[dict(identifier=saved,name='价量观察',session='2025-01-03',
        snapshot_id='fixture-version',count=3)]
    restored=reopened.open(saved)
    assert restored['config']==config()
    assert restored['symbols']==['AAA','BBB','CCC']
    assert restored['view']==dict(x='amount',y='price_change')
    verified=reopened.reproduce(saved,frame(),manifest=snapshot())
    assert verified['screen_id']==result['screen_id']
    changed=frame()
    changed.loc[0,'close']=12.
    with pytest.raises(ValueError,match='不一致'):
        reopened.reproduce(saved,changed,manifest=snapshot())


def test_corrupt_saved_screen_and_wrong_source_never_silently_restore(tmp_path):
    from portfolio_app.screener_store import ScreenerStore
    from portfolio_app.screener import screen_daily
    store=ScreenerStore(tmp_path)
    result=screen_daily(frame(),manifest=snapshot(),config=config())
    identifier=store.save('screen',result,x='amount',y='close')
    with pytest.raises(ValueError):store.open('../outside')
    payload=json.loads((store.directory/(identifier+'.json')).read_text('utf8'))
    payload['symbols']=[]
    (store.directory/(identifier+'.json')).write_text(json.dumps(payload),encoding='utf8')
    with pytest.raises(ValueError,match='校验'):store.open(identifier)
    with pytest.raises(ValueError):store.save('screen',result,x='roe',y='close')
