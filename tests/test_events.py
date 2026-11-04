import datetime as dt, os, tempfile
os.environ.setdefault("RR_ROOT", tempfile.mkdtemp())
from rr import prices, courtlistener
from scripts.backtest import is_spac
D = dt.date
def series(start, n, f=lambda k: 100.0):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5: out.append((d, f(len(out))))
        d += dt.timedelta(days=1)
    return out
def test_after_close_moves_to_next_day():
    assert prices.event_day("2026-10-16T21:30:00.000Z")[0] == D(2026, 10, 17)      # 17:30 ET Fri -> next day (Mon by prices)
    assert prices.event_day("2026-10-16T13:00:00.000Z")[0] == D(2026, 10, 16)      # 09:00 ET
def test_study_windows_and_partial():
    px = series(D(2026, 10, 1), 20, lambda k: 100.0 if k < 12 else 90.0)
    bench = series(D(2026, 10, 1), 20)
    s = prices.study(px, bench, "2026-10-16T21:30:00.000Z")   # day 0 = Mon 10/19 = index 12
    assert s["status"] == "ok" and s["day0"] == "2026-10-19" and s["base_date"] == "2026-10-16"
    w = {x["label"]: x for x in s["windows"]}
    assert abs(w["day 0"]["raw"] + 0.10) < 1e-9 and abs(w["day 0"]["adj"] + 0.10) < 1e-9
    assert not w["0–5"]["partial"] and w["0–30"]["partial"] and w["0–30"]["days_available"] == 7
def test_no_price_near_filing():
    px = series(D(2025, 1, 1), 30)                       # e.g. a warrant ticker that only started trading years later
    assert prices.study(px, px, "2022-08-25T12:00:00.000Z")["status"] == "no_price_near_filing"
    assert prices.study(None, px, "2022-08-25T12:00:00.000Z")["status"] == "no_price_data"
def test_confounders(monkeypatch):
    px = series(D(2026, 10, 1), 20)
    monkeypatch.setattr(prices, "history", lambda s, **k: px)
    ek = [{"form": "8-K", "filed": "2026-10-16", "items": "4.02,9.01", "accepted": "2026-10-16T21:30:00.000Z", "url": "a"},
          {"form": "8-K", "filed": "2026-10-16", "items": "2.02,9.01", "accepted": "2026-10-16T21:00:00.000Z", "url": "b"},
          {"form": "8-K", "filed": "2026-10-16", "items": "9.01", "accepted": "2026-10-16T21:00:00.000Z", "url": "c"},
          {"form": "8-K", "filed": "2026-09-01", "items": "5.02", "accepted": "2026-09-01T21:00:00.000Z", "url": "d"}]
    ev = prices.company_events("X", ek)["events"]
    assert len(ev) == 1 and [c["url"] for c in ev[0]["confounders"]] == ["b"] and ev[0]["confounders"][0]["earnings"]
def test_spac_rule():
    assert is_spac("6770", "Anything Inc") and is_spac("7372", "GX Acquisition Corp. II") and not is_spac("7372", "GoPro, Inc.")
def test_courtlistener_degrades(monkeypatch):
    monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
    assert courtlistener.search("Latch, Inc.", "2022-08-25")["status"] == "not_configured"
    import requests
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "x")
    monkeypatch.setattr(courtlistener, "CACHE", __import__("pathlib").Path(tempfile.mkdtemp()))
    def boom(*a, **k): raise requests.ConnectionError()
    monkeypatch.setattr(requests, "get", boom)
    assert courtlistener.search("Latch, Inc.", "2022-08-25")["status"] == "unavailable"
    assert courtlistener.core_name("Latch, Inc.") == "Latch"
def test_notice_with_own_earnings_item_flagged(monkeypatch):
    from app import events_ui
    x = {"status": "ok", "form": "8-K", "filed": "2024-02-08", "url": "u", "items": "2.02,4.02,9.01", "accepted_et": "t", "after_close": True,
         "day0": "2024-02-09", "base_date": "2024-02-08", "base_close": 5.0, "windows": [], "confounders": []}
    assert "Item 2.02" in events_ui.event_rows(x)
