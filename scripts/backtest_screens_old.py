"""Descriptive 'what happened' table: Item 4.02 filers 2021-2023, screens on numbers AS FIRST REPORTED for the last fiscal
year before the notice, and whether an AAER naming the company appeared after the notice. No accuracy claims."""
import json, pathlib, random, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from datetime import date, datetime
from rr import sec, screens, xbrl
def aaer_date(s):
    for fmt in ("%b. %d, %Y", "%B %d, %Y", "%b %d, %Y"):
        try: return datetime.strptime(s.replace("Sept.", "Sep."), fmt).date()
        except ValueError: pass
    return None
filers = []
for y in (2021, 2022, 2023):
    filers += sec.recent_402(f"{y}-01-01", f"{y}-12-31", pages=10)
first = {}
for f in sorted(filers, key=lambda r: r["filed"]): first.setdefault(f["cik"], f)
tk = {t["cik"]: t["ticker"] for t in sec.tickers()}
A = sec.aaers()
for r in A: r["d"] = aaer_date(r["date"])
allm = []
for cik, f in first.items():
    nm = f["name"].split("  (")[0]
    m = [a for a in sec.aaer_matches(nm, A) if a["d"] and a["d"] > date.fromisoformat(f["filed"])]
    allm.append((cik, f, m))
n_all = len(allm); n_hit = sum(1 for x in allm if x[2])
random.seed(4)
hits = [x for x in allm if x[2]]; rest = [x for x in allm if not x[2] and x[0] in tk]
sample = hits + random.sample(rest, min(len(rest), 14))
rows = []
for cik, f, m in sample:
    row = {"cik": cik, "name": f["name"].split("  (")[0], "ticker": tk.get(cik), "notice_filed": f["filed"], "url": f["url"],
           "aaers_after": [{"date": a["date"], "aaer": a["aaer"], "name": a["name"], "url": a["url"]} for a in m]}
    try:
        cf = sec.companyfacts(cik)
        ends = [e for e in xbrl.fiscal_year_ends(cf, 10) if e < f["filed"]]
        if len(ends) >= 2:
            b = screens.beneish(cf, ends[0], ends[1], which="original")
            fs = screens.dechow_f(cf, ends[0], ends[1], ends[2] if len(ends) > 2 else None, which="original")
            row.update(fy_end=ends[0], m_score=b.get("m_score"), m_status=b.get("status"), m_missing=sorted(set(b["missing"]["current"]+b["missing"]["prior"])), f_missing=fs.get("missing"), f_score=fs.get("f_score"))
        else: row.update(fy_end=None, note="no two pre-notice fiscal years in XBRL")
        k = sorted({(x["filed"], x["accn"]) for c in cf["facts"].get("us-gaap", {}).values() for x in c.get("units", {}).get("USD", []) if x.get("form") == "10-K" and x["filed"] < f["filed"]})
        if k: row["benford_mad"] = screens.benford(cf, k[-1][1]).get("mad")
    except Exception as x: row["note"] = f"no XBRL company facts ({type(x).__name__})"
    rows.append(row); print(row["name"], row.get("m_score"), row.get("f_score"), len(m), file=sys.stderr)
rows.sort(key=lambda r: r["notice_filed"])
out = {"method": (f"All {n_all} companies with an 8-K Item 4.02 notice filed 2021-2023 (EDGAR full-text search, first notice per company). "
                  "Screens use numbers as first reported for the last fiscal year ending before the notice. AAER match = exact normalized "
                  "company-name match against the SEC AAER list, release dated after the notice. Shown: every AAER-matched company plus a "
                  "seeded random sample of 14 others that have tickers. An AAER may concern a different matter than the restatement; read the release."),
       "summary": f"{n_hit} of {n_all} 2021-2023 Item 4.02 filers have a later AAER naming the company (name match; misses possible).",
       "n_filers": n_all, "n_aaer": n_hit, "rows": rows}
pathlib.Path(__file__).resolve().parent.parent.joinpath("data", "backtest.json").write_text(json.dumps(out, indent=1))
print(out["summary"])
