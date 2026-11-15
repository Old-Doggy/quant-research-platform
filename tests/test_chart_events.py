def event(**changes):
    return dict(version=1, source='kline', chart_id='chart-a', symbol='AAA',
                sequence=1, date='2025-01-02', kind='date', **changes)


def test_selection_is_bound_to_chart_symbol_and_actual_dates():
    from portfolio_app.chart_events import accept_chart_event
    valid = event()
    assert accept_chart_event(valid, chart_id='chart-a', symbol='AAA', dates={'2025-01-02'}) == valid
    for update in [dict(chart_id='chart-b'), dict(symbol='BBB'), dict(date='2025-01-03'),
                   dict(version=2), dict(sequence=True), dict(kind='arbitrary')]:
        assert accept_chart_event({**valid, **update}, chart_id='chart-a', symbol='AAA', dates={'2025-01-02'}) is None


def test_selection_rejects_duplicate_and_stale_sequences():
    from portfolio_app.chart_events import accept_chart_event
    for seq in [1, 2]:
        assert accept_chart_event({**event(), 'sequence': seq}, chart_id='chart-a', symbol='AAA',
                                  dates={'2025-01-02'}, last_sequence=2) is None
    assert accept_chart_event({**event(), 'sequence': 3}, chart_id='chart-a', symbol='AAA',
                              dates={'2025-01-02'}, last_sequence=2)
    assert accept_chart_event(None, chart_id='chart-a', symbol='AAA', dates=set()) is None


def test_chart_identity_changes_when_chart_data_changes():
    from portfolio_app.chart_events import chart_identity
    payload = {'symbol': 'AAA', 'bars': [{'time': '2025-01-02', 'close': 10}]}
    assert chart_identity(payload) == chart_identity(dict(payload))
    assert chart_identity(payload) != chart_identity({**payload, 'bars': [{'time': '2025-01-02', 'close': 11}]})


def test_plotly_selection_uses_same_validation_boundary():
    from portfolio_app.chart_events import plotly_date_event, accept_chart_event
    raw = {'selection': {'points': [{'x': '2025-01-02T00:00:00'}]}}
    msg = plotly_date_event(raw, chart_id='run-a', symbol='AAA', sequence=1)
    assert msg['source'] == 'plotly'
    assert accept_chart_event(msg, chart_id='run-a', symbol='AAA', dates={'2025-01-02'})
    assert plotly_date_event({'selection': {'points': []}}, chart_id='run-a', symbol='AAA', sequence=1) is None
