"""Client side of the sandbox. The app stages files under RR_ROOT/jobs and asks the internal runner service to run
one attempt. The app holds the inference key but NOT the docker socket; the runner holds the socket but no keys."""
import json, os, pathlib, shutil, uuid, requests
ROOT = pathlib.Path(os.getenv("RR_ROOT", "/var/lib/rr")); JOBS = ROOT / "jobs"
RUNNER = os.getenv("SANDBOX_RUNNER_URL", "http://runner:9000")
def stage_data(local_dir):
    job = "rr-job-" + uuid.uuid4().hex[:12]; d = JOBS / job / "data"; d.mkdir(parents=True)
    for p in pathlib.Path(local_dir).iterdir(): shutil.copy(p, d / p.name)
    for p in [JOBS / job, d, *d.iterdir()]: os.chmod(p, 0o755 if p.is_dir() else 0o444)
    return job
def run(job, code, attempt):
    a = JOBS / job / f"a{attempt}"; (a / "code").mkdir(parents=True); (a / "out").mkdir()
    (a / "code" / "main.py").write_text(code); os.chmod(a / "code" / "main.py", 0o444)
    for p in (a, a / "code"): os.chmod(p, 0o755)
    os.chown(a / "out", 10001, 10001)
    r = requests.post(RUNNER + "/run", json={"job": job, "attempt": attempt}, timeout=120).json()
    res = a / "out" / "result.json"
    r["result"] = None
    if res.is_file() and res.stat().st_size < 5_000_000:
        try: r["result"] = json.loads(res.read_text())
        except ValueError: r["result_error"] = "result.json is not valid JSON"
    r["out_files"] = sorted(p.name for p in (a / "out").iterdir())
    return r
def cleanup(job): shutil.rmtree(JOBS / job, ignore_errors=True)
