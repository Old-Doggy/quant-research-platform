import pandas as pd
import pytest


def inputs():
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    from portfolio_app.offline_execution import ExecutionSpec
    from portfolio_app.temporal_contracts import build_session_calendar
    dates = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(dates), symbol='AAA',
        open=10., high=10., low=10., close=10., volume=10000, tradability='tradable'))
    recipe = PortfolioRecipe.from_dict(dict(recipe_id='sessions', target_weights={'AAA': 1.}, cash_weight=0., lot_size=1))
    spec = ExecutionSpec('next', 'close', 'next_close', 0, 0, 'us_stock')
    calendar = build_session_calendar(dates, calendar_id='test', market='US', timezone='America/New_York')
    schedule = {d: {'AAA': 1. if i == 0 else 0.} for i, d in enumerate(dates)}
    return dates, frame, dict(recipe=recipe, spec=spec, strategy_key='trend', initial_cash=1000.,
        target_schedule=schedule, session_calendar=calendar)


def test_suspension_values_existing_shares_without_creating_trades():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    dates, frame, args = inputs()
    frame.loc[2, 'tradability'] = 'suspended'
    frame.loc[2, ['open', 'high', 'low', 'close']] = float('nan')
    result = run_portfolio_workspace({'AAA': frame}, **args)
    assert result.accounting.ledger.trade_date.tolist() == dates
    assert result.accounting.ledger.nav.tolist() == [1000.] * 4
    assert all(f['fill_date'] != dates[2] for f in result.fills)
    assert any(o['reason_code'] == 'suspended' for o in result.orders)
    row = result.positions.loc[result.positions.trade_date.eq(dates[2])].iloc[0]
    assert row.close == 10.
    assert row.valuation_status == 'carried_suspension'
    assert result.inputs['market_sessions']['status'] == 'explicit'
    assert pd.isna(frame.loc[2, 'close'])


def test_missing_data_and_zero_volume_do_not_become_suspension_or_fills():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    dates, frame, args = inputs()
    with pytest.raises(ValueError, match='缺失|缺口'):
        run_portfolio_workspace({'AAA': frame.drop(index=2)}, **args)
    frame.loc[1, 'volume'] = 0
    result = run_portfolio_workspace({'AAA': frame}, **args)
    assert not result.fills
    assert result.orders[0]['reason_code'] == 'capacity_exhausted'
    assert result.orders[0]['effective_date'] == dates[1]


def test_unknown_status_is_visible_and_not_treated_as_tradable():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    _, frame, args = inputs()
    frame.loc[1, 'tradability'] = 'unknown'
    result = run_portfolio_workspace({'AAA': frame}, **args)
    assert not result.fills
    assert result.orders[0]['reason_code'] == 'unknown_tradability'


@pytest.mark.parametrize('status,side', [('limit_up', 'BUY'), ('limit_down', 'SELL')])
def test_limit_state_blocks_the_relevant_side(status, side):
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    dates, frame, args = inputs()
    frame.loc[1 if side == 'BUY' else 2, 'tradability'] = status
    result = run_portfolio_workspace({'AAA': frame}, **args)
    assert any(o['reason_code'] == ('limit_up_buy_blocked' if side == 'BUY' else 'limit_down_sell_blocked')
               for o in result.orders)
    assert all(f['fill_date'] != dates[1 if side == 'BUY' else 2] or f['side'] != side for f in result.fills)


def test_no_first_valuation_is_invented_for_a_suspended_start():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    _, frame, args = inputs()
    frame.loc[0, 'tradability'] = 'suspended'
    frame.loc[0, ['open', 'high', 'low', 'close']] = float('nan')
    with pytest.raises(ValueError, match='估值|前收'):
        run_portfolio_workspace({'AAA': frame}, **args)


def test_common_date_filter_cannot_hide_a_missing_portfolio_session():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    _, frame, args = inputs()
    frame.attrs['session_calendar'] = args['session_calendar']
    # The same metadata is retained on a subset, as in the research UI.
    with pytest.raises(ValueError, match='缺失|缺口'):
        run_portfolio_workspace({'AAA': frame.drop(index=1)}, **{k: v for k, v in args.items() if k != 'session_calendar'})


def test_missing_price_fields_use_a_data_error_instead_of_attribute_error():
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    _, frame, args = inputs()
    with pytest.raises(ValueError, match='字段'):
        run_portfolio_workspace({'AAA': frame.drop(columns='close')}, **args)


def test_ui_alignment_retains_synthetic_demo_but_blocks_real_and_calendar_gaps():
    from portfolio_app.portfolio_workspace_view import align_portfolio_observations
    _, frame, args = inputs()
    frames = {'AAA': frame, 'BBB': frame.iloc[1:].assign(symbol='BBB')}
    aligned, dates, excluded = align_portfolio_observations(frames, {'source_kind': 'synthetic'})
    assert len(dates) == 3 and excluded == 1
    assert all(len(f) == 3 for f in aligned.values())
    with pytest.raises(ValueError, match='交易日不齐'):
        align_portfolio_observations(frames, {'source_kind': 'local_market'})
    frames['AAA'].attrs['session_calendar'] = args['session_calendar']
    with pytest.raises(ValueError, match='交易日不齐'):
        align_portfolio_observations(frames, {'source_kind': 'synthetic'})
