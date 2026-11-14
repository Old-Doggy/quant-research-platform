"""Independent behavioral checks for confirmed R1.13 findings."""
import numpy as np
import pandas as pd
import pytest

from portfolio_app.data import normalise_market_frame, build_data_quality_report
from portfolio_app.research import run_single_stock_research, run_portfolio_research
from portfolio_app.backtest import run_equal_weight_portfolio


def bars(symbol='AAA', rows=80):
    close = np.linspace(10, 20, rows)
    return normalise_market_frame(pd.DataFrame(dict(
        trade_date=pd.bdate_range('2025-01-02', periods=rows), symbol=symbol,
        open=close, high=close+1, low=close-1, close=close, vol=1000)))


@pytest.mark.parametrize('column,value', [('high', 1), ('open', np.inf), ('low', -1)])
def test_single_research_blocks_bad_prices_before_backtest(column, value):
    frame = bars()
    frame.loc[30, column] = value
    with pytest.raises(ValueError, match='quality'):
        run_single_stock_research(frame, strategy_key='trend')


def test_weighted_research_rejects_unmodeled_missing_sessions():
    with pytest.raises(ValueError, match='calendar'):
        run_portfolio_research({'AAA': bars(), 'BBB': bars('BBB').drop(index=40)},
            strategy_key='trend', target_weights={'AAA': .5, 'BBB': .5})


@pytest.mark.parametrize('value', [np.nan, np.inf])
def test_weighted_research_rejects_nonfinite_allocations(value):
    with pytest.raises(ValueError, match='finite'):
        run_portfolio_research({'AAA': bars()}, strategy_key='trend',
            target_weights={'AAA': value})


def test_equal_weight_cash_return_and_cost_reconcile(monkeypatch):
    import portfolio_app.strategies as strategies
    monkeypatch.setattr(strategies, 'generate_signal', lambda frame, *a, **k: frame)
    active = bars(rows=3).assign(signal=[1., 1., 0.], **{'return': [0., .1, .1]})
    idle = bars('BBB', rows=3).assign(signal=0., **{'return': [0., 0., 0.]})
    result, _ = run_equal_weight_portfolio({'AAA': active, 'BBB': idle}, 'trend', transaction_cost=.002)
    assert result.loc[1, 'gross_exposure'] == .5
    assert result.loc[1, 'cash_weight'] == .5
    assert result.loc[1, 'daily_return'] == pytest.approx(.05-.001)
    contribution = result.attrs['leg_contributions']
    assert np.allclose(contribution[['AAA', 'BBB']].sum(axis=1), result.daily_return)


def test_normalizer_retains_removed_rows_in_quality_audit():
    source = bars()
    frame = normalise_market_frame(pd.concat([source, source.iloc[[0]]], ignore_index=True))
    assert len(frame) == len(source)
    report = build_data_quality_report(frame)
    assert report['normalization_removed_duplicate_rows'] == 1
    assert report['status'] == '需复核'


def test_quality_reports_invalid_dates_without_crashing():
    frame = bars().astype({'trade_date': 'object'})
    frame.loc[0, 'trade_date'] = 'not-a-date'
    assert build_data_quality_report(frame)['missing_required_value_rows'] == 1
