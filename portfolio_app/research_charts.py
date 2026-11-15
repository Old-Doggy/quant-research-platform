"""Readable interactive views of existing research results; no return calculations."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .design_tokens import CHART_PALETTE, COLOR_TOKENS, FONT_FAMILY, FONT_SIZE_TOKENS

PALETTE = CHART_PALETTE
FONT = FONT_FAMILY
CHART_CONFIG = {
    'displaylogo': False, 'scrollZoom': False, 'responsive': True,
    'displayModeBar': 'hover',
    'modeBarButtonsToRemove': ['lasso2d', 'select2d', 'autoScale2d'],
    'toImageButtonOptions': {'format': 'png', 'scale': 2},
}


def style_chart(figure: go.Figure, *, title: str = '', height: int = 360,
                revision: str = 'research-chart') -> go.Figure:
    """One font, interaction vocabulary and palette for analytical charts."""
    figure.update_layout(
        template='plotly_white', height=height,
        title=dict(text=title, font=dict(size=FONT_SIZE_TOKENS['section_title'], color=COLOR_TOKENS['text']), x=.015, xanchor='left'),
        font=dict(family=FONT, size=FONT_SIZE_TOKENS['chart'], color=COLOR_TOKENS['text']),
        paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF', colorway=list(PALETTE),
        margin=dict(l=18, r=48, t=100 if title else 48, b=42),
        hovermode='x unified', dragmode='zoom', uirevision=revision,
        hoverlabel=dict(font=dict(family=FONT, size=14), bgcolor='#FFFFFF'),
        legend=dict(orientation='h', y=1.04, x=0, yanchor='bottom',
                    font=dict(size=14), itemclick='toggle', itemdoubleclick='toggleothers'),
        modebar=dict(orientation='h', bgcolor='rgba(255,255,255,.9)', color='#60738E', activecolor=PALETTE[0]),
    )
    figure.update_xaxes(showgrid=False, zeroline=False, automargin=True, tickfont=dict(size=14),
                        showspikes=True, spikemode='across', spikesnap='cursor',
                        spikecolor='#91A1B9', spikethickness=1, spikedash='dot')
    figure.update_yaxes(gridcolor='#E4EAF2', zerolinecolor='#CCD6E4', automargin=True,
                        tickfont=dict(size=14), fixedrange=False, nticks=5)
    # The shared hover heading supplies the date once for every visible series.
    for trace in figure.data:
        if trace.type == 'scatter' and trace.hovertemplate:
            trace.hovertemplate = trace.hovertemplate.replace('%{x|%Y-%m-%d}<br>', '')
    return figure


def build_performance_chart(frame: pd.DataFrame, *, date: str = 'trade_date',
                            nav: str = 'nav', benchmark: str | None = None,
                            drawdown: str = 'drawdown', label: str = '策略净值',
                            title: str = '净值与回撤', revision: str = 'performance') -> go.Figure:
    required = [date, nav, drawdown] + ([benchmark] if benchmark else [])
    missing = [name for name in required if name not in frame]
    if missing:
        raise ValueError('Missing chart columns: ' + ', '.join(missing))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.08,
                        row_heights=[.73, .27])
    fig.add_trace(go.Scatter(x=frame[date], y=frame[nav], name=label, mode='lines',
        line=dict(color=COLOR_TOKENS['primary'], width=2.2), connectgaps=False,
        hovertemplate='%{x|%Y-%m-%d}<br>'+label+' %{y:.4f}<extra></extra>'), row=1, col=1)
    if benchmark:
        fig.add_trace(go.Scatter(x=frame[date], y=frame[benchmark], name='同标的买入持有', mode='lines',
            line=dict(color=COLOR_TOKENS['benchmark'], width=1.5, dash='dash'), connectgaps=False,
            hovertemplate='%{x|%Y-%m-%d}<br>买入持有 %{y:.4f}<extra></extra>'), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame[date], y=frame[drawdown], name='回撤', mode='lines',
        line=dict(color=COLOR_TOKENS['benchmark'], width=1.2), fill='tozeroy', fillcolor='rgba(104,120,141,.10)',
        connectgaps=False, hovertemplate='%{x|%Y-%m-%d}<br>回撤 %{y:.2%}<extra></extra>'), row=2, col=1)
    style_chart(fig, title='', height=480, revision=revision)
    fig.update_layout(margin=dict(l=18, r=70, t=62, b=38), hovermode='x unified',
        title=dict(text=''), legend=dict(y=1.04, yanchor='bottom', x=0),
        hoverdistance=30)
    # hoversubplots is supported by the project's Plotly >=5.24 requirement.
    fig.update_layout(hoversubplots='axis')
    # One common x axis lets hover and zoom cover both panels.
    fig.data[-1].update(xaxis='x')
    fig.update_yaxes(title_text='净值', tickformat='.2f', side='right', nticks=5, row=1, col=1)
    fig.update_yaxes(title_text='回撤', tickformat='.1%', side='right', nticks=3,
        rangemode='tozero', zeroline=True, row=2, col=1)
    fig.update_xaxes(matches=None, anchor='y2', showticklabels=True,
        tickformat='%Y-%m', hoverformat='%Y-%m-%d', nticks=6, tickangle=0, ticklabelstep=2,
        unifiedhovertitle=dict(text='%{x|%Y-%m-%d}'), row=1, col=1)
    fig.update_xaxes(matches='x', showticklabels=False, row=2, col=1)
    return fig


def build_turnover_chart(frame: pd.DataFrame, *, window: int = 20,
                         revision: str = 'turnover') -> go.Figure:
    """Daily membership exits are discrete observations, not a price path."""
    daily = pd.to_numeric(frame['turnover'], errors='coerce')
    fig = go.Figure(go.Scatter(x=frame.trade_date, y=daily, name='每日退出比例 · 点击查看',
        mode='markers', visible='legendonly' if daily.rolling(window, min_periods=window).mean().notna().any() else True,
        marker=dict(color='#9AACC5', size=4, opacity=.45),
        connectgaps=False,
        hovertemplate='当日退出 %{y:.0%}<extra></extra>'))
    fig.add_trace(go.Scatter(x=frame.trade_date, y=daily.rolling(window, min_periods=window).mean(),
        name=f'{window}日均值', mode='lines', line=dict(color=PALETTE[0], width=2.3),
        connectgaps=False, hovertemplate=f'{window}日均值 '+'%{y:.1%}<extra></extra>'))
    style_chart(fig, title='', height=250, revision=revision)
    fig.update_layout(margin=dict(l=18, r=64, t=48, b=38),
        legend=dict(y=1.02, yanchor='bottom', x=0))
    fig.update_yaxes(range=[0, 1.05], tickvals=[0, .5, 1], tickformat='.0%', side='right')
    fig.update_xaxes(tickformat='%Y-%m', tickangle=0, nticks=6,
        unifiedhovertitle=dict(text='%{x|%Y-%m-%d}'))
    return fig


def build_allocation_chart(positions: pd.DataFrame, *, cash: float, nav: float,
                           revision: str = 'allocation') -> go.Figure:
    """Show actual marked holdings and cash as shares of the same account NAV."""
    if nav <= 0:
        raise ValueError('allocation requires positive NAV')
    amounts = positions.groupby('symbol', sort=False)['market_value'].sum(min_count=1)
    amounts = pd.concat([amounts, pd.Series({'现金': cash})])
    fig = go.Figure(go.Bar(x=amounts / nav, y=amounts.index, orientation='h',
        customdata=amounts.tolist(),
        marker_color=[PALETTE[0]] * (len(amounts) - 1) + ['#94A6BF'],
        width=.42, text=[f'{v / nav:.1%}' for v in amounts], textposition='outside', cliponaxis=False,
        hovertemplate='%{y}<br>账户占比 %{x:.1%}<br>市值 %{customdata:,.2f}<extra></extra>'))
    style_chart(fig, title='持仓与现金', height=max(230, 100 + len(amounts)*32), revision=revision)
    fig.update_layout(showlegend=False, hovermode='closest', margin=dict(l=18, r=38, t=50, b=38))
    fig.update_xaxes(tickformat='.0%', range=[0, 1], showgrid=True, gridcolor='#E4EAF2')
    fig.update_yaxes(type='category', autorange='reversed', showgrid=False, dtick=1)
    return fig


def build_time_series_chart(frame: pd.DataFrame, series: dict[str, str], *,
                             date: str = 'trade_date', title: str = '',
                             unit: str = 'percent', height: int = 340,
                             revision: str = 'time-series') -> go.Figure:
    fig = go.Figure()
    fmt = '.2%' if unit == 'percent' else '.3f'
    for i, (column, label) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=frame[date], y=frame[column], name=label, mode='lines',
            connectgaps=False, line=dict(color=PALETTE[i % len(PALETTE)], width=2),
            hovertemplate='%{x|%Y-%m-%d}<br>'+label+' %{y:'+fmt+'}<extra></extra>'))
    style_chart(fig, title=title, height=height, revision=revision)
    fig.update_yaxes(tickformat='.0%' if unit == 'percent' else '.2f')
    fig.update_xaxes(tickformat='%Y-%m', hoverformat='%Y-%m-%d', nticks=6)
    return fig


def build_coverage_chart(frame: pd.DataFrame, *, max_symbols: int = 20) -> go.Figure:
    """Count observed unique dates, without guessing an exchange calendar."""
    observed = frame[['symbol', 'trade_date']].copy()
    observed['trade_date'] = pd.to_datetime(observed['trade_date'], errors='coerce').dt.normalize()
    observed = observed.dropna().drop_duplicates(['symbol', 'trade_date'])
    if observed.empty:
        return style_chart(go.Figure(), title='暂无有效日期可展示', height=300)
    symbols = sorted(observed.symbol.unique())[:max_symbols]
    months = pd.period_range(observed.trade_date.min(), observed.trade_date.max(), freq='M').astype(str)
    observed['month'] = observed.trade_date.dt.strftime('%Y-%m')
    counts = observed[observed.symbol.isin(symbols)].groupby(['symbol', 'month']).size().unstack(fill_value=0)
    counts = counts.reindex(index=symbols, columns=months, fill_value=0)
    fig = go.Figure(go.Heatmap(x=list(months), y=list(symbols), z=counts.to_numpy(),
        colorscale=[[0, '#EDF2FA'], [.4, '#9DB8E9'], [1, '#2864D7']], zmin=0,
        colorbar=dict(title='日期数', tickfont=dict(size=14), thickness=12),
        hovertemplate='标的 %{y}<br>月份 %{x}<br>已记录日期数 %{z}<extra></extra>',
        xgap=3, ygap=3))
    style_chart(fig, title='数据覆盖 · 每月已记录日期数',
        height=max(300, min(740, 155 + len(symbols) * 28)), revision='data-coverage')
    fig.update_layout(hovermode='closest', margin_b=55, showlegend=False)
    fig.update_xaxes(type='category', showspikes=False)
    fig.update_yaxes(type='category', autorange='reversed')
    return fig


def build_ic_chart(frame: pd.DataFrame, *, value: str = 'ic', window: int = 20,
                   revision: str = 'ic') -> go.Figure:
    """Show daily noise and an explicitly labelled full-window descriptive mean."""
    daily = pd.to_numeric(frame[value], errors='coerce')
    rolling = daily.rolling(window, min_periods=window).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame.trade_date, y=daily, name='每日 Rank IC · 点击查看',
        mode='markers', marker=dict(color='#9AACC5', size=4, opacity=.4),
        visible='legendonly' if rolling.notna().any() else True, connectgaps=False,
        hovertemplate='%{x|%Y-%m-%d}<br>每日 Rank IC %{y:.3f}<extra></extra>'))
    fig.add_trace(go.Scatter(x=frame.trade_date, y=rolling, name=f'{window}日均值',
        mode='lines', line=dict(color=PALETTE[0], width=2.4), connectgaps=False,
        hovertemplate=f'{window}日均值 '+'%{y:.3f}<extra></extra>'))
    style_chart(fig, title=f'Rank IC · {window}日趋势', height=330, revision=revision)
    fig.add_hline(y=0, line_color='#7A8DA9', line_width=1)
    fig.update_yaxes(title_text='Rank IC', range=[-1.05, 1.05], tickformat='.1f')
    fig.update_xaxes(tickformat='%Y-%m', tickangle=0, nticks=6,
        unifiedhovertitle=dict(text='%{x|%Y-%m-%d}'))
    return fig


def build_metric_bars(frame: pd.DataFrame, *, category: str, value: str,
                      title: str = '', unit: str = 'percent',
                      revision: str = 'metric-bars') -> go.Figure:
    """Keep input order and units; an unavailable result is never a zero bar."""
    shown = frame[[category, value]].copy()
    shown[value] = pd.to_numeric(shown[value], errors='coerce')
    shown = shown.loc[shown[value].notna() & shown[value].abs().ne(float('inf'))]
    fmt = '.2%' if unit == 'percent' else ',.2f'
    fig = go.Figure(go.Bar(y=shown[category].astype(str), x=shown[value], orientation='h',
        marker_color=[PALETTE[0] if v >= 0 else '#B65269' for v in shown[value]], width=.38,
        text=[format(v, fmt) for v in shown[value]], textposition='outside', cliponaxis=False,
        hovertemplate='%{y}<br>%{x:'+fmt+'}<extra></extra>'))
    style_chart(fig, title=title, height=max(220, min(760, 135 + 38 * len(shown))), revision=revision)
    fig.update_layout(hovermode='closest', showlegend=False, margin=dict(l=18,r=86,t=62,b=42))
    fig.update_yaxes(autorange='reversed', type='category', showgrid=False, dtick=1)
    fig.update_xaxes(tickformat=fmt, showgrid=True, gridcolor='#E4EAF2', zeroline=True)
    if not shown.empty:
        lo, hi = min(0, shown[value].min()), max(0, shown[value].max())
        pad = (hi-lo)*.16 or .01
        fig.update_xaxes(range=[lo-pad, hi+pad])
    return fig


def build_comparison_chart(categories, series, *, title='', unit='percent'):
    """Aligned dot comparisons for sparse scenarios, retaining every observed value."""
    fig = go.Figure()
    fmt = '.2%' if unit == 'percent' else '.2f'
    for i, (label, values) in enumerate(series):
        shown = pd.DataFrame({'category': list(categories), 'value': list(values)})
        shown.value = pd.to_numeric(shown.value, errors='coerce')
        shown = shown.loc[shown.value.notna() & shown.value.abs().ne(float('inf'))]
        fig.add_trace(go.Scatter(x=shown.value, y=shown.category.astype(str),
            name=label, mode='markers+text',
            marker=dict(size=10, color=PALETTE[i % len(PALETTE)], line=dict(color='white',width=1.5)),
            text=[format(v, fmt) for v in shown.value], textposition='middle right',
            textfont=dict(size=14), cliponaxis=False,
            hovertemplate='%{y}<br>'+label+' %{x:'+fmt+'}<extra></extra>'))
    style_chart(fig, title=title, height=max(240, 140+len(categories)*44))
    fig.update_layout(hovermode='closest', showlegend=len(series)>1,
                      margin=dict(l=18,r=100,t=90 if len(series)>1 else 60,b=42))
    fig.update_yaxes(type='category',autorange='reversed',showgrid=True,gridcolor='#F0F3F8',zeroline=False,dtick=1)
    fig.update_xaxes(tickformat='.0%' if unit=='percent' else '.2f',showspikes=False,
                     showgrid=True,gridcolor='#E4EAF2',zeroline=True,zerolinecolor='#9AAAC0',rangemode='tozero')
    return fig
