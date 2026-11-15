(function () {
  'use strict';
  const payload = window.__QUANT_CHART_PAYLOAD__;
  const root = document.getElementById('chart');
  const panes = document.getElementById('panes');
  if (!payload.bars.length || !window.LightweightCharts) {
    panes.textContent = payload.bars.length ? '图表引擎不可用' : '暂无可用行情';
    return;
  }
  const theme = getComputedStyle(document.documentElement);
  const up = theme.getPropertyValue('--q-up').trim(), down = theme.getPropertyValue('--q-down').trim();
  const charts = [], seriesByPane = [], labels = [];
  const times = payload.bars.map(bar => bar.time);
  const barsByTime = new Map(payload.bars.map(bar => [bar.time, bar]));
  const volumeByTime = new Map(payload.volume.map(item => [item.time, item]));
  const panelGroups = payload.indicators.filter(item => item.pane === 'panel');
  const overlayGroups = payload.indicators.filter(item => item.pane === 'overlay');
  const density = payload.density || {min_bar_spacing: 2.5, max_bar_spacing: 12};
  const devicePixelRatio = Math.max(1, Math.min(2, Number(window.devicePixelRatio) || 1));
  const state = payload.chart_state || {version: 1, storage_key: 'quant-chart-state-v1:default', bounds: payload.bounds || {}};
  const storageKey = String(state.storage_key || 'quant-chart-state-v1:default');
  const format = value => Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumFractionDigits: Math.abs(value) > 0 && Math.abs(value) < .01 ? 8 : 4}) : '--';
  const publicEvents = Array.isArray(payload.events) ? payload.events : [];
  // A fresh iframe must not reuse the previous mount's sequence numbers.
  let selectionSequence = Date.now() * 1000;
  function emitSelection(time, kind = 'date') {
    if (!payload.selection_bridge || !barsByTime.has(time)) return;
    window.parent.postMessage({type: 'quant:selection', version: 1, source: 'kline',
      chart_id: payload.selection_bridge.chart_id, symbol: payload.symbol,
      sequence: ++selectionSequence, date: time, kind}, '*');
  }
  const eventById = new Map(publicEvents.map(event => [String(event.event_id), event]));
  const context = {is_realtime: false, ...(payload.data_context || {})};
  function pane(id, title, kind, last) {
    const wrap = document.createElement('div');
    wrap.className = 'pane pane-' + kind;
    const label = document.createElement('div');
    label.className = 'pane-label';
    const heading = document.createElement('strong');
    heading.textContent = title;
    label.appendChild(heading);
    const values = document.createElement('span');
    label.appendChild(values);
    const canvas = document.createElement('div');
    canvas.id = id; canvas.className = 'pane-canvas';
    wrap.append(label, canvas); panes.appendChild(wrap);
    const chart = LightweightCharts.createChart(canvas, {
      width: Math.max(120, canvas.clientWidth), height: Math.max(40, canvas.clientHeight),
      layout: {background: {color: theme.getPropertyValue('--q-surface').trim()}, textColor: theme.getPropertyValue('--q-muted').trim(), fontSize: parseInt(theme.getPropertyValue('--q-font-chart'), 10), fontFamily: theme.getPropertyValue('--q-font').trim()},
      localization: {locale: 'zh-CN'},
      grid: {vertLines: {visible: false}, horzLines: {color: '#edf1f2'}},
      rightPriceScale: {minimumWidth: 76, borderColor: '#d8e0eb', scaleMargins: {top: 0.12, bottom: 0.08}},
      timeScale: {visible: last, borderColor: '#e2e8eb', rightOffset: 0, minBarSpacing: density.min_bar_spacing, barSpacing: Math.max(density.min_bar_spacing, 8), fixLeftEdge: true, fixRightEdge: true},
      crosshair: {mode: LightweightCharts.CrosshairMode.Normal, vertLine: {color: '#8c9ba3', labelVisible: last}, horzLine: {color: '#8c9ba3'}},
      handleScale: {axisPressedMouseMove: {time: true, price: false}, mouseWheel: true, pinch: true},
    });
    charts.push({chart, canvas}); seriesByPane.push([]); labels.push(values);
    return chart;
  }
  const periodLabels = {"1d": "日K", "1w": "周K", "1m": "月K"};
  const periodLabel = periodLabels[payload.period] || "日K";
  const periodInfo = payload.period_info || {label: periodLabel, basis: payload.period === '1d' ? '日线原始数据' : '由日线聚合', incomplete_bars: 0};
  const meta = {
    label: document.getElementById('period-label'),
    basis: document.getElementById('period-basis'),
    status: document.getElementById('period-status'),
    zoom: document.getElementById('zoom-limit-label'),
  };
  if (meta.label) meta.label.textContent = periodInfo.label || periodLabel;
  if (meta.basis) meta.basis.textContent = periodInfo.basis || '';
  if (meta.status) meta.status.textContent = Number(periodInfo.incomplete_bars) > 0
    ? `未完成周期 ${Number(periodInfo.incomplete_bars)} 根`
    : '周期完整';
  const chart = pane('price-pane', payload.symbol + ' · ' + periodLabel, 'price', false);
  const minimumPrice = payload.bars.reduce((minimum, bar) => Math.min(minimum, bar.low), Infinity);
  const precision = minimumPrice < .01 ? 8 : 4;
  const candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down, priceLineVisible: true, lastValueVisible: true,
    priceFormat: {type: 'price', precision, minMove: 10 ** -precision}});
  candles.setData(payload.bars);
  seriesByPane[0].push({series: candles, name: '收', values: new Map(payload.bars.map(bar => [bar.time, bar.close])), color: '#24343c'});
  if (payload.markers.length) candles.setMarkers(payload.markers);
  function addSeries(target, series, paneIndex, histogram) {
    const line = histogram ? target.addHistogramSeries({priceLineVisible: false, lastValueVisible: false}) : target.addLineSeries({
      color: series.color, lineWidth: 2, lineStyle: series.style === 'dashed' ? 2 : 0,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    const values = new Map(series.data.map(point => [point.time, point.value]));
    // Whitespace aligns every pane's logical indices, including indicator warm-up.
    line.setData(times.map(time => values.has(time) ? {
      time, value: values.get(time), ...(histogram ? {color: values.get(time) >= 0 ? up : down} : {}),
    } : {time}));
    seriesByPane[paneIndex].push({series: line, name: series.label, values, color: series.color});
    return line;
  }
  for (const indicator of overlayGroups) {
    for (const series of indicator.series) addSeries(chart, series, 0, false);
  }
  const volumeUnit = String(context.volume_unit || 'unknown');
  const volumeChart = pane('volume-pane', '成交量 · ' + (volumeUnit === 'unknown' ? '源单位' : volumeUnit), 'volume', !panelGroups.length);
  const volume = volumeChart.addHistogramSeries({priceFormat: {type: 'volume'}, priceLineVisible: false, lastValueVisible: false});
  volume.setData(times.map(time => volumeByTime.get(time) || {time}));
  seriesByPane[1].push({series: volume, name: 'VOL', values: new Map(payload.volume.map(item => [item.time, item.value])), color: '#52636c'});
  for (const [index, indicator] of panelGroups.entries()) {
    const panelChart = pane('panel-pane-' + index, indicator.key, 'indicator', index === panelGroups.length - 1);
    for (const series of indicator.series) {
      const histogram = series.column === 'macd_hist';
      const line = addSeries(panelChart, series, index + 2, histogram);
      if (indicator.key === 'RSI' && !histogram) {
        for (const price of [30, 70]) line.createPriceLine({price, color: '#b8c4ca', lineWidth: 1, lineStyle: 2, axisLabelVisible: false});
      }
    }
  }
  const minBars = Math.min(payload.zoom.min_visible_bars, times.length);
  const maxBars = payload.zoom.max_visible_bars;
  const lastBar = times.length - 1;
  let correctingRange = false, syncingCrosshair = false, persistenceReady = false;
  let currentRange = null;
  function visibleLimit() {
    const width = Math.max(120, root.clientWidth || 120);
    const drawableWidth = Math.max(56, width - 64);
    const densityLimit = Math.floor(drawableWidth / Math.max(1, Number(density.min_bar_spacing)));
    return Math.min(maxBars, Math.max(minBars, densityLimit));
  }
  function readStoredRange() {
    try {
      const saved = JSON.parse(window.localStorage.getItem(storageKey) || 'null');
      const range = saved && saved.version === 1 && saved.bounds && saved.bounds.start === state.bounds.start && saved.bounds.end === state.bounds.end ? saved.range : null;
      if (!range || !Number.isFinite(Number(range.from)) || !Number.isFinite(Number(range.to))) return null;
      return {from: Number(range.from), to: Number(range.to)};
    } catch (_) { return null; }
  }
  function saveRange(range) {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({version: 1, bounds: state.bounds || payload.bounds || {}, range}));
    } catch (_) { /* storage may be unavailable in private browsing */ }
  }
  function clampRange(range) {
    if (!range || correctingRange) return;
    const limit = visibleLimit();
    const requestedFrom = Number(range.from), requestedTo = Number(range.to);
    const left = Math.min(requestedFrom, requestedTo), right = Math.max(requestedFrom, requestedTo);
    const span = Math.round(Math.max(minBars, Math.min(limit, right - left + 1)));
    const to = Math.max(span - 1, Math.min(lastBar, Math.round(right)));
    const from = Math.max(0, to - span + 1);
    if (![from, to].every(Number.isFinite)) return;
    currentRange = {from, to};
    correctingRange = true;
    try { for (const item of charts) item.chart.timeScale().setVisibleLogicalRange(currentRange); }
    finally { correctingRange = false; }
    const visibleBars = Math.round(to - from + 1);
    document.getElementById('range-label').textContent = '当前可见范围 ' + times[Math.ceil(from)] + ' ~ ' + times[Math.floor(to)] + ' · ' + visibleBars + '根';
    if (meta.zoom) meta.zoom.textContent = '缩放范围 ' + minBars + '–' + limit + '根';
    document.querySelector('[data-action="zoom-in"]').disabled = span <= minBars + 0.01;
    document.querySelector('[data-action="zoom-out"]').disabled = span >= limit - 0.01;
    document.querySelectorAll('[data-bars]').forEach(button => {
      const requested = button.dataset.bars === 'all' ? limit : Number(button.dataset.bars);
      button.classList.toggle('selected', Number.isFinite(requested) && Math.abs(requested - span) < 1);
    });
    if (persistenceReady) saveRange(currentRange);
  }
  for (const item of charts) item.chart.timeScale().subscribeVisibleLogicalRangeChange(clampRange);
  function updateLabels(time) {
    const bar = barsByTime.get(time);
    for (let index = 0; index < labels.length; index++) {
      labels[index].replaceChildren();
      if (index === 0 && bar) {
        const ohlc = document.createElement('span');
        ohlc.className = 'ohlc-values';
        for (const text of [time, '开 ' + format(bar.open), '高 ' + format(bar.high), '低 ' + format(bar.low), '收 ' + format(bar.close)]) {
          const value = document.createElement('span'); value.textContent = text; ohlc.appendChild(value);
        }
        labels[index].appendChild(ohlc);
      }
      for (const entry of seriesByPane[index].slice(index === 0 ? 1 : 0)) {
        const text = document.createElement('span'); text.style.color = entry.color;
        text.textContent = entry.name + ' ' + format(entry.values.get(time));
        labels[index].appendChild(text);
      }
    }
  }
  function safeText(value) { return value == null || value === '' ? '--' : String(value); }
  function detailRow(label, value) {
    const row = document.createElement('div'); row.className = 'detail-row';
    const name = document.createElement('span'); name.textContent = label;
    const text = document.createElement('strong'); text.textContent = safeText(value);
    row.append(name, text); return row;
  }
  function showDrawer(title, rows) {
    const drawer = document.getElementById('data-detail-drawer');
    document.getElementById('drawer-title').textContent = title;
    const body = document.getElementById('drawer-body'); body.replaceChildren();
    rows.forEach(([label, value]) => body.appendChild(detailRow(label, value)));
    drawer.setAttribute('aria-hidden', 'false');
  }
  function showEventGroup(group, publish = true) {
    if (!group || !group.length) return;
    const first = group[0];
    if (publish) emitSelection(first.effective_date || first.decision_date, 'event');
    const quantity = group.reduce((sum, event) => sum + (Number(event.quantity) || 0), 0);
    const ids = group.map(event => String(event.event_id));
    const evidence = first.evidence && typeof first.evidence === 'object' ? Object.keys(first.evidence).join('、') : '--';
    const rows = [
      ['事件层', first.event_type], ['状态', group.length > 1 ? '同日聚合' : first.status], ['方向', first.side],
      ['信号日期', first.decision_date], ['执行/成交日期', first.fill_date || first.effective_date],
      ['事件数量', group.length], ['合计数量', quantity || '--'],
      ['事件ID', ids.join('、')], ['价格', format(Number(first.price))],
      ['原因', first.reason_text_public || first.reason_code], ['证据字段', evidence],
    ];
    showDrawer((group.length > 1 ? '研究事件组 · ' : '研究事件 · ') + safeText(first.event_id), rows);
    document.querySelectorAll('.event-chip').forEach(chip => chip.classList.toggle('active', chip.dataset.eventIds && ids.some(id => chip.dataset.eventIds.split(',').includes(id))));
  }
  const showEvent = event => showEventGroup(event ? [event] : []);
  const eventGroups = (events, aggregateAcrossLayers = false) => {
    const groups = new Map();
    events.forEach(event => {
      const key = aggregateAcrossLayers
        ? [event.effective_date || event.decision_date, event.side || '', event.symbol || payload.symbol].join('|')
        : event.event_type === 'FILL' ? [event.event_type, event.effective_date, event.side].join('|') : String(event.event_id);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(event);
    });
    return [...groups.values()];
  };
  function renderEvents(layer) {
    const strip = document.getElementById('event-strip'); strip.replaceChildren();
    eventGroups(publicEvents.filter(event => layer === 'all' || event.event_type === layer), layer === 'all').forEach(group => {
      const event = group[0];
      const chip = document.createElement('button'); chip.className = 'event-chip'; chip.type = 'button';
      chip.dataset.eventId = String(event.event_id); chip.dataset.eventIds = group.map(item => String(item.event_id)).join(','); chip.dataset.eventType = String(event.event_type || '');
      chip.setAttribute('data-event-id', String(event.event_id)); chip.setAttribute('data-event-ids', chip.dataset.eventIds); chip.setAttribute('data-layer', String(event.event_type || ''));
      chip.textContent = (event.effective_date || event.decision_date || '--') + ' · ' + (event.side === 'BUY' ? '买入' : event.side === 'SELL' ? '卖出' : event.event_type) + (group.length > 1 ? ` ×${group.length}` : '');
      chip.addEventListener('click', () => showEventGroup(group)); strip.appendChild(chip);
    });
  }
  document.querySelectorAll('[data-layer]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-layer]').forEach(item => item.classList.toggle('selected', item === button));
    renderEvents(button.dataset.layer);
  }));
  document.querySelector('[data-action="data-detail"]').addEventListener('click', () => showDrawer('行情数据详情', [
    ['数据来源', context.source], ['标的', context.symbol || payload.symbol], ['价格口径', context.price_mode],
    ['价格单位', context.price_unit], ['成交量单位', context.volume_unit], ['覆盖起点', context.coverage_start || payload.bounds.start],
    ['覆盖终点', context.coverage_end || payload.bounds.end], ['数据截止', context.as_of || payload.bounds.end],
    ['实时行情', context.is_realtime ? '是' : '否'], ['质量状态', context.quality_status],
    ['缺失必需值行数', context.missing_required_value_rows], ['异常OHLC行数', context.invalid_ohlc_rows],
  ]));
  document.querySelector('[data-action="close-drawer"]').addEventListener('click', () => document.getElementById('data-detail-drawer').setAttribute('aria-hidden', 'true'));
  renderEvents('all');
  charts.forEach((item, index) => item.chart.subscribeCrosshairMove(event => {
    if (syncingCrosshair) return;
    syncingCrosshair = true;
    try {
      const time = typeof event.time === 'string' ? event.time : null;
      updateLabels(time || times[lastBar]);
      charts.forEach((other, otherIndex) => {
        if (otherIndex === index) return;
        const entry = seriesByPane[otherIndex][0];
        const value = entry.values.get(time);
        if (time && Number.isFinite(value)) other.chart.setCrosshairPosition(value, time, entry.series);
        else other.chart.clearCrosshairPosition();
      });
    } finally { syncingCrosshair = false; }
  }));
  charts[0].chart.subscribeClick(param => {
    const markerId = param && param.hoveredObjectId ? String(param.hoveredObjectId) : '';
    const marker = payload.markers.find(item => String(item.id) === markerId);
    if (marker) {
      const markerEvents = publicEvents.filter(event =>
        event.effective_date === marker.time && String(event.side || '').toUpperCase() === (marker.position === 'belowBar' ? 'BUY' : 'SELL')
      );
      showEventGroup(eventGroups(markerEvents, true)[0] || (marker.event_ids || []).map(id => eventById.get(String(id))).filter(Boolean));
      return;
    }
    const time = param && typeof param.time === 'string' ? param.time : null;
    if (time) {
      const group = eventGroups(publicEvents.filter(event => event.effective_date === time), true)[0] || [];
      if (group.length) showEventGroup(group);
      else emitSelection(time);
    }
  });
  const reset = () => clampRange({from: Math.max(0, times.length - payload.zoom.initial_visible_bars), to: lastBar});
  document.querySelectorAll('[data-bars]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-bars]').forEach(other => other.classList.toggle('selected', other === button));
    const requested = button.dataset.bars === 'all' ? maxBars : Number(button.dataset.bars);
    clampRange({from: lastBar - requested + 1, to: lastBar});
  }));
  document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => {
    const action = button.dataset.action;
    if (action === 'full') { if (document.fullscreenElement) document.exitFullscreen(); else root.requestFullscreen?.(); return; }
    if (action === 'reset') { reset(); return; }
    const range = currentRange || {from: 0, to: lastBar};
    const span = (range.to - range.from + 1) * (action === 'zoom-in' ? 0.7 : 1.4);
    clampRange({from: range.to - span + 1, to: range.to});
  }));
  let resizePending = false;
  new ResizeObserver(() => {
    if (resizePending) return;
    resizePending = true;
    requestAnimationFrame(() => {
      correctingRange = true;
      try { for (const item of charts) item.chart.resize(Math.max(120, item.canvas.clientWidth), Math.max(40, item.canvas.clientHeight)); }
      finally { correctingRange = false; resizePending = false; }
      clampRange(readStoredRange() || currentRange || {from: lastBar - 119, to: lastBar});
    });
  }).observe(root);
  window.__QUANT_CHART__ = {charts: charts.map(item => item.chart), candles, clampRange, visibleLimit, minBars, lastBar, stateKey: storageKey, density, devicePixelRatio};
  updateLabels(times[lastBar]);
  const restoredRange = readStoredRange();
  clampRange(restoredRange || {from: lastBar - payload.zoom.initial_visible_bars + 1, to: lastBar});
  persistenceReady = true;
  // Restore the focused event selected in the strategy result table.
  const focusedEvent = payload.focus_event_id ? eventById.get(String(payload.focus_event_id)) : null;
  if (focusedEvent) {
    const focusedTime = focusedEvent.effective_date || focusedEvent.decision_date;
    const focusedIndex = times.indexOf(focusedTime);
    if (focusedIndex >= 0) {
      const span = Math.min(visibleLimit(), Math.max(minBars, payload.zoom.initial_visible_bars));
      clampRange({from: focusedIndex - Math.floor(span / 2), to: focusedIndex + Math.ceil(span / 2) - 1});
      updateLabels(focusedTime);
      candles.setMarkers(payload.markers);
      showEventGroup(eventGroups(publicEvents.filter(event =>
        event.effective_date === focusedTime && event.symbol === focusedEvent.symbol && event.side === focusedEvent.side
      ), true)[0] || [focusedEvent], false);
    }
  }
})();
