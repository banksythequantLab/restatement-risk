"""Pattern A loop: fetch (outside sandbox) -> model writes Python -> sandbox runs it -> retry on error (max 3)
-> cross-check against deterministic reference -> model explains with caveats."""
import json, pathlib, re, sys, time
from . import sec, xbrl, screens, llm, sandbox
import os
RUNS = pathlib.Path(os.getenv("RR_ROOT", pathlib.Path(__file__).resolve().parent.parent)) / "runs"
TASK = """You are a forensic-accounting analyst writing ONE Python 3.12 script (stdlib + numpy + pandas only).
Data (read-only) is in /data:
- /data/companyfacts.json : SEC XBRL companyfacts for {name} (CIK {cik}). Facts at facts['us-gaap'][TAG]['units']['USD'],
  each fact has val, end, optional start (duration facts), fy, fp, form, filed, accn.
- /data/filings.json : this company's 8-K Item 4.02 notices, 10-K/A, 10-Q/A, CORRESP, UPLOAD filings.
- /data/tag_map.json : line item -> ordered list of fallback XBRL tags (use the first tag that has a value for the period;
  'A+B' means sum of tags A and B from the same filing). Instant items: {instant}.
Write results to /out/result.json. Fiscal years to analyse: current year ending {t}, prior {p}, prior-2 {pp}
(annual facts: duration 350-380 days, or instant facts, with end date within 10 days; use the LATEST filed value).

Compute:
1. "deltas": every line item in tag_map (single tags only, any duration incl. quarters, period end >= 2022-01-01)
   whose value differs between filings for the same (start,end). For each: item, tag, start, end, original (earliest filed
   value), original_form, restated (latest filed value), restated_form, restated_filed, pct_change=(restated-original)/|original|.
   Skip |pct_change| < 0.005. Count per item is fine to be large.
2. "beneish": 8-variable M-score (Beneish 1999) for the current year vs prior:
   DSRI=(rec/rev)_t/(rec/rev)_p; GMI=gm_p/gm_t with gm=(rev-cogs)/rev; AQI=(1-(ca+ppe)/ta)_t/(same)_p;
   SGI=rev_t/rev_p; DEPI=(dep/(dep+ppe))_p/(same)_t; SGAI=(sga/rev)_t/(sga/rev)_p; LVGI=((cl+ltd)/ta)_t/(same)_p;
   TATA=(ni-cfo)_t/ta_t. M=-4.84+.920DSRI+.528GMI+.404AQI+.892SGI+.115DEPI-.172SGAI+4.679TATA-.327LVGI.
   If ltd missing use 0; if depreciation or sga missing set that index to 1 and list it in "imputed".
   If any other input is missing, set m_score null and list missing inputs. Include the 8 ratios.
3. "dechow_f": F-score model 1 (Dechow et al. 2011). Missing st_investments, lt_investments, debt_current, ltd,
   inventory, stock_issued, debt_issued are 0. avgTA=(ta_t+ta_p)/2.
   WC=(ca-cash-sti)-(cl-debt_current); NCO=(ta-ca-lti)-(tl-cl-ltd); FIN=(sti+lti)-(ltd+debt_current);
   rsst_acc=(dWC+dNCO+dFIN)/avgTA; ch_rec=d(rec)/avgTA; ch_inv=d(inv)/avgTA; soft_assets=(ta-ppe-cash)/ta_t;
   ch_cs=(cs_t-cs_p)/cs_p with cs=rev-d(rec) (for cs_p use prior-2 receivables, or rev_p if missing);
   ch_roa=ni_t/avgTA - ni_p/((ta_p+ta_pp)/2); issue=1 if stock_issued_t>0 or debt_issued_t>0.
   x=-7.893+.790rsst_acc+2.518ch_rec+1.191ch_inv+1.979soft_assets+.171ch_cs-.932ch_roa+1.029issue;
   F=(e^x/(1+e^x))/0.0037. Include the variables.
4. "benford": first-digit test over distinct |val|>=10 USD values (unique by tag,start,end) in the latest 10-K or 10-K/A
   accession (by filed date): n, mad (mean absolute deviation of 9 digit proportions vs log10(1+1/d)).
5. "restatement_filings": list from filings.json of 8-K 4.02 / 10-K/A / 10-Q/A with dates, and count of CORRESP/UPLOAD
   filed after the earliest 4.02 notice.
Be defensive (missing keys, zero denominators). Reply with exactly one ```python block and nothing else."""
FIX = """The script failed. Exit code {rc}{extra}.
stdout/stderr tail:
{err}
Fix it and reply with the full corrected script in one ```python block."""
EXPLAIN = """You are explaining results to a New York litigator. Be plain and short (<=250 words). Rules:
- The SEC does not "audit" companies; scrutiny comes as Corp Fin filing review / comment letters and, rarely, an
  Enforcement inquiry. Say this once.
- M-score and F-score are published academic screens approximated on XBRL data, not the SEC's non-public Accounting
  Quality Model; a score is a screen, not a prediction. Note any imputed or missing inputs.
- Don't characterize intent. Changes between filings can be restatement, reclassification or recast; say which filings
  show it (8-K 4.02 / 10-K/A).
- CORRESP/UPLOAD filings show that a filing review happened; do not call a review "active" or assume it concerns
  the restatement unless dates/content show it.
- If the cross-check found mismatches, say the reference numbers are used and why.
Company: {name}. Data (reference values are authoritative):
{data}"""
def close(a, b, tol=0.02):
    if a is None or b is None: return a is None and b is None
    return abs(a - b) <= tol * max(1, abs(b))
def crosscheck(model, ref, deltas_ref):
    rows = []
    mb, rb = model.get("beneish") or {}, ref["beneish"]
    rows.append(("M-score", mb.get("m_score"), rb.get("m_score")))
    for k, v in (rb.get("ratios") or {}).items(): rows.append(("M." + k, (mb.get("ratios") or {}).get(k, mb.get(k)), v))
    mf, rf = model.get("dechow_f") or {}, ref["dechow_f"]
    rows.append(("F-score", mf.get("f_score", mf.get("F")), rf.get("f_score")))
    for k, v in (rf.get("variables") or {}).items(): rows.append(("F." + k, (mf.get("variables") or {}).get(k, mf.get(k)), v))
    rows.append(("Benford MAD", (model.get("benford") or {}).get("mad"), ref["benford"].get("mad")))
    md = model.get("deltas") or []
    key = lambda r: (r.get("item"), r.get("start") or None, r.get("end"))
    mk = {key(r): r for r in md if isinstance(r, dict)}; rk = {key(r): r for r in deltas_ref}
    both = set(mk) & set(rk)
    val_mis = [k for k in both if not close(mk[k].get("restated"), rk[k]["restated"], 1e-6) or not close(mk[k].get("original"), rk[k]["original"], 1e-6)]
    out = [{"metric": n, "model": m, "reference": r, "match": close(m, r, 0.02 if n.startswith(("M", "F")) else 0.05)} for n, m, r in rows]
    out.append({"metric": "deltas (count)", "model": len(mk), "reference": len(rk), "match": len(mk) == len(rk) and not val_mis,
                "only_model": len(set(mk) - set(rk)), "only_reference": len(set(rk) - set(mk)), "value_mismatches": len(val_mis)})
    return out
NETWORK = re.compile(r"(ConnectionError|Errno -3|Errno 101|Temporary failure in name resolution|Name or service not known|Network is unreachable|NewConnectionError|URLError|gaierror)")
DATA_DESC = """Data (read-only) is in /data:
- /data/companyfacts.json : SEC XBRL companyfacts for {name} (CIK {cik}). Facts at facts['us-gaap'][TAG]['units']['USD'],
  each fact has val, end, optional start (duration facts), fy, fp, form, filed, accn.
- /data/filings.json : this company's 8-K Item 4.02 notices, 10-K/A, 10-Q/A, CORRESP, UPLOAD filings (form, filed, url).
- /data/tag_map.json : line item -> ordered list of fallback XBRL tags."""
ASK = """You are a forensic-accounting analyst. Answer the user's question by writing ONE Python 3.12 script
(stdlib + numpy + pandas only).
""" + DATA_DESC + """
Write a JSON object to /out/result.json with keys "answer" (short text), "table" (list of row dicts, optional) and
"notes" (list of caveats/limitations). Print a short summary to stdout.
Reply with exactly one ```python block and nothing else.

Question: {q}"""
ASK_EXPLAIN = """Explain this result to a New York litigator in <=180 words. Plain. Say what the code actually computed and
from which data, state limits honestly (if data needed was not available, say so). If the sandbox blocked anything, say
what happened. Do not overstate. The SEC does not "audit" companies; screens are not predictions.
Question: {q}
Attempts: {attempts}
Result: {result}"""
def loop(job, msgs, run_dir, log, max_attempts=3):
    """Model writes code -> runner executes in sandbox -> retry on error. Every attempt is logged, incl. no-code replies."""
    attempts, result = [], None
    for i in range(1, max_attempts + 1):
        t0 = time.time(); reply = llm.chat(msgs); code = llm.code_block(reply)
        a = {"attempt": i, "model_seconds": round(time.time() - t0, 1), "code": code}
        if not code:
            a.update(status="no_code", model_reply=reply[-3000:]); attempts.append(a); log(attempts)
            msgs += [{"role": "assistant", "content": reply or "(empty)"}, {"role": "user", "content": "Reply with the full script in one ```python block."}]
            continue
        text = (r.get("stdout") or "") + (r.get("stderr") or "") + json.dumps(r.get("result"), default=str)  # caught errors land in result.json
        text = (r.get("stdout") or "") + (r.get("stderr") or "")
        a.update({k: r.get(k) for k in ("container", "exit_code", "seconds", "timed_out", "oom_killed", "destroyed", "stdout", "stderr", "out_files")})
        a["network_blocked"] = bool(NETWORK.search(text))
        a["code_references_network"] = bool(re.search(r"^\s*(?:import|from)\s+[^\n]*\b(requests|urllib|http\.client|socket|httpx|aiohttp)\b", code, re.M))
        ok = r.get("exit_code") == 0 and r.get("result") is not None
        a["status"] = "ok" if ok else ("timeout" if r.get("timed_out") else "killed" if r.get("oom_killed") else "error")
        if run_dir: (run_dir / f"attempt{i}.py").write_text(code)
        attempts.append(a); log(attempts)
        if ok: result = r["result"]; break
        extra = " (killed: time or memory limit)" if r.get("timed_out") or r.get("oom_killed") else ""
        if a["network_blocked"]: extra += " (the sandbox has no network access)"
        err = ((r.get("stderr") or "") + "\n" + (r.get("stdout") or ""))[-2500:]
        if not r.get("exit_code") and r.get("result") is None: err += "\n/out/result.json was not written or invalid."
        msgs += [{"role": "assistant", "content": reply}, {"role": "user", "content": FIX.format(rc=r.get("exit_code"), extra=extra, err=err)}]
    return attempts, result
def prepare(ticker):
    c = sec.lookup(ticker); cik, name = c["cik"], c["name"]
    run = RUNS / f"{c['ticker']}-{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}"; data = run / "data"; data.mkdir(parents=True)
    cf = sec.companyfacts(cik); fl = sec.filings(cik)
    (data / "companyfacts.json").write_text(json.dumps(cf)); (data / "filings.json").write_text(json.dumps(fl))
    (data / "tag_map.json").write_text(json.dumps(xbrl.TAGS, indent=1))
    return c, cf, fl, run
def analyse(ticker, log=lambda *_: None):
    c, cf, fl, run = prepare(ticker); cik, name = c["cik"], c["name"]
    ref = screens.run_all(cf); deltas_ref = xbrl.restatement_deltas(cf); aaer = sec.aaer_matches(name)
    ends = ref.get("fiscal_year_ends", [])
    if len(ends) < 2: return {"name": name, "cik": cik, "ticker": c["ticker"], "error": "fewer than two fiscal years of XBRL data"}
    job = sandbox.stage_data(run / "data")
    msgs = [{"role": "user", "content": TASK.format(name=name, cik=cik, instant=sorted(xbrl.INSTANT), t=ends[0], p=ends[1], pp=ends[2] if len(ends) > 2 else "n/a")}]
    try: attempts, result = loop(job, msgs, run, lambda a: log({"stage": "sandbox", "attempts": a}))
    finally: sandbox.cleanup(job)
    xc = crosscheck(result, ref, deltas_ref) if result else []
    mism = [x for x in xc if not x["match"]]
    summary = {"name": name, "cik": cik, "ticker": c["ticker"], "sic": fl.get("sicDescription"), "fiscal_year_ends": ends,
               "restatement_filings": [f for f in fl["filings"] if f["form"] not in ("CORRESP", "UPLOAD")],
               "comment_letters": [f for f in fl["filings"] if f["form"] in ("CORRESP", "UPLOAD")],
               "aaer_name_matches": aaer, "reference": ref, "reference_deltas": deltas_ref, "reference_delta_count": len(deltas_ref),
               "crosscheck_mismatches": mism}
    log({"stage": "explaining", "attempts": attempts})
    slim = dict(summary, reference_deltas=deltas_ref[:15], comment_letters=[f for f in summary["comment_letters"] if f["filed"] >= "2024-01-01"],
                restatement_filings=summary["restatement_filings"][:12])
    expl = llm.chat([{"role": "user", "content": EXPLAIN.format(name=name, data=json.dumps(slim, default=str)[:60000])}], 6000)
    out = {**summary, "attempts": attempts, "model_result": result, "crosscheck": xc, "explanation": expl}
    (run / "report.json").write_text(json.dumps(out, indent=1, default=str))
    return out
def ask(ticker, question, log=lambda *_: None):
    c, cf, fl, run = prepare(ticker)
    job = sandbox.stage_data(run / "data")
    msgs = [{"role": "user", "content": ASK.format(name=c["name"], cik=c["cik"], q=question)}]
    try: attempts, result = loop(job, msgs, run, lambda a: log({"stage": "sandbox", "attempts": a}))
    finally: sandbox.cleanup(job)
    log({"stage": "explaining", "attempts": attempts})
    slim = [{k: a.get(k) for k in ("attempt", "status", "exit_code", "network_blocked", "timed_out")} | {"err": (a.get("stderr") or "")[-400:]} for a in attempts]
    expl = llm.chat([{"role": "user", "content": ASK_EXPLAIN.format(q=question, attempts=json.dumps(slim), result=json.dumps(result, default=str)[:20000])}])
    out = {"ticker": c["ticker"], "name": c["name"], "question": question, "attempts": attempts, "result": result, "explanation": expl}
    (run / "ask.json").write_text(json.dumps(out, indent=1, default=str))
    return out
