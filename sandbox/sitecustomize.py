# Loaded by the interpreter at startup (system site-packages; -I does not disable it).
# Records every network attempt to /out/.netlog BEFORE it fails against --network none, so the app can show it
# even when model code swallows the exception. Observation only; the block itself is the container's lack of network.
import sys, json, time
_EV = {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.connect", "socket.connect_ex",
       "urllib.Request", "http.client.connect", "socket.sendto"}
def _hook(ev, args):
    if ev in _EV:
        try:
            with open("/out/.netlog", "a") as f:
                f.write(json.dumps({"t": round(time.time(), 3), "event": ev, "target": repr(args[:2])[:200]}) + "\n")
        except Exception:
            pass
sys.addaudithook(_hook)
