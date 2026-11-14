import io
import json
import pytest
import scripts.fetch_tushare as downloader


def response(monkeypatch, items, code=0):
 def open_request(request, timeout):
  assert request.full_url == "https://api.waditu.com"
  assert json.loads(request.data)["token"] == "test-only"
  return io.BytesIO(json.dumps(dict(code=code,data=dict(fields=["ts_code","trade_date","open","high","low","close"],items=items))).encode())
 monkeypatch.setattr(downloader,"urlopen",open_request)


def test_download_validates_and_sorts(monkeypatch):
 response(monkeypatch,[["600000.SH","20240103",10,11,9,10],["600000.SH","20240102",10,11,9,10]])
 f=downloader.fetch_daily("600000.SH","20240101","20240131","test-only")
 assert f.trade_date.tolist()==["20240102","20240103"]


@pytest.mark.parametrize("items", [[],[["WRONG","20240102",10,11,9,10]],[["600000.SH","20240102",10,11,12,10]],[["600000.SH","20240102",10,11,9,float("inf")]]])
def test_bad_source_bars_are_rejected(monkeypatch,items):
 response(monkeypatch,items)
 with pytest.raises(ValueError):downloader.fetch_daily("600000.SH","20240101","20240131","test-only")


def test_missing_credentials_and_invalid_date_stop_before_network():
 for symbol,start,end,token in [("600000.SH","20240101","20240131",""),("600000.SH","20240201","20240131","test-only"),("bad","20240101","20240131","test-only")]:
  with pytest.raises(ValueError):downloader.fetch_daily(symbol,start,end,token)
