"""Compare up to four saved NAVs on their original calendars and bases."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .research_charts import style_chart,PALETTE
from .research_manifest import valid_manifest


def _basis(manifest):
    if not isinstance(manifest,dict) or not manifest:
        return None
    # Run identities/parameters may differ; comparability is about inputs and
    # accounting conventions, not whether the two strategies are identical.
    return manifest['basis'] if valid_manifest(manifest) else None


def compare_projections(projections):
    if not 2<=len(projections)<=4:
        raise ValueError('请选择2至4个有净值曲线的结果')
    curves,summary={},[]
    for name,projection in projections.items():
        curve=projection.get('curve')
        if not isinstance(curve,pd.DataFrame) or curve.empty or not {'trade_date','nav','drawdown'}<=set(curve):
            raise ValueError('所选记录没有可比较的净值与回撤')
        curve=curve[['trade_date','nav','drawdown']].copy()
        curve['trade_date']=pd.to_datetime(curve.trade_date,errors='raise')
        if curve.trade_date.isna().any() or curve.trade_date.duplicated().any():
            raise ValueError('净值日期缺失或重复')
        curve=curve.sort_values('trade_date').reset_index(drop=True)
        for field in ('nav','drawdown'):
            curve[field]=pd.to_numeric(curve[field],errors='raise')
            if curve[field].isna().any() or not np.isfinite(curve[field]).all():
                raise ValueError('净值或回撤存在缺失、非有限值')
        if curve.nav.le(0).any() or curve.drawdown.gt(1e-8).any() or curve.drawdown.lt(-1).any():
            raise ValueError('净值或回撤范围无效')
        curves[name]=curve
        summary.append(dict(run=name,start=curve.trade_date.iloc[0].date().isoformat(),
            end=curve.trade_date.iloc[-1].date().isoformat(),sessions=len(curve),
            total_return=float(curve.nav.iloc[-1]-1),max_drawdown=float(curve.drawdown.min()),
            sharpe=projection.get('metrics',{}).get('sharpe')))
    names=list(projections)
    first=names[0]
    same_dates=all(curves[first].trade_date.equals(curves[n].trade_date) for n in names[1:])
    bases=[_basis(projections[n].get('manifest')) for n in names]
    same_basis=all(b is not None and b==bases[0] for b in bases)
    differences={}
    for field in ('parameters','manifest'):
        values={n:projections[n].get(field) for n in names}
        if any(values[n]!=values[first] for n in names[1:]):
            differences[field]=values
    if not same_dates:
        differences['period']={n:curves[n].trade_date.dt.strftime('%Y-%m-%d').tolist() for n in names}
    return dict(curves=curves,summary=pd.DataFrame(summary),comparable=same_dates and same_basis,
        same_dates=same_dates,same_basis=same_basis,differences=differences)


def comparison_curve(result):
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.07,row_heights=[.7,.3])
    for index,(name,curve) in enumerate(result['curves'].items()):
        color=PALETTE[index%len(PALETTE)]
        for row,column in [(1,'nav'),(2,'drawdown')]:
            fig.add_trace(go.Scatter(x=curve.trade_date.tolist(),y=curve[column].tolist(),mode='lines',
                line=dict(color=color,width=2 if row==1 else 1.4),name=name,legendgroup=name,
                showlegend=row==1,connectgaps=False,
                hovertemplate='%{x|%Y-%m-%d}<br>%{y:'+('.4f' if row==1 else '.2%')+'}<extra>%{fullData.name}</extra>'),row=row,col=1)
    style_chart(fig,height=490)
    fig.update_yaxes(title_text='原始单位净值',row=1,col=1)
    fig.update_yaxes(title_text='原始回撤',tickformat='.1%',row=2,col=1)
    fig.update_xaxes(tickformat='%Y-%m',hoverformat='%Y-%m-%d')
    return fig
