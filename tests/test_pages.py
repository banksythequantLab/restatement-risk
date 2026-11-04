import os, tempfile
os.environ.setdefault("RR_ROOT", tempfile.mkdtemp())
from fastapi.testclient import TestClient
import app.main as m
def test_pages_render():
    c = TestClient(m.app)
    for u in ["/", "/backtest", "/about", "/ask", "/health"]:
        assert c.get(u).status_code == 200, u
def test_bad_ticker_rejected():
    assert TestClient(m.app).get("/c/..%2Fetc").status_code in (400, 404, 422)
