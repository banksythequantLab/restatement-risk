"""Daily prices from Yahoo's public chart endpoint (unofficial; best-effort, cached, ~1 request/second) and a simple
event study around Item 4.02 notices. Fetched by the app, never inside the sandbox."""
import datetime as dt, hashlib, json, os, pathlib, time
from zoneinfo import ZoneInfo
import requests
ET = ZoneInfo("America/New_York")
CACHE = pathlib.Path(os.getenv("RR_CACHE", pathlib.Path(__file__).resolve().parent.parent / "cache")) / "prices"
_last = [0.0]
BENCH = "IWM"
HORIZONS = (1, 5, 30)
def history(symbol, ttl=12 * 3600):
    """[(date, adjclose)] or None if Yahoo has no data (typical for delisted symbols)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    sym = symbol.upper().replace(".", "-")
    p = CACHE / (hashlib.sha256(sym.encode()).hexdigest()[:20] + ".json")
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        d = json.loads(p.read_text())
    else:
        wait = 1.0 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"period1": 1514764800, "period2": int(time.time()), "interval": "1d", "events": "split,div"},
                             headers={"User-Agent": "Mozilla/5.0 (restatement-risk research)"}, timeout=30)
            if r.status_code == 404: d = {"none": True}
            else:
                r.raise_for_status(); res = r.json()["chart"]["result"][0]; q = res["indicators"]
                c = (q.get("adjclose") or [{}])[0].get("adjclose") or q["quote"][0]["close"]
                d = {"rows": [[dt.datetime.fromtimestamp(t, ET).date().isoformat(), v] for t, v in zip(res.get("timestamp") or [], c) if v]}
                if not d["rows"]: d = {"none": True}
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as x:
            return None  # transient: do not cache
        p.write_text(json.dumps(d))
    return None if d.get("none") else [(dt.date.fromisoformat(a), b) for a, b in d["rows"]]
def event_day(accepted):
    """EDGAR acceptanceDateTime is UTC. Filed at/after 16:00 ET (or on a non-trading day) -> next trading day."""
    a = dt.datetime.fromisoformat(accepted.replace("Z", "+00:00")).astimezone(ET)
    d = a.date()
    return (d + dt.timedelta(days=1) if a.time() >= dt.time(16, 0) else d), a
def study(px, bench, accepted, today=None):
    """Returns from the last close before day 0 to the close h trading days after day 0 (h=0 is day 0 itself)."""
    today = today or dt.date.today()
    d0, a = event_day(accepted)
    out = {"accepted_et": a.strftime("%Y-%m-%d %H:%M ET"), "after_close": a.time() >= dt.time(16, 0), "day0_calendar": d0.isoformat()}
    if not px: return {**out, "status": "no_price_data"}
    days = [d for d, _ in px]
    i = next((k for k, d in enumerate(days) if d >= d0), None)
    if i is None or i == 0: return {**out, "status": "no_price_near_filing", "first_price": days[0].isoformat()}
    # first-price-near-filing check: both the base close and day 0 must be within a week of the notice
    if (days[i] - d0).days > 6 or (d0 - days[i - 1]).days > 7: return {**out, "status": "no_price_near_filing", "first_price": days[0].isoformat()}
    bp = dict(bench or [])
    base_d, base_v = px[i - 1]
    out.update(status="ok", day0=days[i].isoformat(), base_date=base_d.isoformat(), base_close=round(base_v, 4), windows=[])
    for h in (0,) + HORIZONS:
        j = i + h; partial = j >= len(px)
        j = min(j, len(px) - 1)
        end_d, end_v = px[j]
        raw = end_v / base_v - 1
        adj = (raw - (bp[end_d] / bp[base_d] - 1)) if end_d in bp and base_d in bp else None
        out["windows"].append({"label": f"day 0" if h == 0 else f"0–{h}", "h": h, "end": end_d.isoformat(), "raw": round(raw, 4),
                               "adj": None if adj is None else round(adj, 4), "partial": partial,
                               "days_available": j - i})
    return out
def company_events(ticker, eightks):
    """eightks: rows with form, filed, items, accepted, url. Event study for each 4.02 + same-day confounders."""
    px = history(ticker); bench = history(BENCH)
    ev = []
    for r in eightks:
        if "4.02" not in (r.get("items") or "") or not r.get("accepted"): continue
        s = study(px, bench, r["accepted"]); s.update(form=r["form"], filed=r["filed"], url=r["url"], items=r["items"])
        d0 = s.get("day0") or s["day0_calendar"]; lo = dt.date.fromisoformat(r["filed"]) - dt.timedelta(days=1)
        s["confounders"] = [{"form": x["form"], "filed": x["filed"], "items": x["items"], "url": x["url"],
                             "earnings": "2.02" in (x.get("items") or "")}
                            for x in eightks if x is not r and lo <= dt.date.fromisoformat(x["filed"]) <= dt.date.fromisoformat(d0)
                            and set((x.get("items") or "").split(",")) - {"9.01", "4.02", ""}]
        ev.append(s)
    return {"ticker": ticker, "benchmark": BENCH, "has_prices": bool(px), "series": [(d.isoformat(), round(v, 4)) for d, v in (px or [])],
            "events": ev, "source": "Yahoo Finance chart endpoint (unofficial), adjusted close"}
