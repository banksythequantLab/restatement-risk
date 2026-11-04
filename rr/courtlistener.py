"""Securities class-action lookup via CourtListener RECAP docket search (API v4). Token from env
COURTLISTENER_API_TOKEN (never logged). Cached; degrades to status 'unavailable' when the API is down."""
import datetime as dt, hashlib, json, os, pathlib, re, time
import requests
CACHE = pathlib.Path(os.getenv("RR_CACHE", pathlib.Path(__file__).resolve().parent.parent / "cache")) / "courtlistener"
URL = "https://www.courtlistener.com/api/rest/v4/search/"
_last = [0.0]
SUFFIX = re.compile(r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|holdings?|group|the)\b\.?", re.I)
def core_name(name):
    n = re.sub(r"\(.*?\)|/[A-Z]{2}/?$", " ", name); n = re.sub(r"[^\w&' -]", " ", n); n = SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()
def search(name, notice_date, days_after=365, ttl=7 * 86400):
    tok = os.getenv("COURTLISTENER_API_TOKEN")
    if not tok: return {"status": "not_configured"}
    core = core_name(name)
    if len(core) < 3: return {"status": "name_too_short"}
    start = dt.date.fromisoformat(notice_date); end = start + dt.timedelta(days=days_after)
    q = (f'caseName:("{core}") AND (suitNature:"Securities/Commodities/Exchange" OR "10b-5" OR "Securities Exchange Act")')
    params = {"type": "r", "q": q, "filed_after": start.isoformat(), "filed_before": end.isoformat(), "order_by": "dateFiled asc"}
    key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
    CACHE.mkdir(parents=True, exist_ok=True); p = CACHE / f"{key}.json"
    if p.exists() and time.time() - p.stat().st_mtime < ttl: return json.loads(p.read_text())
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get(URL, params=params, headers={"Authorization": f"Token {tok}", "User-Agent": "restatement-risk (dj@soltis.info)"}, timeout=30)
        if r.status_code != 200: return {"status": "unavailable", "http": r.status_code, "query": q}
        res = r.json().get("results", [])
    except (requests.RequestException, ValueError) as x:
        return {"status": "unavailable", "error": type(x).__name__, "query": q}
    toks = set(core.lower().split())
    cases = []
    for c in res[:20]:
        cn = c.get("caseName") or ""
        if not toks <= set(re.findall(r"[\w&']+", cn.lower())): continue   # company name must appear in the caption
        cases.append({"caseName": cn, "dateFiled": c.get("dateFiled"), "court": c.get("court") or c.get("court_id"),
                      "docketNumber": c.get("docketNumber"), "suitNature": c.get("suitNature"), "cause": c.get("cause"),
                      "url": "https://www.courtlistener.com" + (c.get("docket_absolute_url") or "")})
    out = {"status": "ok", "query": q, "window": [start.isoformat(), end.isoformat()], "cases": cases, "raw_hits": len(res),
           "fetched": time.strftime("%Y-%m-%d %H:%M")}
    p.write_text(json.dumps(out)); return out
