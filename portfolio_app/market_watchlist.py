"""Recent raw-price paths for existing favorites, preserving missing sessions."""
import pandas as pd
import streamlit as st

from .market_overview import market_overview, overview_sessions
from .market_query import query_daily
from .state_paths import state_root
from .watchlist import WatchlistStore


def watchlist_trends(frame, *, manifest, session, symbols, window=20):
    if type(window) is not int or not 1 <= window <= 60:
        raise ValueError('自选走势窗口必须为1至60个交易日')
    sessions = overview_sessions(manifest)
    if session not in sessions:
        raise ValueError('自选走势日期不在已核验交易日内')
    symbols = list(dict.fromkeys(symbols))
    if len(symbols) > 50:
        raise ValueError('自选走势最多展示50只证券')
    sessions = [day for day in sessions if day <= session][-window:]
    # Reuse the unit, date, uniqueness and source-price checks for every displayed day.
    reports = {day: market_overview(frame,manifest=manifest,session=day)['details'].set_index('symbol')
        for day in sessions}
    master = {r['symbol']:r for r in manifest['instrument_master']['records']}
    scope = set(manifest['range']['symbols'])
    rows = []
    for symbol in symbols:
        row = dict(symbol=symbol,name=master.get(symbol,{}).get('name',''),trend=[],
            close=None,price_change=None,amount=None,observed_sessions=0,expected_sessions=0,
            status='不在此版本')
        if symbol not in scope:
            rows.append(row)
            continue
        instrument = master[symbol]
        calendar = manifest['calendars'][instrument['market']]
        opened = {day for day, is_open in calendar['days'] if is_open}
        values = []
        for day in sessions:
            table = reports[day]
            eligible = symbol in table.index and day in opened
            row['expected_sessions'] += int(eligible)
            close = table.loc[symbol,'close'] if eligible else None
            values.append(float(close) if close is not None and pd.notna(close) else None)
        anchor = next((v for v in values if v is not None),None)
        row['trend'] = [v/anchor-1 if v is not None else None for v in values]
        row['observed_sessions'] = sum(v is not None for v in values)
        latest = reports[session]
        if symbol not in latest.index:
            row['status'] = '当日不在上市范围'
        elif pd.isna(latest.loc[symbol,'observed']) or not bool(latest.loc[symbol,'observed']):
            row['status'] = '当日行情缺失'
        else:
            record = latest.loc[symbol]
            row.update(close=record.close,price_change=record.price_change,amount=record.amount,
                status='已记录' if pd.notna(record.price_change) else '涨跌未知')
        rows.append(row)
    return pd.DataFrame(rows, columns=['symbol','name','trend','close','price_change','amount',
        'observed_sessions','expected_sessions','status'])


def render_watchlist_trends(store, manifest, *, session):
    try:
        favorites = WatchlistStore(state_root()/'watchlist.json').symbols
    except (OSError,ValueError):
        st.caption('本地自选暂时无法读取。')
        return
    st.markdown('**自选走势**')
    if not favorites:
        st.caption('在证券行情中加入自选后，这里显示近期走势。')
        return
    in_scope = [s for s in favorites if s in manifest['range']['symbols']]
    sessions = [d for d in overview_sessions(manifest) if d <= session][-20:]
    try:
        frame = query_daily(store,manifest['snapshot_id'],symbols=in_scope,
            start=sessions[0],end=session,columns=['symbol','trade_date','close','pre_close','amount','volume']) if in_scope else pd.DataFrame()
        if not in_scope:
            # No unsupported query or invented prices for favorites outside the snapshot.
            st.caption('自选证券均不在此行情版本中，请先更新对应证券。')
            return
        table = watchlist_trends(frame,manifest=manifest,session=session,symbols=favorites)
    except (OSError,ValueError,KeyError):
        st.error('自选走势校验失败，已停止读取。')
        return
    table['coverage'] = table.observed_sessions.astype(str)+' / '+table.expected_sessions.astype(str)
    table['trend'] = table.trend.map(lambda path:[None if v is None else v*100 for v in path])
    display = table[['symbol','name','trend','price_change','close','amount','coverage','status']].rename(columns={
        'symbol':'证券','name':'名称','trend':'近期价格走势（%）','price_change':'当日价格涨跌',
        'close':'当日收盘（元）','amount':'当日成交额（元）','coverage':'走势覆盖','status':'状态'})
    st.caption(f'{sessions[0]}—{session} · 原始价格相对首个有效收盘；空缺不补价。')
    event = st.dataframe(display,hide_index=True,width='stretch',on_select='rerun',
        selection_mode='single-row',key='market_watchlist_'+manifest['snapshot_id']+session,column_config={
        '近期价格走势（%）':st.column_config.LineChartColumn(width='medium',y_min=None,y_max=None),
        '当日价格涨跌':st.column_config.NumberColumn(format='percent'),
        '当日收盘（元）':st.column_config.NumberColumn(format='%.2f'),
        '当日成交额（元）':st.column_config.NumberColumn(format='localized')})
    if event.selection.rows:
        selected = display.iloc[event.selection.rows[0]]['证券']
        if selected in in_scope and st.button('打开 '+selected+' 行情',key='market_watchlist_open'):
            return selected
    return None


def render_watchlist_toggle(symbol):
    try:
        store = WatchlistStore(state_root()/'watchlist.json')
        included = symbol in store.symbols
        if st.button('移出自选' if included else '加入自选',key='market_watch_favorite'):
            if included:
                store.remove(symbol)
            else:
                if len(store.symbols) >= 50:
                    st.info('自选已满50只，请先移出不需要的证券。')
                    return
                store.add(symbol)
            st.rerun()
    except (OSError,ValueError):
        st.error('自选未能保存，请检查本地状态目录。')
