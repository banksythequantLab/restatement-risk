"""rr sandbox runner: the ONLY component holding the Docker socket. Internal network only, no published port, no secrets.
The app may ask for exactly one thing: "run jobs/<job>/a<n>/code/main.py". Image, flags and mounts are fixed here."""
import json, os, pathlib, re, subprocess, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
JOBS = pathlib.Path(os.getenv("RR_ROOT", "/var/lib/rr")).resolve() / "jobs"
IMAGE = "rr-sandbox:latest"; TIMEOUT = int(os.getenv("RUN_TIMEOUT", 30))
FLAGS = ["--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=64m,noexec,nosuid",
         "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "64", "--ulimit", "nofile=256:256",
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10001:10001", "--env-file", "/dev/null"]
JOB = re.compile(r"^rr-job-[0-9a-f]{12}$")
def run(job, attempt):
    if not (isinstance(job, str) and JOB.match(job)): raise ValueError("bad job")
    if not (isinstance(attempt, int) and 1 <= attempt <= 10): raise ValueError("bad attempt")
    base = JOBS / job; a = base / f"a{attempt}"
    for p in (base / "data", a / "code", a / "out"):
        if not p.is_dir() or p.is_symlink(): raise ValueError("missing dir")
    cid = "rr-sbx-" + uuid.uuid4().hex[:10]
    cmd = ["docker", "run", "--name", cid, *FLAGS, "-v", f"{base/'data'}:/data:ro", "-v", f"{a/'code'}:/code:ro",
           "-v", f"{a/'out'}:/out:rw", IMAGE]
    r = {"container": cid, "flags": FLAGS, "timed_out": False, "oom_killed": False}
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env={"PATH": "/usr/bin:/bin"})
        r.update(exit_code=p.returncode, stdout=p.stdout[-8000:], stderr=p.stderr[-8000:])
        r["oom_killed"] = p.returncode == 137
    except subprocess.TimeoutExpired as e:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        r.update(exit_code=-9, timed_out=True, stdout=(e.stdout or b"").decode()[-8000:] if isinstance(e.stdout, bytes) else (e.stdout or "")[-8000:],
                 stderr=f"killed: {TIMEOUT}s time limit")
    r["seconds"] = round(time.time() - t0, 2)
    r["destroyed"] = subprocess.run(["docker", "ps", "-aq", "--filter", f"name=^{cid}$"], capture_output=True, text=True).stdout.strip() == ""
    return r
class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/health": return self._send(200, {"ok": True, "image": IMAGE, "flags": FLAGS, "timeout_s": TIMEOUT})
        self._send(404, {})
    def do_POST(self):
        if self.path != "/run": return self._send(404, {})
        try:
            b = json.loads(self.rfile.read(min(int(self.headers.get("content-length", 0)), 1024)) or b"{}")
            self._send(200, run(b.get("job"), b.get("attempt")))
        except (ValueError, json.JSONDecodeError) as e: self._send(400, {"error": str(e)})
    def log_message(self, *a): pass
if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), H).serve_forever()
