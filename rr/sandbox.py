"""Runs model-written code in a throwaway Docker container on the Vultr VM. Image, flags and mounts are fixed here;
the model controls only the contents of main.py. No env vars, no network, /data read-only, removed after each run.
Transport for milestone 1: ssh to the VM (alias 'proveit'); the inference key never leaves this process."""
import json, pathlib, shlex, subprocess, tempfile, time, uuid
HOST = "proveit"; ROOT = "/var/lib/rr/jobs"; IMAGE = "rr-sandbox:latest"; TIMEOUT = 30
FLAGS = ["--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=64m,noexec,nosuid",
         "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "64", "--ulimit", "nofile=256:256",
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10001:10001", "--env-file", "/dev/null"]
def ssh(cmd, timeout=120, inp=None):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd], capture_output=True, text=True, timeout=timeout, input=inp)
def stage_data(local_dir):
    """Copy fetched JSON to the VM once per task. Returns remote job dir."""
    job = f"{ROOT}/rr-{uuid.uuid4().hex[:12]}"
    ssh(f"mkdir -p {job}/data && chmod 755 {job} {job}/data")
    subprocess.run(["scp", "-q", "-r", *[str(p) for p in pathlib.Path(local_dir).iterdir()], f"{HOST}:{job}/data/"], check=True, timeout=300)
    ssh(f"chmod -R a+rX,a-w {job}/data")
    return job
def run(job, code, attempt):
    run_dir = f"{job}/a{attempt}"; cid = "rr-sbx-" + uuid.uuid4().hex[:10]
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f: f.write(code)
    ssh(f"mkdir -p {run_dir}/code {run_dir}/out && chown 10001:10001 {run_dir}/out && chmod 755 {run_dir}/code")
    subprocess.run(["scp", "-q", f.name, f"{HOST}:{run_dir}/code/main.py"], check=True, timeout=60)
    ssh(f"chmod 644 {run_dir}/code/main.py")
    cmd = ["docker", "run", "--name", cid, *FLAGS, "-v", f"{job}/data:/data:ro", "-v", f"{run_dir}/code:/code:ro",
           "-v", f"{run_dir}/out:/out:rw", IMAGE]
    remote = (f"timeout -s KILL {TIMEOUT} {shlex.join(cmd)}; rc=$?; docker rm -f {cid} >/dev/null 2>&1; "
              f"echo __RC=$rc; echo __GONE=$(docker ps -aq --filter name=^{cid}$ | wc -l); "
              f"echo __OOM=$(dmesg 2>/dev/null | tail -5 | grep -c -i 'killed process')")
    t0 = time.time(); p = ssh(remote, timeout=TIMEOUT + 60); dt = round(time.time() - t0, 1)
    lines = p.stdout.splitlines(); meta = {l.split("=")[0][2:]: l.split("=", 1)[1] for l in lines if l.startswith("__")}
    rc = int(meta.get("RC", -1))
    res = ssh(f"cat {run_dir}/out/result.json 2>/dev/null | head -c 2000000")
    return {"container": cid, "flags": FLAGS, "exit_code": rc, "seconds": dt,
            "timed_out": rc == 137 and dt >= TIMEOUT - 1, "oom_or_killed": rc == 137,
            "destroyed": meta.get("GONE") == "0",
            "stdout": "\n".join(l for l in lines if not l.startswith("__"))[-6000:], "stderr": p.stderr[-6000:],
            "result": json.loads(res.stdout) if res.stdout.strip().startswith("{") else None}
