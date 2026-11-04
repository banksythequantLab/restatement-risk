"""Deterministic reference implementations. These approximate published academic screens on XBRL data
(Beneish 1999 8-variable M-score; Dechow et al. 2011 F-score model 1; Benford first-digit). They are NOT the SEC's
non-public Accounting Quality Model, and a score is a screen, not a prediction."""
import math
from .xbrl import annual_value, fiscal_year_ends, _facts
def _vals(cf, end, items, which="latest"):
    v, src, missing = {}, {}, []
    for it in items:
        val, tag, s = annual_value(cf, it, end, which)
        if val is None: missing.append(it)
        else: v[it] = val; src[it] = tag
    return v, src, missing
M_ITEMS = ["revenue", "cogs", "sga", "receivables", "current_assets", "ppe", "depreciation", "total_assets", "current_liabilities", "ltd", "net_income", "cfo"]
def beneish(cf, t_end, p_end, which="latest"):
    t, ts, tm = _vals(cf, t_end, M_ITEMS, which); p, ps, pm = _vals(cf, p_end, M_ITEMS, which)
    imputed = []
    for d in (t, p):  # missing long-term debt is common for debt-free filers; treat as 0 and say so
        if "ltd" not in d: d["ltd"] = 0.0
    if "ltd" in tm or "ltd" in pm: imputed.append("ltd=0 (no long-term debt tag)")
    tm = [m for m in tm if m != "ltd"]; pm = [m for m in pm if m != "ltd"]
    hard = [m for m in set(tm + pm) if m not in ("sga", "depreciation")]
    res = {"model": "Beneish 8-variable M-score", "year_end": t_end, "prior_year_end": p_end, "tags": ts,
           "missing": {"current": tm, "prior": pm}, "imputed": imputed}
    if hard: res.update(status="insufficient_data", m_score=None); return res
    r = {}
    r["DSRI"] = (t["receivables"] / t["revenue"]) / (p["receivables"] / p["revenue"])
    gm = lambda d: (d["revenue"] - d["cogs"]) / d["revenue"]
    r["GMI"] = gm(p) / gm(t)
    aq = lambda d: 1 - (d["current_assets"] + d["ppe"]) / d["total_assets"]
    r["AQI"] = aq(t) / aq(p) if aq(p) else 1.0
    r["SGI"] = t["revenue"] / p["revenue"]
    if "depreciation" in t and "depreciation" in p:
        dep = lambda d: d["depreciation"] / (d["depreciation"] + d["ppe"])
        r["DEPI"] = dep(p) / dep(t)
    else: r["DEPI"] = 1.0; imputed.append("DEPI=1 (depreciation missing)")
    if "sga" in t and "sga" in p:
        r["SGAI"] = (t["sga"] / t["revenue"]) / (p["sga"] / p["revenue"])
    else: r["SGAI"] = 1.0; imputed.append("SGAI=1 (SG&A missing)")
    lev = lambda d: (d["current_liabilities"] + d["ltd"]) / d["total_assets"]
    r["LVGI"] = lev(t) / lev(p)
    r["TATA"] = (t["net_income"] - t["cfo"]) / t["total_assets"]
    m = (-4.84 + .920 * r["DSRI"] + .528 * r["GMI"] + .404 * r["AQI"] + .892 * r["SGI"] + .115 * r["DEPI"]
         - .172 * r["SGAI"] + 4.679 * r["TATA"] - .327 * r["LVGI"])
    res.update(status="ok" if not imputed else "ok_with_imputation", ratios={k: round(v, 4) for k, v in r.items()},
               m_score=round(m, 3), flag=m > -1.78, threshold=-1.78, imputed=imputed)
    return res
F_ITEMS = ["current_assets", "cash", "current_liabilities", "total_assets", "total_liabilities", "receivables", "revenue", "net_income", "ppe"]
def dechow_f(cf, t_end, p_end, pp_end, which="latest"):
    """F-score model 1. Approximations on XBRL: missing ST/LT investments, current debt, inventory = 0 (listed)."""
    opt = ["st_investments", "lt_investments", "debt_current", "ltd", "inventory", "stock_issued", "debt_issued"]
    t, _, tm = _vals(cf, t_end, F_ITEMS + opt, which); p, _, pm = _vals(cf, p_end, F_ITEMS + opt, which)
    pp, _, ppm = _vals(cf, pp_end, ["total_assets", "net_income"], which) if pp_end else ({}, {}, ["total_assets", "net_income"])
    hard = sorted(set(m for m in tm + pm if m not in opt) | set("prior2_" + m for m in ppm))
    res = {"model": "Dechow et al. (2011) F-score, model 1", "year_end": t_end, "missing": hard,
           "imputed_zero": sorted(set(m for m in tm + pm if m in opt))}
    if hard: res.update(status="insufficient_data", f_score=None); return res
    for d in (t, p):
        for o in opt: d.setdefault(o, 0.0)
    def parts(d):
        wc = (d["current_assets"] - d["cash"] - d["st_investments"]) - (d["current_liabilities"] - d["debt_current"])
        nco = (d["total_assets"] - d["current_assets"] - d["lt_investments"]) - (d["total_liabilities"] - d["current_liabilities"] - d["ltd"])
        fin = (d["st_investments"] + d["lt_investments"]) - (d["ltd"] + d["debt_current"])
        return wc, nco, fin
    avg = (t["total_assets"] + p["total_assets"]) / 2; avgp = (p["total_assets"] + pp["total_assets"]) / 2
    a, b = parts(t), parts(p)
    v = {"rsst_acc": sum(x - y for x, y in zip(a, b)) / avg,
         "ch_rec": (t["receivables"] - p["receivables"]) / avg,
         "ch_inv": (t["inventory"] - p["inventory"]) / avg,
         "soft_assets": (t["total_assets"] - t["ppe"] - t["cash"]) / t["total_assets"]}
    cs_t = t["revenue"] - (t["receivables"] - p["receivables"])
    # prior-year cash sales needs prior2 receivables; use reported revenue for prior year if unavailable (listed)
    pr2, _, _ = _vals(cf, pp_end, ["receivables"], which)
    cs_p = p["revenue"] - (p["receivables"] - pr2["receivables"]) if "receivables" in pr2 else p["revenue"]
    v["ch_cs"] = (cs_t - cs_p) / cs_p
    v["ch_roa"] = t["net_income"] / avg - p["net_income"] / avgp
    v["issue"] = 1.0 if (t["stock_issued"] > 0 or t["debt_issued"] > 0) else 0.0
    x = (-7.893 + .790 * v["rsst_acc"] + 2.518 * v["ch_rec"] + 1.191 * v["ch_inv"] + 1.979 * v["soft_assets"]
         + .171 * v["ch_cs"] - .932 * v["ch_roa"] + 1.029 * v["issue"])
    prob = math.exp(x) / (1 + math.exp(x)); f = prob / 0.0037
    res.update(status="ok", variables={k: round(val, 4) for k, val in v.items()}, f_score=round(f, 3),
               flag=f >= 1.0, threshold=1.0)
    return res
def benford(cf, accn=None):
    """First-digit test over all distinct USD values reported in one filing (default: latest 10-K)."""
    facts = [(tag, f) for tag, c in cf["facts"].get("us-gaap", {}).items() for f in c.get("units", {}).get("USD", [])]
    if accn is None:
        ks = sorted({(f["filed"], f["accn"]) for _, f in facts if f.get("form") in ("10-K", "10-K/A")})
        if not ks: return {"status": "insufficient_data"}
        accn = ks[-1][1]
    vals = {(tag, f.get("start"), f["end"]): abs(f["val"]) for tag, f in facts if f["accn"] == accn and abs(f["val"]) >= 10}
    digits = [int(str(int(v))[0]) for v in vals.values()]
    n = len(digits)
    if n < 100: return {"status": "insufficient_data", "n": n, "accn": accn}
    exp = [math.log10(1 + 1 / d) for d in range(1, 10)]; obs = [digits.count(d) / n for d in range(1, 10)]
    mad = sum(abs(o - e) for o, e in zip(obs, exp)) / 9
    chi2 = sum(n * (o - e) ** 2 / e for o, e in zip(obs, exp))
    conf = "close" if mad < .006 else "acceptable" if mad < .012 else "marginal" if mad < .015 else "nonconformity"
    return {"status": "ok", "accn": accn, "n": n, "mad": round(mad, 5), "chi2": round(chi2, 2),
            "conformity_nigrini": conf, "observed": [round(o, 4) for o in obs]}
def run_all(cf):
    ends = fiscal_year_ends(cf, 4)
    if len(ends) < 2: return {"status": "insufficient_data", "fiscal_year_ends": ends}
    out = {"fiscal_year_ends": ends,
           "beneish": beneish(cf, ends[0], ends[1]),
           "dechow_f": dechow_f(cf, ends[0], ends[1], ends[2] if len(ends) > 2 else None),
           "benford": benford(cf)}
    if len(ends) > 1:  # same screen on originally-reported numbers, to show what the restatement did to the screen
        out["beneish_original_numbers"] = beneish(cf, ends[0], ends[1], which="original")
    return out
