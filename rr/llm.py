"""Vultr Serverless Inference (OpenAI-compatible). Key read from env at call time; never logged or passed on."""
import os, re, requests
BASE = "https://api.vultrinference.com/v1"; MODEL = "glm-5.3-flash"
def chat(messages, max_tokens=6000):
    key = os.environ.get("VULTR_INFERENCE_API_KEY")
    if not key: raise RuntimeError("VULTR_INFERENCE_API_KEY not set")
    r = requests.post(BASE + "/chat/completions", timeout=300, headers={"Authorization": "Bearer " + key},
        json={"model": MODEL, "messages": messages, "max_tokens": max_tokens, "reasoning_effort": "low", "temperature": 0.2})
    if r.status_code != 200: raise RuntimeError(f"inference HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"].get("content") or ""
def code_block(text):
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return max(m, key=len) if m else None
