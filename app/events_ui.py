"""Event-study panel (stock reaction around Item 4.02 notices) and class-action lookup, rendered server-side."""
import datetime as dt, html
from rr import prices, sec, courtlistener
e = lambda x: html.escape("" if x is None else str(x))
def pct(v): return "—" if v is None else f"{v*100:+.1f}%"
def chart_svg(series, events, w=1060, h=230):
    if not series: return ""
    first = min((dt.date.fromisoformat(x["day0_calendar"]) for x in events), default=dt.date.fromisoformat(series[-1][0]))
    lo = (first - dt.timedelta(days=200)).isoformat()
    s = [(d, v) for d, v in series if d >= lo]
    if len(s) < 2: return ""
    vs = [v for _, v in s]; mn, mx = min(vs), max(vs); rng = (mx - mn) or 1
    X = lambda i: 40 + i * (w - 60) / (len(s) - 1); Y = lambda v: 12 + (h - 40) * (1 - (v - mn) / rng)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(s))
    idx = {d: i for i, (d, _) in enumerate(s)}
    marks = ""
    for k, x in enumerate(events):
        d = x.get("day0")
        if d in idx:
            xx = X(idx[d]); marks += (f"<line x1={xx:.1f} x2={xx:.1f} y1=8 y2={h-26} stroke='#b42318' stroke-dasharray='4 3'/>"
                                      f"<text x={xx+3:.1f} y={18 + 12*(k%3)} font-size=11 fill='#b42318'>4.02 {e(x['filed'])}</text>")
    ticks = "".join(f"<text x={X(i):.1f} y={h-8} font-size=10 fill='#667085' text-anchor=middle>{e(s[i][0][:7])}</text>"
                    for i in range(0, len(s), max(1, len(s) // 8)))
    return (f"<svg width='100%' viewBox='0 0 {w} {h}' role=img aria-label='price chart'><text x=2 y={Y(mx)+4:.0f} font-size=10 fill='#667085'>{mx:.2f}</text>"
            f"<text x=2 y={Y(mn)+4:.0f} font-size=10 fill='#667085'>{mn:.2f}</text><polyline fill=none stroke='#14213d' stroke-width=1.4 points='{pts}'/>{marks}{ticks}</svg>")
def event_rows(x):
    st = x.get("status")
    head = (f"<b>{e(x['form'])} filed {e(x['filed'])}</b>, accepted {e(x['accepted_et'])}"
            f"{' (after the 4:00 pm close, so day 0 is the next trading day)' if x.get('after_close') else ''} — "
            f"<a href='{e(x['url'])}' target=_blank rel=noopener>notice</a>")
    if st == "no_price_data": return f"<p>{head}<br><span class=muted>No price data (delisted or not covered by the price source).</span></p>"
    if st == "no_price_near_filing": return f"<p>{head}<br><span class=muted>No price data near the filing date (first available price {e(x.get('first_price'))}); not computed.</span></p>"
    tr = "".join(f"<tr><td>{e(w['label'])}</td><td>{e(x['base_date'])} → {e(w['end'])}</td><td class=num>{pct(w['raw'])}</td><td class=num>{pct(w['adj'])}</td>"
                 f"<td>{'<span class=bad>partial: only ' + str(w['days_available']) + ' trading days so far</span>' if w['partial'] else ''}</td></tr>" for w in x["windows"])
    conf = "".join(f"<li>{e(c['form'])} filed {e(c['filed'])}, items {e(c['items'])}{' — <b>earnings release (Item 2.02)</b>' if c['earnings'] else ''} "
                   f"<a href='{e(c['url'])}' target=_blank rel=noopener>open</a></li>" for c in x.get("confounders") or [])
    if "2.02" in (x.get("items") or "").split(","):
        conf = f"<li>The notice itself also contains <b>Item 2.02 (results of operations / earnings)</b>: items {e(x['items'])}</li>" + conf
    conf = (f"<div class=alert><b>Other news the same day:</b> the move may reflect these, not the restatement.<ul>{conf}</ul></div>" if conf
            else "<p class=muted>No other 8-K (besides exhibits) filed between the day before the notice and day 0.</p>")
    return (f"<p>{head}<br><span class=muted>Day 0 = {e(x['day0'])}; base = last close before day 0 ({e(x['base_date'])}, {x['base_close']:.2f}).</span></p>"
            f"<table><tr><th>Window (trading days)</th><th>Dates (close to close)</th><th class=num>Raw</th><th class=num>Minus IWM</th><th></th></tr>{tr}</table>{conf}")
def class_actions_html(name, events):
    out = []
    for x in events[:4]:
        r = courtlistener.search(name, x["filed"])
        st = r.get("status")
        if st == "not_configured": return "<p class=muted>Class-action lookup not configured on this server.</p>"
        if st == "unavailable":
            out.append(f"<li>{e(x['filed'])} notice: <span class=bad>CourtListener unavailable, retry later</span></li>"); continue
        if st != "ok": continue
        cs = "".join(f"<li>{e(c['dateFiled'])} — <a href='{e(c['url'])}' target=_blank rel=noopener>{e(c['caseName'])}</a> ({e(c['court'])}, {e(c['docketNumber'])}; {e(c['suitNature'] or c.get('cause') or '')})</li>" for c in r["cases"])
        out.append(f"<li>{e(x['filed'])} notice, federal dockets filed {e(r['window'][0])} to {e(r['window'][1])}: "
                   + (f"<ul>{cs}</ul>" if cs else "<span class=muted>none found naming the company</span>") + "</li>")
    return ("<ul>" + "".join(out) + "</ul><p class=muted>CourtListener RECAP docket search (caption names the company; securities nature of suit, "
            "'10b-5' or 'Securities Exchange Act'). A docket may concern a different matter; open it. A miss is not proof there is no suit.</p>")
def panel(cik, ticker, name):
    try:
        fl = sec.filings(cik); es = prices.company_events(ticker, fl.get("eightks", []))
    except Exception as x:
        return f"<div class=card><h3 style='margin-top:0'>Stock reaction</h3><p class=muted>Not available right now ({e(type(x).__name__)}).</p></div>"
    evs = es["events"]
    if not evs: return "<div class=card><h3 style='margin-top:0'>Stock reaction</h3><p class=muted>No Item 4.02 notice with an EDGAR acceptance time for this company.</p></div>"
    body = "".join(event_rows(x) for x in evs[:6])
    nop = "" if es["has_prices"] else "<p class=bad>No price data (delisted or not covered by the price source).</p>"
    return (f"<div class=card><h3 style='margin-top:0'>Did the stock fall, and when? (Item 4.02 notices)</h3>{nop}"
            f"{chart_svg(es['series'], evs)}<p class=muted>Daily adjusted closes, {e(es['source'])}; best-effort, may be wrong or missing. "
            f"Returns run from the last close before day 0 to the close N trading days later. 'Minus IWM' subtracts the Russell 2000 ETF's return over the same dates. "
            f"Descriptive only: not a prediction and not a causal estimate.</p>{body}"
            f"<h4>Securities class actions after the notice</h4>{class_actions_html(name, evs)}</div>")
