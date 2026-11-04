"""XBRL line items with tag fallbacks, original-vs-restated deltas, and explicit insufficient-data reporting."""
from datetime import date
TAGS = {  # first tag in the list that has a value for the period wins
 "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"],
 "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization", "CostOfServices"],
 "sga": ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense+SellingAndMarketingExpense", "GeneralAndAdministrativeExpense+SellingExpense+MarketingExpense"],
 "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "AccountsReceivableNet"],
 "inventory": ["InventoryNet", "InventoryFinishedGoods"],
 "current_assets": ["AssetsCurrent"],
 "ppe": ["PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
 "depreciation": ["Depreciation", "DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
 "total_assets": ["Assets"],
 "current_liabilities": ["LiabilitiesCurrent"],
 "total_liabilities": ["Liabilities"],
 "ltd": ["LongTermDebtNoncurrent", "LongTermDebt", "ConvertibleNotesPayableNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "ConvertibleLongTermNotesPayable"],
 "debt_current": ["LongTermDebtCurrent", "DebtCurrent", "ConvertibleNotesPayableCurrent"],
 "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
 "st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
 "lt_investments": ["LongTermInvestments", "MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"],
 "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
 "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
 "stock_issued": ["ProceedsFromIssuanceOfCommonStock", "ProceedsFromIssuanceOfCommonStockNetOfIssuanceCosts" ],
 "debt_issued": ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromConvertibleDebt", "ProceedsFromIssuanceOfDebt", "ProceedsFromIssuanceOfSeniorLongTermDebt"],
}
INSTANT = {"receivables", "inventory", "current_assets", "ppe", "total_assets", "current_liabilities", "total_liabilities", "ltd", "debt_current", "cash", "st_investments", "lt_investments"}
def _d(s): return date.fromisoformat(s)
def _facts(cf, tag):
    u = cf["facts"].get("us-gaap", {}).get(tag, {}).get("units", {})
    return u.get("USD", [])
def _period_ok(f, item, annual):
    if item in INSTANT: return "start" not in f
    if "start" not in f: return False
    days = (_d(f["end"]) - _d(f["start"])).days
    return 350 <= days <= 380 if annual else True
def history(cf, tag, item, annual=True):
    """{period_key: [(filed, form, accn, val), ...]} sorted by filed date."""
    out = {}
    for t in tag.split("+"):
        pass
    if "+" in tag:  # sum of components, only where every component exists from the same filing
        parts = [history(cf, t, item, annual) for t in tag.split("+")]
        for k in parts[0]:
            if all(k in p for p in parts[1:]):
                by = [{(a, v[0]) : v[3] for v in p[k] for a in [v[2]]} for p in parts]
                common = set(by[0]).intersection(*by[1:])
                rows = [(fd, next(x[1] for x in parts[0][k] if x[2] == a), a, sum(b[(a, fd)] for b in by)) for a, fd in common]
                if rows: out[k] = sorted(rows)
        return out
    for f in _facts(cf, tag):
        if not _period_ok(f, item, annual): continue
        if not f.get("form", "").startswith(("10-K", "10-Q", "20-F", "8-K")): continue
        k = (f.get("start", ""), f["end"])
        out.setdefault(k, []).append((f["filed"], f["form"], f["accn"], f["val"]))
    for k in out: out[k] = sorted(set(out[k]))
    return out
def annual_value(cf, item, fy_end, which="latest"):
    """Value of a line item for the fiscal year ending fy_end (YYYY-MM-DD, +/-10 days). Returns (val, tag, source) or (None, None, reason)."""
    for tag in TAGS[item]:
        h = history(cf, tag, item, annual=True)
        for (s, e), rows in h.items():
            if abs((_d(e) - _d(fy_end)).days) <= 10:
                r = rows[-1] if which == "latest" else rows[0]
                return r[3], tag, {"filed": r[0], "form": r[1], "accn": r[2]}
    return None, None, "no fact under tags " + ", ".join(TAGS[item])
def fiscal_year_ends(cf, n=6):
    """Most recent fiscal-year end dates, from annual Assets/NetIncome facts in 10-K filings."""
    ends = set()
    for f in _facts(cf, "Assets") + _facts(cf, "NetIncomeLoss"):
        if f.get("fp") == "FY" and f.get("form", "").startswith("10-K") and "start" not in f:
            ends.add(f["end"])
    ends = sorted(ends, reverse=True); keep = []
    for e in ends:
        if all(abs((_d(e) - _d(k)).days) > 300 for k in keep): keep.append(e)
    return keep[:n]
def restatement_deltas(cf, since="2022-01-01", min_abs=0.005):
    """Every (line item, period) whose reported value changed between filings. Deterministic; no model."""
    out = []
    for item, tags in TAGS.items():
        seen = set()
        for tag in tags:
            if "+" in tag: continue
            for annual in (False,):
                for (s, e), rows in history(cf, tag, item, annual).items():
                    if e < since or (item, s, e) in seen: continue
                    vals = [r[3] for r in rows]
                    if len(set(vals)) < 2: continue
                    seen.add((item, s, e)); o, l = rows[0], rows[-1]
                    if o[3] == l[3]:  # changed then changed back; report first change
                        l = next(r for r in rows if r[3] != o[3])
                    base = abs(o[3]) or 1
                    pct = (l[3] - o[3]) / base
                    if abs(pct) < min_abs: continue
                    out.append({"item": item, "tag": tag, "start": s or None, "end": e,
                                "original": o[3], "original_form": o[1], "original_filed": o[0], "original_accn": o[2],
                                "restated": l[3], "restated_form": l[1], "restated_filed": l[0], "restated_accn": l[2],
                                "change": l[3] - o[3], "pct_change": round(pct, 4)})
    return sorted(out, key=lambda r: (r["restated_filed"], r["end"]), reverse=True)
