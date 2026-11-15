import pytest


def record(**changes):
    return {**dict(instrument_id='CN:SSE:600000', symbol='600000.SH', name='测试银行', market='SSE',
        asset_type='cn_stock', subtype='main_a', listed_on='1999-11-10', delisted_on=None,
        provider='tushare', provider_code='600000.SH'), **changes}


def test_master_retains_missing_and_delisted_symbols_and_reports_changes():
    from portfolio_app.instrument_master import InstrumentMaster
    master = InstrumentMaster()
    first = master.update([record(), record(instrument_id='CN:SSE:600001', symbol='600001.SH',
        provider_code='600001.SH', name='旧公司')], observed_on='2025-01-02', source='synthetic', batch_id='one')
    assert len(first['added']) == 2
    second = master.update([record(name='新名称')], observed_on='2025-01-03', source='synthetic', batch_id='two')
    assert second['renamed'] == ['CN:SSE:600000']
    assert second['missing'] == ['CN:SSE:600001']
    assert len(master.records) == 2
    master.update([record(instrument_id='CN:SSE:600001', symbol='600001.SH', provider_code='600001.SH',
        name='旧公司', delisted_on='2025-01-06')], observed_on='2025-01-07', source='synthetic', batch_id='three')
    assert len(master.listed_at('2025-01-03')) == 2
    assert len(master.listed_at('2025-01-07')) == 1
    assert master.resolve_provider('tushare', '600001.SH').delisted_on == '2025-01-06'
    assert master.changes[0]['batch_id'] == 'one'


def test_code_conflict_does_not_partially_update_or_drop_existing_records():
    from portfolio_app.instrument_master import InstrumentMaster
    master = InstrumentMaster()
    master.update([record()], observed_on='2025-01-02', source='synthetic', batch_id='one')
    before = master.to_dict()
    with pytest.raises(ValueError, match='冲突'):
        master.update([record(name='误改'), record(instrument_id='OTHER', name='重复', symbol='600002.SH')],
            observed_on='2025-01-03', source='synthetic', batch_id='conflict')
    assert master.to_dict() == before


def test_names_are_observations_and_cannot_claim_historical_pit():
    from portfolio_app.instrument_master import InstrumentMaster
    master = InstrumentMaster()
    master.update([record()], observed_on='2025-01-02', source='synthetic', batch_id='one')
    master.update([record(name='改名')], observed_on='2025-01-03', source='synthetic', batch_id='two')
    assert master.name_as_observed('CN:SSE:600000', '2025-01-02') == '测试银行'
    assert master.name_as_observed('CN:SSE:600000', '2020-01-02') is None
    assert master.name_as_observed('CN:SSE:600000', '2025-01-03') == '改名'


def test_master_atomic_round_trip_and_checksum(tmp_path):
    from portfolio_app.instrument_master import InstrumentMaster
    master = InstrumentMaster()
    master.update([record()], observed_on='2025-01-02', source='synthetic', batch_id='one')
    path = tmp_path / 'master.json'
    master.save(path)
    assert InstrumentMaster.load(path).to_dict() == master.to_dict()
    path.write_text(path.read_text(encoding='utf8').replace('600000.SH', '600009.SH'), encoding='utf8')
    with pytest.raises(ValueError, match='校验'):
        InstrumentMaster.load(path)


def test_returned_change_records_cannot_modify_master_history():
    from portfolio_app.instrument_master import InstrumentMaster
    master = InstrumentMaster()
    change = master.update([record()], observed_on='2025-01-02', source='synthetic', batch_id='one')
    change['observations'][0]['name'] = 'tampered'
    snapshot = master.to_dict()
    snapshot['changes'][0]['observations'][0]['name'] = 'also tampered'
    assert master.name_as_observed('CN:SSE:600000', '2025-01-02') == '测试银行'
