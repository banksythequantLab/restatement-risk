import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "runner"))
from rr import xbrl, screens, sec, agent
import runner as R
def fact(v, end, filed, form, start=None, fp="FY", accn=None):
    f = {"val": v, "end": end, "filed": filed, "form": form, "fp": fp, "accn": accn or f"a-{filed}"}
    if start: f["start"] = start
    return f
def cf_with(**tags): return {"facts": {"us-gaap": {t: {"units": {"USD": fs}} for t, fs in tags.items()}}}
def test_delta_original_vs_restated():
    cf = cf_with(NetIncomeLoss=[fact(-21, "2025-09-30", "2025-11-06", "10-Q", "2025-07-01"), fact(-27, "2025-09-30", "2026-10-19", "10-K/A", "2025-07-01")])
    d = xbrl.restatement_deltas(cf)
    assert len(d) == 1 and d[0]["original"] == -21 and d[0]["restated"] == -27 and d[0]["restated_form"] == "10-K/A"
def test_unchanged_not_reported():
    cf = cf_with(Assets=[fact(5, "2025-12-31", "2026-02-01", "10-K"), fact(5, "2025-12-31", "2026-05-01", "10-Q")])
    assert xbrl.restatement_deltas(cf) == []
def test_tag_fallback_and_missing():
    cf = cf_with(RevenueFromContractWithCustomerExcludingAssessedTax=[fact(100, "2025-12-31", "2026-02-01", "10-K", "2025-01-01")])
    assert xbrl.annual_value(cf, "revenue", "2025-12-31")[1] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert xbrl.annual_value(cf, "cogs", "2025-12-31")[0] is None
def test_beneish_insufficient_is_explicit():
    r = screens.beneish(cf_with(), "2025-12-31", "2024-12-31")
    assert r["status"] == "insufficient_data" and r["m_score"] is None
def test_crosscheck_flags_mismatch():
    ref = {"beneish": {"m_score": -3.0, "ratios": {"DSRI": 1.0}}, "dechow_f": {"f_score": 0.5, "variables": {}}, "benford": {"mad": 0.01}}
    xc = agent.crosscheck({"beneish": {"m_score": -2.0, "ratios": {"DSRI": 1.0}}, "dechow_f": {"f_score": 0.5}, "benford": {"mad": 0.01}, "deltas": []}, ref, [])
    bad = {x["metric"] for x in xc if not x["match"]}
    assert bad == {"M-score"}
def test_network_error_detected():
    assert agent.NETWORK.search("socket.gaierror: [Errno -3] Temporary failure in name resolution")
def test_aaer_name_norm():
    rows = [{"name": "Latch, Inc."}, {"name": "Latchford Corp"}]
    assert [r["name"] for r in sec.aaer_matches("LATCH INC", rows)] == ["Latch, Inc."]
def test_runner_rejects_bad_job():
    import pytest
    for job, a in [("../etc", 1), ("rr-job-xyz", 1), ("rr-job-0123456789ab", 0), ("rr-job-0123456789ab", "1")]:
        with pytest.raises(ValueError): R.run(job, a)
def test_runner_flags_locked_down():
    for f in ["--network", "none", "--read-only", "--cap-drop", "ALL", "--memory", "512m", "--env-file", "/dev/null"]:
        assert f in R.FLAGS
def test_network_import_detected_in_multi_import():
    import re
    src = open(agent.__file__).read()
    pat = re.search(r're\.search\((r"\^.*?")', src).group(1)
    assert re.search(eval(pat), "import json, re, html, urllib.request, pathlib", re.M)
def test_name_postcheck_fixes_wrong_name():
    t, f = agent.check_names("the most recent 10-K/A for Pets at Home (CIK 1040130).", "PETMED EXPRESS INC", 1040130)
    assert f == ["Pets at Home"] and "PETMED EXPRESS INC (CIK 1040130)" in t
    t2, f2 = agent.check_names("GoPro, Inc. (CIK 1500435) filed", "GoPro, Inc.", 1500435)
    assert f2 == [] and t2.startswith("GoPro")
def test_available_tags_lists_present_fallbacks():
    cf = cf_with(RevenueFromContractWithCustomerExcludingAssessedTax=[fact(1, "2025-12-31", "2026-02-01", "10-K", "2025-01-01")])
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in agent.available_tags(cf)["revenue"]
def test_sitecustomize_logs_network_attempt(tmp_path):
    import subprocess, textwrap
    sc = pathlib.Path(__file__).resolve().parent.parent / "sandbox" / "sitecustomize.py"
    code = textwrap.dedent(f"""
        import sys; exec(open({str(sc)!r}).read().replace('/out/.netlog', {str(tmp_path / '.netlog')!r}))
        import socket
        try: socket.getaddrinfo('www.sec.gov.invalid', 443)
        except Exception: pass
    """)
    subprocess.run([sys.executable, "-c", code], check=True)
    assert "socket.getaddrinfo" in (tmp_path / ".netlog").read_text()
