"""Web app: holds the inference key (env) but not the docker socket. Server-rendered HTML, no JS frameworks."""
import html, json, os, pathlib, re, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from rr import agent, sec
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
ROOT = pathlib.Path(os.getenv("RR_ROOT", "/var/lib/rr")); STORE = ROOT / "results"; STORE.mkdir(parents=True, exist_ok=True)
BACKTEST = pathlib.Path(__file__).resolve().parent.parent / "data" / "backtest.json"
POOL = ThreadPoolExecutor(max_workers=2); JOBS = {}; LOCK = threading.Lock()
CIK_RE = re.compile(r"\s*\(CIK.*")
def clean_name(n): return CIK_RE.sub("", n or "")
TICK = re.compile(r"^[A-Z0-9.\-]{1,10}$")
e = lambda x: html.escape("" if x is None else str(x))
def money(v):
    if v is None: return "—"
    a = abs(v); s = f"{a/1e9:,.2f}B" if a >= 1e9 else f"{a/1e6:,.2f}M" if a >= 1e6 else f"{a:,.0f}"
    return ("−$" if v < 0 else "$") + s
def num(v, d=3):
    return "—" if v is None else (f"{v:.{d}f}" if isinstance(v, (int, float)) else e(v))
CSS = """body{font:15px/1.45 system-ui,sans-serif;margin:0;color:#1d2330;background:#f6f7f9}
header{background:#14213d;color:#fff;padding:14px 28px;display:flex;gap:24px;align-items:center}
header a{color:#fff;text-decoration:none}header b{font-size:18px}main{max-width:1180px;margin:0 auto;padding:20px 28px}
.card{background:#fff;border:1px solid #dde1e7;border-radius:8px;padding:16px 20px;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}td,th{border-bottom:1px solid #eceef2;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f1f3f6}.num{text-align:right;font-variant-numeric:tabular-nums}.ok{color:#1a7f37}.bad{color:#b42318;font-weight:600}
.muted{color:#667085;font-size:13px}pre{background:#0f172a;color:#e2e8f0;padding:10px;border-radius:6px;overflow:auto;max-height:420px;font-size:12.5px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:#eef2ff;color:#3538cd}
.alert{background:#fff4e5;border:2px solid #f79009;padding:10px 14px;border-radius:6px;margin:8px 0}
.net{background:#fef3f2;border:2px solid #d92d20}input,textarea,button{font:inherit;padding:7px 10px;border:1px solid #c9ced6;border-radius:6px}
button{background:#14213d;color:#fff;cursor:pointer}details{margin:6px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.caveat{border-left:4px solid #14213d;padding:6px 12px;background:#f1f3f6;font-size:13.5px}"""
def page(title, body, refresh=False):
    r = '<meta http-equiv="refresh" content="3">' if refresh else ""
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(title)}</title>{r}
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>
<header><b><a href="/">Restatement Risk</a></b><a href="/">Search</a><a href="/ask">Ask</a><a href="/backtest">What happened (2021–23)</a><a href="/about">How it works</a></header>
<main>{body}</main></body></html>""")
CAVEAT = """<div class="caveat">The SEC does not "audit" companies. Scrutiny comes as Corp Fin filing review (comment letters) and, rarely,
an Enforcement inquiry. M-score (Beneish 1999) and F-score (Dechow et al. 2011) are published academic screens approximated on
SEC XBRL data — not the SEC's non-public Accounting Quality Model. A screen is not a prediction.</div>"""
def start(kind, key, fn):
    jid = uuid.uuid4().hex[:12]
    with LOCK: JOBS[jid] = {"kind": kind, "key": key, "status": "running", "progress": {}, "started": time.time()}
    def work():
        try:
            out = fn(lambda p: JOBS[jid].__setitem__("progress", p))
            (STORE / f"{jid}.json").write_text(json.dumps({"kind": kind, "key": key, "out": out, "at": time.time()}, default=str))
            JOBS[jid]["status"] = "done"
        except Exception as x:
            JOBS[jid].update(status="failed", error=f"{type(x).__name__}: {str(x)[:300]}")
    POOL.submit(work); return jid
def latest_report(ticker, max_age=86400):
    best = None
    for p in STORE.glob("*.json"):
        if time.time() - p.stat().st_mtime > max_age: continue
        d = json.loads(p.read_text())
        if d["kind"] == "report" and d["key"] == ticker and (not best or d["at"] > best[1]["at"]): best = (p.stem, d)
    return best
@app.get("/", response_class=HTMLResponse)
def home():
    try: rows = sec.recent_402("2025-01-01")[:60]; err = ""
    except Exception as x: rows, err = [], f"EDGAR full-text search unavailable right now ({type(x).__name__})."
    tk = {t["cik"]: t["ticker"] for t in sec.tickers()}
    trs = "".join(f"<tr><td>{e(r['filed'])}</td><td>{e(clean_name(r['name']))}</td><td>{e(r['form'])}</td><td>{e(', '.join(r['items'] or []))}</td>"
                  f"<td><a href='{e(r['url'])}' target=_blank rel=noopener>filing</a></td><td>"
                  + (f"<a href='/c/{e(tk[r['cik']])}'>analyse {e(tk[r['cik']])}</a>" if r['cik'] in tk else "<span class=muted>no ticker</span>") + "</td></tr>" for r in rows)
    return page("Restatement Risk", f"""<div class="card"><h2 style="margin-top:0">Who restated, what changed, and has the SEC said anything?</h2>
<form method="post" action="/go"><input name="t" placeholder="Ticker, e.g. GPRO" autofocus> <button>Analyse</button></form>
<p class="muted">Public SEC data only: XBRL company facts, EDGAR filings, comment-letter correspondence, AAER list.</p>{CAVEAT}</div>
<div class="card"><h3 style="margin-top:0">Recent Item 4.02 non-reliance notices (since 2025-01-01, EDGAR full-text search)</h3>
<p class="muted">{e(err)}</p><table><tr><th>Filed</th><th>Company</th><th>Form</th><th>Items</th><th></th><th></th></tr>{trs}</table></div>""")
@app.post("/go")
def go(t: str = Form(...)):
    t = t.strip().upper()
    if not TICK.match(t): raise HTTPException(400, "bad ticker")
    return RedirectResponse(f"/c/{t}", 303)
@app.get("/c/{ticker}", response_class=HTMLResponse)
def company(ticker: str, fresh: int = 0):
    t = ticker.upper()
    if not TICK.match(t): raise HTTPException(400)
    try: sec.lookup(t)
    except KeyError: return page("Not found", f"<div class=card>No SEC registrant with ticker {e(t)}.</div>")
    if not fresh and (r := latest_report(t)): return RedirectResponse(f"/r/{r[0]}", 303)
    with LOCK: running = next((j for j, v in JOBS.items() if v["kind"] == "report" and v["key"] == t and v["status"] == "running"), None)
    jid = running or start("report", t, lambda log: agent.analyse(t, log))
    return RedirectResponse(f"/job/{jid}", 303)
def attempts_html(attempts):
    out = []
    for a in attempts or []:
        cls = "card"
        head = f"Attempt {a['attempt']}: <b>{e(a.get('status'))}</b>"
        if a.get("status") == "no_code":
            out.append(f"<div class=card>{head} — model replied without code; asked again.<details><summary>reply</summary><pre>{e(a.get('model_reply'))}</pre></details></div>"); continue
        alert = ""
        if a.get("network_blocked"):
            nl = a.get("netlog") or []
            ev = "".join(f"<li><code>{e(x.get('event'))}</code> {e(x.get('target'))}</li>" for x in nl[:8])
            src = "recorded inside the sandbox by an audit hook" if nl else "seen in the script's output"
            alert = (f"<div class='alert net'><b>Contained: the model's code tried to reach the network and the sandbox blocked it</b> "
                     f"(container started with <code>--network none</code>; attempt {src}). It was never told to use the network.<ul>{ev}</ul></div>")
        elif a.get("timed_out"): alert = "<div class=alert><b>Contained: time limit hit</b> — container killed and removed.</div>"
        elif a.get("oom_killed"): alert = "<div class=alert><b>Contained: memory limit (512 MB) hit</b> — container killed.</div>"
        out.append(f"""<div class="{cls}">{head} &middot; exit {e(a.get('exit_code'))} &middot; {e(a.get('seconds'))}s in sandbox &middot;
container <code>{e(a.get('container'))}</code> {'removed' if a.get('destroyed') else '<span class=bad>NOT removed</span>'}{alert}
<details><summary>code the model wrote ({len(a.get('code') or '')} chars)</summary><pre>{e(a.get('code'))}</pre></details>
<details {'open' if a.get('status')!='ok' else ''}><summary>stdout / stderr</summary><pre>{e((a.get('stdout') or '')[-4000:])}\n{e((a.get('stderr') or '')[-4000:])}</pre></details></div>""")
    return "".join(out)
@app.get("/job/{jid}", response_class=HTMLResponse)
def job(jid: str):
    j = JOBS.get(jid)
    if not j:
        if (STORE / f"{jid}.json").exists(): return RedirectResponse(f"/r/{jid}", 303)
        raise HTTPException(404)
    if j["status"] == "done": return RedirectResponse(f"/r/{jid}", 303)
    if j["status"] == "failed": return page("Failed", f"<div class=card><b>Failed:</b> {e(j['error'])}</div>")
    p = j["progress"] or {}; el = int(time.time() - j["started"])
    return page("Working…", f"""<div class=card><h3>Working on {e(j['key'])} — {el}s</h3><p>Stage: {e(p.get('stage','fetching SEC data'))}</p>
<p class=muted>The model writes Python; it runs in a throwaway, network-less container on this Vultr VM.</p></div>{attempts_html(p.get('attempts'))}""", refresh=True)
def benford_svg(obs):
    import math
    exp = [math.log10(1 + 1 / d) for d in range(1, 10)]; W, H, bw = 420, 170, 40; mx = max(max(obs), max(exp)) * 1.1
    bars = "".join(f"<rect x='{20+i*bw+6}' y='{H-20-o/mx*(H-30)}' width='{bw-12}' height='{o/mx*(H-30)}' fill='#5b7bd5'/>"
                   f"<text x='{20+i*bw+bw/2}' y='{H-5}' font-size='11' text-anchor='middle'>{i+1}</text>" for i, o in enumerate(obs))
    line = " ".join(f"{20+i*bw+bw/2},{H-20-x/mx*(H-30)}" for i, x in enumerate(exp))
    return f"<svg width='{W}' height='{H}'>{bars}<polyline points='{line}' fill='none' stroke='#d92d20' stroke-width='2'/></svg><div class=muted>bars: observed first digits; red line: Benford expected</div>"
def report_html(o):
    ref = o["reference"]; b, f, bf = ref.get("beneish", {}), ref.get("dechow_f", {}), ref.get("benford", {})
    rows = "".join(f"<tr><td>{e(d['item'])}</td><td class=muted>{e(d['tag'])}</td><td>{e(d['start'] or '')} → {e(d['end'])}</td>"
        f"<td class=num>{money(d['original'])}<br><span class=muted>{e(d['original_form'])} {e(d['original_filed'])}</span></td>"
        f"<td class=num>{money(d['restated'])}<br><span class=muted>{e(d['restated_form'])} {e(d['restated_filed'])}</span></td>"
        f"<td class=num>{d['pct_change']*100:+.1f}%</td></tr>" for d in o["reference_deltas"][:60])
    def link(acc): return f"https://www.sec.gov/Archives/edgar/data/{o['cik']}/{acc.replace('-','')}/"
    rf = "".join(f"<tr><td>{e(x['filed'])}</td><td>{e(x['form'])}</td><td>{e(x['items'])}</td><td><a href='{e(x['url'])}' target=_blank rel=noopener>open</a></td></tr>" for x in o["restatement_filings"][:30])
    cl = "".join(f"<tr><td>{e(x['filed'])}</td><td>{e(x['form'])}</td><td><a href='{e(x['url'])}' target=_blank rel=noopener>open</a></td></tr>" for x in o["comment_letters"][:30]) or "<tr><td colspan=3 class=muted>None on EDGAR for this company.</td></tr>"
    aa = "".join(f"<li>{e(x['date'])} — {e(x['name'])} — AAER-{e(x['aaer'])} <a href='{e(x['url'])}' target=_blank rel=noopener>release</a></li>" for x in o["aaer_name_matches"]) or "<li class=muted>No AAER whose respondent name matches this company (exact normalized name; individuals charged alone would not match).</li>"
    xc = "".join(f"<tr><td>{e(x['metric'])}</td><td class=num>{num(x['reference'],4)}</td><td class=num>{num(x['model'],4)}</td><td class={'ok' if x['match'] else 'bad'}>{'match' if x['match'] else 'MISMATCH'}</td></tr>" for x in o["crosscheck"])
    mism = len(o.get("crosscheck_mismatches") or [])
    miss = []
    if b.get("status") == "insufficient_data": miss.append(f"M-score not computed — missing: {', '.join(set(b['missing']['current']+b['missing']['prior']))}")
    miss += [f"M-score imputation: {x}" for x in b.get("imputed") or []]
    if f.get("status") == "insufficient_data": miss.append(f"F-score not computed — missing: {', '.join(f.get('missing', []))}")
    if f.get("imputed_zero"): miss.append("F-score inputs treated as 0 (no XBRL fact): " + ", ".join(f["imputed_zero"]))
    expl = e(o["explanation"]).replace("\n", "<br>")
    expl = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", expl)
    return f"""<h2>{e(o['name'])} <span class=muted>({e(o['ticker'])}, CIK {e(o['cik'])}, {e(o.get('sic'))})</span></h2>
<p><a href="/c/{e(o['ticker'])}?fresh=1">re-run</a> &middot; <a href="/ask?t={e(o['ticker'])}">ask a question about this company</a></p>
<div class=card><h3 style="margin-top:0">Explanation (model, from the reference numbers)</h3><div>{expl}</div>{fixes_html(o)}{CAVEAT}</div>
<div class=grid><div class=card><h3 style="margin-top:0">Screens (fiscal year ending {e(ref['fiscal_year_ends'][0])})</h3>
<p>Beneish M-score: <b>{num(b.get('m_score'))}</b> <span class=muted>(flag above −1.78; {e(b.get('status'))})</span><br>
Same screen on numbers as first reported: {num((ref.get('beneish_original_numbers') or {}).get('m_score'))}<br>
Dechow F-score: <b>{num(f.get('f_score'))}</b> <span class=muted>(flag at ≥ 1.0; {e(f.get('status'))})</span><br>
Benford MAD: <b>{num(bf.get('mad'),4)}</b> <span class=muted>n={e(bf.get('n'))}, Nigrini: {e(bf.get('conformity_nigrini'))}</span></p>
{benford_svg(bf['observed']) if bf.get('observed') else ''}
<h4>Missing-data notes</h4><ul>{''.join(f'<li>{e(m)}</li>' for m in miss) or '<li class=muted>none</li>'}</ul></div>
<div class=card><h3 style="margin-top:0">Model's sandboxed calculation vs reference code</h3>
<p>{'<span class=ok>All checks match.</span>' if not mism else f'<span class=bad>{mism} mismatch(es).</span> The reference numbers are used everywhere on this page.'}</p>
<table><tr><th>Metric</th><th>Reference</th><th>Model</th><th></th></tr>{xc}</table></div></div>
<div class=card><h3 style="margin-top:0">What changed between filings ({o['reference_delta_count']} line-item/periods, since 2022)</h3>
<p class=muted>Original = earliest filed value for that period; restated = latest. Changes can be restatement, reclassification or recast — read the filings.</p>
<table><tr><th>Item</th><th>XBRL tag</th><th>Period</th><th class=num>Original</th><th class=num>Latest</th><th class=num>Change</th></tr>{rows}</table></div>
<div class=grid><div class=card><h3 style="margin-top:0">Non-reliance (8-K 4.02) and amended filings</h3><table><tr><th>Filed</th><th>Form</th><th>Items</th><th></th></tr>{rf}</table></div>
<div class=card><h3 style="margin-top:0">SEC comment-letter correspondence (CORRESP / UPLOAD)</h3><p class=muted>Shows a filing review happened; content not summarized here.</p><table>{cl}</table>
<h3>AAER (enforcement release) name match</h3><ul>{aa}</ul></div></div>
<h3>Sandbox attempt log</h3>{attempts_html(o['attempts'])}"""
def fixes_html(o):
    f = o.get("name_fixes") or []
    return f"<div class=alert>Post-check corrected a wrong company name in the model's text: {e(', '.join(f))} → {e(o['name'])}.</div>" if f else ""
def ask_html(o):
    r = o.get("result") or {}; tb = r.get("table") or []
    t = ""
    if tb and isinstance(tb, list) and isinstance(tb[0], dict):
        cols = list(tb[0])[:10]
        t = "<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in cols) + "</tr>" + "".join("<tr>" + "".join(f"<td>{e(row.get(c))}</td>" for c in cols) + "</tr>" for row in tb[:80]) + "</table>"
    net = any(a.get("network_blocked") or a.get("network_attempted") for a in o["attempts"])
    expl = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(o["explanation"]).replace("\n", "<br>"))
    return f"""<h2>{e(o['name'])} ({e(o['ticker'])})</h2><div class=card><b>Question:</b> {e(o['question'])}</div>
{"<div class='alert net'><b>Containment event in this run:</b> the model's code tried to use the network; the sandbox has none. See the attempt log.</div>" if net else ""}
<div class=card><h3 style="margin-top:0">Answer</h3><p>{e(r.get('answer'))}</p>{t}<ul>{''.join(f'<li>{e(n)}</li>' for n in (r.get('notes') or []))}</ul>
<h4>Explanation</h4><div>{expl}</div>{fixes_html(o)}{CAVEAT}</div><h3>Attempt log</h3>{attempts_html(o['attempts'])}"""
@app.get("/r/{rid}", response_class=HTMLResponse)
def result(rid: str):
    if not re.fullmatch(r"[0-9a-f]{12}", rid) or not (STORE / f"{rid}.json").exists(): raise HTTPException(404)
    d = json.loads((STORE / f"{rid}.json").read_text()); o = d["out"]
    if o.get("error"): return page("No report", f"<div class=card>{e(o['name'])}: {e(o['error'])}</div>")
    return page(o["name"], report_html(o) if d["kind"] == "report" else ask_html(o))
@app.get("/ask", response_class=HTMLResponse)
def ask_form(t: str = ""):
    past = sorted(STORE.glob("*.json"), key=lambda p: -p.stat().st_mtime)[:200]
    items = []
    for p in past:
        d = json.loads(p.read_text())
        if d["kind"] == "ask":
            net = any(a.get("network_blocked") for a in d["out"]["attempts"])
            items.append(f"<li><a href='/r/{p.stem}'>{e(d['out']['ticker'])}: {e(d['out']['question'])}</a> {'<span class=badge>network blocked</span>' if net else ''}</li>")
    return page("Ask", f"""<div class=card><h2 style="margin-top:0">Ask an analysis question</h2>
<form method=post action=/ask><input name=t placeholder=Ticker value="{e(t)}" required> <br><br>
<textarea name=q rows=3 cols=90 placeholder="e.g. Which quarterly line items moved the most in the 2026 amendments, in dollars?" required></textarea><br><br><button>Run</button></form>
<p class=muted>The model gets this company's SEC XBRL facts and filing index as read-only files and writes Python; it runs in a throwaway container with no network, 512 MB, 1 CPU, 30 s.</p></div>
<div class=card><h3 style="margin-top:0">Previous questions</h3><ul>{''.join(items[:40]) or '<li class=muted>none yet</li>'}</ul></div>""")
@app.post("/ask")
def ask_post(t: str = Form(...), q: str = Form(...)):
    t = t.strip().upper(); q = q.strip()[:800]
    if not TICK.match(t) or not q: raise HTTPException(400)
    try: sec.lookup(t)
    except KeyError: raise HTTPException(404, "unknown ticker")
    return RedirectResponse(f"/job/{start('ask', t, lambda log: agent.ask(t, q, log))}", 303)
@app.get("/backtest", response_class=HTMLResponse)
def backtest():
    if not BACKTEST.exists(): return page("Backtest", "<div class=card>Not generated yet.</div>")
    d = json.loads(BACKTEST.read_text())
    rows = "".join(f"<tr><td>{e(r['notice_filed'])}</td><td>{e(r['name'])}</td><td>{e(r.get('ticker') or '')}</td><td>{e(r.get('fy_end'))}</td>"
        f"<td class=num>{num(r.get('m_score'))}</td><td class=num>{num(r.get('f_score'))}</td><td class=num>{num(r.get('benford_mad'),4)}</td>"
        f"<td>{'; '.join(e(x['date'])+' AAER-'+e(x['aaer']) for x in r.get('aaers_after') or []) or '—'}</td><td><a href='{e(r['url'])}' target=_blank rel=noopener>4.02</a></td></tr>" for r in d["rows"])
    return page("What happened", f"""<div class=card><h2 style="margin-top:0">What happened next: Item 4.02 filers, 2021–2023</h2>
<p>{e(d['method'])}</p><p><b>{e(d['summary'])}</b></p>{CAVEAT}<p class=muted>This is a small, descriptive sample. It is not a validation and supports no accuracy claim.</p>
<table><tr><th>4.02 filed</th><th>Company</th><th>Ticker</th><th>Screened FY end</th><th class=num>M-score</th><th class=num>F-score</th><th class=num>Benford MAD</th><th>Later AAER (name match)</th><th></th></tr>{rows}</table></div>""")
@app.get("/about", response_class=HTMLResponse)
def about():
    return page("How it works", f"""<div class=card><h2 style="margin-top:0">How it works</h2><ol>
<li>The app fetches public SEC data (XBRL company facts, filing index, comment-letter index, AAER list) with a declared User-Agent, under SEC's 10 requests/second limit, and caches it.</li>
<li>For a report or a question, the model (Vultr Serverless Inference, <code>glm-5.3-flash</code>) writes a Python script.</li>
<li>An internal runner service — the only component with the Docker socket, holding no keys — runs it in a fresh container: no network, data mounted read-only, 512 MB, 1 CPU, 64 processes, 30 s, no capabilities, non-root, empty environment. The container is removed after each attempt.</li>
<li>Errors go back to the model, up to 3 attempts. Every attempt is shown.</li>
<li>For reports, the model's numbers are checked against fixed reference code. Mismatches are shown; reference numbers are used.</li>
<li>The model explains the result with the caveats below.</li></ol>{CAVEAT}</div>""")
@app.get("/health")
def health(): return {"ok": True}
