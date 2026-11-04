"""'What happened next' for every company with an 8-K Item 4.02 notice filed 2021-2023 (first notice per company).
Descriptive only: stock reaction around the notice (raw and minus IWM), SPAC/shell vs operating split, later AAER name
match, and a 'possible litigation disclosure' snippet from the company's own later filings (EDGAR full-text search).
No predictive or causal claims. Rate limits: SEC <=8 req/s (rr.sec), Yahoo ~1 req/s (rr.prices)."""
import datetime as dt, html, json, pathlib, re, statistics, sys, urllib.parse
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from datetime import datetime
from rr import sec, prices
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "backtest.json"
SPAC_NAME = re.compile(r"\bacquisition\s+(corp|corporation|co|company|inc|ltd|limited|holdings?)\b|\bblank check\b|\bspac\b"
                       r"|\bcapital acquisition\b|\bmerger (corp|sub)\b", re.I)
def is_spac(sic, name):
    """SPAC/shell = SIC 6770 (blank checks) OR name pattern '<X> Acquisition Corp/Inc/Ltd', 'blank check', 'merger corp'.
    De-SPACed operating companies that kept the SPAC's CIK get the operating SIC and are counted as operating
    unless the name still matches."""
    return str(sic or "") == "6770" or bool(SPAC_NAME.search(name or ""))
def aaer_date(s):
    for fmt in ("%b. %d, %Y", "%B %d, %Y", "%b %d, %Y"):
        try: return datetime.strptime(s.replace("Sept.", "Sep."), fmt).date()
        except ValueError: pass
def disp_tickers(name):
    m = [x for x in re.findall(r"\(([A-Z0-9.\-, ]{1,30})\)", name) if not x.startswith("CIK")]
    return [t.strip() for t in m[0].split(",")] if m else []
LIT = re.compile(r"class action complaint", re.I)
def litigation(cik, filed):
    end = (dt.date.fromisoformat(filed) + dt.timedelta(days=730)).isoformat()
    d = sec.get_json("https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(
        {"q": '"class action complaint"', "ciks": f"{int(cik):010d}", "dateRange": "custom", "startdt": filed, "enddt": end}), ttl=30 * 86400)
    for h in sorted(d["hits"]["hits"], key=lambda x: x["_source"]["file_date"])[:3]:
        adsh, fn = h["_id"].split(":")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{fn}"
        try: t = sec._get(url, ttl=365 * 86400).decode("utf-8", "ignore")
        except Exception: continue
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
        for m in LIT.finditer(t):
            w = t[max(0, m.start() - 350): m.end() + 350]
            if re.search(r"Exchange Act|10\(b\)|Securities Act|securities laws", w) and re.search(r"Case No|Civil Action|C\.A\. No| v\. ", w):
                return {"filed": h["_source"]["file_date"], "form": h["_source"]["form"], "url": url, "snippet": w.strip()}
    return None
def main():
    filers = []
    for y in (2021, 2022, 2023): filers += sec.recent_402(f"{y}-01-01", f"{y}-12-31", pages=10)
    first = {}
    for f in sorted(filers, key=lambda r: r["filed"]): first.setdefault(f["cik"], f)
    A = sec.aaers()
    for r in A: r["d"] = aaer_date(r["date"])
    bench = prices.history(prices.BENCH)
    rows = []
    for n, (cik, f) in enumerate(sorted(first.items(), key=lambda kv: kv[1]["filed"])):
        nm = f["name"].split("  (")[0]
        row = {"cik": cik, "name": nm, "notice_filed": f["filed"], "url": f["url"]}
        try:
            s = sec.filings(cik); acc = f["url"].split("/")[-2]
            ek = s["eightks"]; me = next((x for x in ek if x["accession"].replace("-", "") == acc), None)
            row.update(sic=s.get("sic"), sic_desc=s.get("sicDescription"), accepted=me and me["accepted"])
            cands = [t for t in disp_tickers(f["name"]) if not re.search(r"(WS|WT|W|U|R)$", t) or len(t) <= 3] + s.get("tickers", [])
            fm = re.match(r"([a-z]{1,5})[-_]", f["url"].split("/")[-1])   # Workiva-style file names start with the ticker
            if fm: cands.append(fm.group(1).upper())
            cands = list(dict.fromkeys(cands))[:4]
        except Exception as x:
            row["error"] = f"submissions: {type(x).__name__}"; cands = disp_tickers(f["name"])[:1]; me = None; ek = []
        row["spac"] = is_spac(row.get("sic"), nm)
        row["stock"] = {"status": "no_ticker"}
        if me and me.get("accepted"):
            for t in cands:
                st = prices.study(prices.history(t), bench, me["accepted"])
                st["ticker"] = t; row["stock"] = st
                if st["status"] == "ok": break
            if row["stock"]["status"] == "ok":
                d0 = row["stock"]["day0"]; lo = (dt.date.fromisoformat(f["filed"]) - dt.timedelta(days=1)).isoformat()
                row["same_day_8k"] = [{"filed": x["filed"], "items": x["items"], "url": x["url"]} for x in ek
                                      if x is not me and lo <= x["filed"] <= d0 and set(x["items"].split(",")) - {"9.01", "4.02", ""}]
                row["notice_items"] = me["items"]
                row["earnings_same_day"] = "2.02" in me["items"].split(",") or any("2.02" in x["items"] for x in row["same_day_8k"])
        elif cands: row["stock"] = {"status": "no_acceptance_time", "ticker": cands[0]}
        m = [a for a in sec.aaer_matches(nm, A) if a["d"] and a["d"] > dt.date.fromisoformat(f["filed"])]
        row["aaers_after"] = [{"date": a["date"], "aaer": a["aaer"], "url": a["url"]} for a in m]
        try: row["litigation_disclosure"] = litigation(cik, f["filed"])
        except Exception as x: row["litigation_disclosure"] = None; row["lit_error"] = type(x).__name__
        rows.append(row)
        if n % 25 == 0: print(n, nm, row["stock"].get("status"), file=sys.stderr, flush=True)
    OUT.write_text(json.dumps(summarise(rows), indent=1, default=str))
def summarise(rows):
    def grp(sel):
        g = [r for r in rows if sel(r)]; ok = [r for r in g if r["stock"].get("status") == "ok"]
        w = {}
        for k, lab in enumerate(["day 0", "0–1", "0–5", "0–30"]):
            v = [r["stock"]["windows"][k]["adj"] for r in ok if r["stock"]["windows"][k]["adj"] is not None and not r["stock"]["windows"][k]["partial"]]
            w[lab] = {"n": len(v), "median_adj": round(statistics.median(v), 4) if v else None,
                      "share_below_minus10": round(sum(x < -0.10 for x in v) / len(v), 3) if v else None}
        v5 = [r["stock"]["windows"][2]["adj"] for r in ok if r["stock"]["windows"][2]["adj"] is not None]
        edges = [-1, -0.5, -0.25, -0.10, -0.05, 0, 0.05, 0.10, 0.25, 0.5, 99]
        hist = [{"lo": a, "hi": b, "n": sum(a <= x < b for x in v5)} for a, b in zip(edges, edges[1:])]
        st = {}
        for r in g: st[r["stock"].get("status")] = st.get(r["stock"].get("status"), 0) + 1
        ne = [r["stock"]["windows"][2]["adj"] for r in ok if not r.get("earnings_same_day") and r["stock"]["windows"][2]["adj"] is not None]
        return {"n": len(g), "with_prices": len(ok), "median_0_5_adj_no_earnings": round(statistics.median(ne), 4) if ne else None, "n_no_earnings": len(ne), "status_counts": st, "windows": w, "hist_0_5_adj": hist,
                "earnings_same_day": sum(1 for r in ok if r.get("earnings_same_day")),
                "aaer_after": sum(1 for r in g if r["aaers_after"]), "litigation_disclosure": sum(1 for r in g if r.get("litigation_disclosure"))}
    return {"generated": dt.date.today().isoformat(),
            "method": ("All companies with an 8-K Item 4.02 notice filed 2021-2023 (EDGAR full-text search, first notice per company). "
                       "Day 0 from the EDGAR acceptance time (at/after 16:00 ET -> next trading day). Returns from the last close before day 0 "
                       "to the close N trading days after day 0, raw and minus IWM. Prices: Yahoo Finance chart endpoint (unofficial, adjusted "
                       "closes); ticker from the EDGAR display name at filing time, then current SEC tickers; a result is used only if prices "
                       "exist within a week of the notice. SPAC/shell = SIC 6770 or a SPAC-style name (see scripts/backtest.py). AAER = exact "
                       "normalized-name match, release after the notice. Litigation = a later 10-K/10-Q/8-K of the company mentioning a "
                       "'class action complaint' near securities-law and case-caption words, within 2 years: possible, verify."),
            "operating": grp(lambda r: not r["spac"]), "spac": grp(lambda r: r["spac"]), "all": grp(lambda r: True), "rows": rows}
if __name__ == "__main__": main()
