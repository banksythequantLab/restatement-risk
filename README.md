# Restatement Risk Agent (work in progress)

Looks at companies that restated (8-K Item 4.02 non-reliance, 10-K/A, 10-Q/A) and shows what changed, the SEC
correspondence on file, any AAER name match, and published forensic screens recomputed from SEC XBRL data.

**What it is not.** The SEC does not "audit" companies; scrutiny comes as Corp Fin filing review (comment letters) and,
rarely, Enforcement. M-score (Beneish 1999) and F-score (Dechow et al. 2011) here are approximations of published academic
screens on XBRL data, not the SEC's non-public Accounting Quality Model. A score is a screen, not a prediction.

## Flow (Pattern A)
1. `rr/sec.py` fetches public SEC data outside the sandbox (fixed User-Agent, ~8 req/s, disk cache).
2. `rr/agent.py` asks Vultr Serverless Inference (`glm-5.3-flash`) to write a Python script.
3. `rr/sandbox.py` runs it in a throwaway container on the Vultr VM: `--network none`, `/data` read-only, `/out` scratch,
   512 MB, 1 CPU, 64 pids, 30 s kill, cap-drop ALL, no-new-privileges, uid 10001, empty env, removed after.
4. Errors go back to the model (max 3 attempts).
5. Model output is cross-checked against deterministic reference code (`rr/xbrl.py`, `rr/screens.py`); mismatches are
   reported and the reference numbers win.
6. The model writes a plain-English explanation with the caveats above.

Run: `VULTR_INFERENCE_API_KEY=... python3 -m rr.agent GPRO` (needs ssh alias `proveit` with docker and image `rr-sandbox`).
