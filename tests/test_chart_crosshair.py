"""Execute the actual sync callback against chart API boundaries in Node."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_crosshair_waits_for_target_price_scale_and_time_coordinates():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for chart callback execution')
    source = (Path(__file__).resolve().parents[1]/'portfolio_app/chart_assets/workbench.js').read_text('utf8')
    callback = source.split('  charts.forEach((item, index) => item.chart.subscribeCrosshairMove',1)[1]
    callback = 'charts.forEach((item, index) => item.chart.subscribeCrosshairMove'+callback.split('  charts[0].chart.subscribeClick',1)[0]
    harness = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(0, 'utf8');
const day = '2025-01-06';
for (const condition of ['ready','unscaled','unknown-time','empty-panel','absent-time','second-series']) {
  const calls = [], handlers = [];
  const priceCoordinate = condition === 'unscaled' ? null : 100;
  const timeCoordinate = condition === 'unknown-time' ? null : 30;
  const ready = {values:new Map([[day,10.15]]),series:{priceToCoordinate:()=>priceCoordinate}};
  const empty = {values:new Map(),series:{priceToCoordinate:()=>null}};
  const chart = index => ({
    subscribeCrosshairMove:handler=>{handlers[index]=handler;},
    timeScale:()=>({timeToCoordinate:()=>timeCoordinate}),
    setCrosshairPosition:(value,time,series)=>{
      assert.notEqual(priceCoordinate,null,'unscaled target must not receive setCrosshairPosition');
      assert.notEqual(timeCoordinate,null,'unknown time must not receive setCrosshairPosition');
      calls.push({index,value,time});
      handlers[index]({time});
    },
    clearCrosshairPosition:()=>calls.push({index,cleared:true}),
  });
  const context = {charts:[{chart:chart(0)},{chart:chart(1)}],
    seriesByPane:[[ready],condition==='empty-panel'?[empty]:condition==='second-series'?[empty,ready]:[ready]],
    syncingCrosshair:false,times:[day],lastBar:0,updateLabels:()=>{}};
  vm.runInNewContext(source,context);
  handlers[0]({time:condition==='absent-time'?undefined:day});
  assert.equal(context.syncingCrosshair,false,'lock must release after every callback');
  assert.equal(calls.length,1,'sync event must not recurse');
  assert.equal(Boolean(calls[0].cleared),!['ready','second-series'].includes(condition),condition);
}
process.stdout.write(JSON.stringify({passed:6}));
'''
    result = subprocess.run([node,'-e',harness],input=callback,text=True,capture_output=True,timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'passed':6}
