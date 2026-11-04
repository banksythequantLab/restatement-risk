"""SEC fetcher: fixed User-Agent, <=10 req/s (we use ~8), everything cached on disk."""
import hashlib, json, pathlib, re, time, html
import requests
UA = "Derek Soltis dj@soltis.info"
import os
CACHE = pathlib.Path(os.getenv("RR_CACHE", pathlib.Path(__file__).resolve().parent.parent / "cache"))
_last = [0.0]
def _get(url, ttl=86400, binary=False):
    CACHE.mkdir(exist_ok=True)
    p = CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".cache")
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        return p.read_bytes()
    wait = 0.125 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    for attempt in range(4):
        _last[0] = time.time()
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, timeout=60)
        if r.status_code in (429, 503): time.sleep(2 ** attempt); continue
        r.raise_for_status(); p.write_bytes(r.content); return r.content
    r.raise_for_status()
def get_json(url, ttl=86400): return json.loads(_get(url, ttl))
def cik10(cik): return str(int(cik)).zfill(10)

def tickers():
    d = get_json("https://www.sec.gov/files/company_tickers.json", ttl=7 * 86400)
    return [{"cik": v["cik_str"], "ticker": v["ticker"], "name": v["title"]} for v in d.values()]
def lookup(ticker_or_cik):
    s = str(ticker_or_cik).upper()
    for t in tickers():
        if t["ticker"] == s or (s.isdigit() and int(s) == t["cik"]): return t
    raise KeyError(ticker_or_cik)

def recent_402(start="2025-01-01", end=None, pages=3):
    """Item 4.02 (non-reliance) 8-K/8-K/A filers via EDGAR full-text search."""
    end = end or time.strftime("%Y-%m-%d"); out = {}
    for i in range(pages):
        d = get_json(f"https://efts.sec.gov/LATEST/search-index?q=%22Item%204.02%22&forms=8-K"
                     f"&dateRange=custom&startdt={start}&enddt={end}&from={i*100}", ttl=6 * 3600)
        for h in d["hits"]["hits"]:
            s = h["_source"]
            if "4.02" not in (s.get("items") or []): continue
            acc, fn = h["_id"].split(":", 1); cik = int(s["ciks"][0])
            out.setdefault(acc, {"cik": cik, "name": s["display_names"][0], "form": s["form"], "filed": s["file_date"],
                "items": s.get("items"),
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fn}"})
        if len(d["hits"]["hits"]) < 100: break
    return sorted(out.values(), key=lambda x: x["filed"], reverse=True)

def companyfacts(cik): return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10(cik)}.json")

def filings(cik):
    """Relevant filings from the submissions API: 8-K with Item 4.02, 10-K/A, 10-Q/A, CORRESP, UPLOAD."""
    d = get_json(f"https://data.sec.gov/submissions/CIK{cik10(cik)}.json", ttl=6 * 3600)
    rows, blocks = [], [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        blocks.append(get_json("https://data.sec.gov/submissions/" + f["name"]))
    for b in blocks:
        for i, form in enumerate(b["form"]):
            items = b.get("items", [""] * len(b["form"]))[i] or ""
            keep = form in ("10-K/A", "10-Q/A", "CORRESP", "UPLOAD") or form.startswith("8-K")
            if not keep: continue
            acc = b["accessionNumber"][i]
            rows.append({"form": form, "filed": b["filingDate"][i], "items": items, "accession": acc,
                         "accepted": (b.get("acceptanceDateTime") or [None] * len(b["form"]))[i],
                         "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{b['primaryDocument'][i]}"})
    rows.sort(key=lambda r: r["filed"], reverse=True)
    return {"name": d["name"], "cik": int(cik), "sic": d.get("sic"), "sicDescription": d.get("sicDescription"),
            "tickers": d.get("tickers") or [],
            "filings": [r for r in rows if not r["form"].startswith("8-K") or "4.02" in r["items"]],
            "eightks": [r for r in rows if r["form"].startswith("8-K")]}

AAER_URL = "https://www.sec.gov/enforcement-litigation/accounting-auditing-enforcement-releases"
def aaers(pages=33):
    rows = []
    for p in range(pages):
        t = _get(AAER_URL + (f"?page={p}" if p else ""), ttl=86400).decode("utf-8", "replace")
        trs = re.findall(r"<tr.*?</tr>", t, re.S)[1:]
        if not trs: break
        for tr in trs:
            links = re.findall(r'href="([^"]+)"', tr)
            txt = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", tr))).strip()
            m = re.match(r"(\w+\.? \d+, \d{4}) (.*?) Release No\. (.*?)(?: See Also:.*)?$", txt)
            if not m: continue
            rel = m.group(3); aaer = re.search(r"AAER-(\d+)", rel)
            rows.append({"date": m.group(1), "name": m.group(2).strip(), "release": rel.strip(),
                         "aaer": int(aaer.group(1)) if aaer else None,
                         "url": ("https://www.sec.gov" + links[0]) if links and links[0].startswith("/") else (links[0] if links else None)})
    return rows
SUFFIX = r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|lp|plc|holdings?|group|n\.?v|s\.?a|the)\b"
def norm(n):
    n = re.sub(r"\(.*?\)", " ", n.lower()); n = re.sub(r"[/\\].*$", "", n)
    n = re.sub(r"[^a-z0-9& ]", " ", n); n = re.sub(SUFFIX, " ", n)
    return re.sub(r"\s+", " ", n).strip()
def aaer_matches(name, rows=None):
    """Exact normalized-name match of a company against AAER respondent text. Conservative: no fuzzy matching,
    so a miss means 'not found by name', not 'never charged'."""
    rows = rows if rows is not None else aaers(); k = norm(name)
    if len(k) < 3: return []
    return [r for r in rows if re.search(r"(^| )" + re.escape(k) + r"( |$)", norm(r["name"]))]
