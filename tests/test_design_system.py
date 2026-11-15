"""The same design contract must reach the application and embedded charts."""
import pandas as pd

from portfolio_app.design_tokens import (
    COLOR_TOKENS, FONT_SIZE_TOKENS, RADIUS_TOKENS, validate_design_tokens,
)


def test_terminal_contract_is_readable_and_consistent():
    assert validate_design_tokens() == []
    assert COLOR_TOKENS['primary'] == '#2864D7'
    assert FONT_SIZE_TOKENS['body'] >= 16
    assert FONT_SIZE_TOKENS['table'] >= 14
    assert FONT_SIZE_TOKENS['chart'] >= 14
    assert RADIUS_TOKENS['control'] == 8
    assert RADIUS_TOKENS['chart'] == 12


def test_theme_variables_come_from_contract():
    from portfolio_app.design_tokens import css_variables
    css = css_variables()
    assert f'--q-primary:{COLOR_TOKENS["primary"]}' in css
    assert f'--q-font-body:{FONT_SIZE_TOKENS["body"]}px' in css
    assert f'--q-radius-chart:{RADIUS_TOKENS["chart"]}px' in css
    assert validate_design_tokens({'radius': {'control': 200}})
    assert validate_design_tokens({'muted_text': '#FFFFFF'})


def test_performance_visuals_keep_input_values_and_semantic_series():
    from portfolio_app.research_charts import build_performance_chart
    frame = pd.DataFrame({'trade_date': pd.date_range('2025-01-01', periods=3),
                          'nav': [1., 1.02, 1.01], 'bench': [1., .99, 1.],
                          'drawdown': [0., 0., -.0098]})
    original = frame.copy(deep=True)
    fig = build_performance_chart(frame, benchmark='bench')
    pd.testing.assert_frame_equal(frame, original)
    assert list(fig.data[0].y) == list(frame.nav)
    assert fig.data[0].line.color == COLOR_TOKENS['primary']
    assert fig.data[1].line.color == COLOR_TOKENS['benchmark']
    assert fig.data[1].line.dash == 'dash'
    assert fig.layout.font.size == FONT_SIZE_TOKENS['chart']


def test_embedded_chart_receives_same_theme():
    from portfolio_app.chart_bridge import chart_bridge_html
    html = chart_bridge_html({'period': '1d', 'bars': []})
    assert '--q-primary:#2864D7' in html
    assert '--q-font-chart:14px' in html
    assert 'getComputedStyle(document.documentElement)' in html
