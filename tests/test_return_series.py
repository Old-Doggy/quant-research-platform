import pandas as pd
import pytest


def bars():
    return pd.DataFrame(dict(trade_date=pd.to_datetime(['2025-01-02', '2025-01-03', '2025-01-06']),
        symbol='AAA', open=[10., 9.5, 9.5], high=[10., 9.5, 9.5], low=[10., 9.5, 9.5],
        close=[10., 9.5, 9.5], cash_dividend_per_share=[0., .5, 0.], share_multiplier=[1., 1., 1.]))


def test_dividend_and_split_total_returns_follow_independent_formulas():
    from portfolio_app.return_series import build_return_series
    frame = bars()
    result = build_return_series(frame, definition='total_return_v1', action_coverage='complete')
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == pytest.approx((9.5 + .5) / 10 - 1)
    frame.loc[1:, ['open', 'high', 'low', 'close']] = 5.
    frame['cash_dividend_per_share'] = 0.
    frame.loc[1, 'share_multiplier'] = 2.
    assert build_return_series(frame, definition='total_return_v1', action_coverage='complete').iloc[1] == 0.


def test_total_return_requires_event_coverage_and_does_not_double_count_adjusted_price():
    from portfolio_app.return_series import build_return_series, ReturnContractError
    with pytest.raises(ReturnContractError, match='公司行为覆盖'):
        build_return_series(bars(), definition='total_return_v1')
    with pytest.raises(ReturnContractError, match='原始价格'):
        build_return_series(bars(), definition='total_return_v1', action_coverage='complete', price_basis='qfq')


def test_price_return_is_explicit_and_keeps_symbol_boundaries_and_missing_values():
    from portfolio_app.return_series import build_return_series
    frame = pd.concat([bars(), bars().assign(symbol='BBB')], ignore_index=True)
    result = build_return_series(frame)
    assert result.isna().sum() == 2
    assert result.iloc[1] == pytest.approx(-.05)
    assert result.attrs['return_contract']['definition'] == 'price_return_v1'
    frame.loc[1, 'close'] = float('nan')
    assert build_return_series(frame).iloc[1:3].isna().all()


def test_cash_account_rejects_adjusted_trade_prices():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    from portfolio_app.offline_execution import ExecutionSpec
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    frame = bars()
    frame.attrs['research_dataset'] = dict(price_basis='qfq')
    with pytest.raises(ValueError, match='原始价格'):
        run_portfolio_workspace({'AAA': frame}, strategy_key='trend',
            recipe=PortfolioRecipe.from_dict(dict(recipe_id='test', target_weights={'AAA': 1.}, cash_weight=0., lot_size=1)),
            spec=ExecutionSpec('close', 'close', 'next_close', 0, 0, 'us_stock'))


def test_legacy_proxy_cannot_present_known_ex_dividend_gap_as_investment_loss():
    from portfolio_app.research import run_single_stock_research
    with pytest.raises(ValueError, match='公司行为.*资金账本'):
        run_single_stock_research(bars(), strategy_key='trend')


def test_display_payload_carries_price_role_without_modifying_input():
    from portfolio_app.chart_payload import build_ohlcv_payload
    frame = bars()
    original = frame.copy(deep=True)
    raw = build_ohlcv_payload(frame, symbol='AAA', data_context={'price_mode': 'raw'})
    adjusted = build_ohlcv_payload(frame, symbol='AAA', data_context={'price_mode': 'qfq'})
    assert raw['data_context']['price_role'] == adjusted['data_context']['price_role'] == 'display_only'
    pd.testing.assert_frame_equal(original, frame)
