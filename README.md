# Restatement Risk Agent

Live: https://rr.207-246-93-241.sslip.io (Vultr VM, alongside Prove-It)

Looks at companies that restated (8-K Item 4.02 non-reliance, 10-K/A, 10-Q/A). For each one it shows what changed,
the SEC correspondence on file, any AAER name match, and published forensic screens recomputed from SEC XBRL data.
A free-form "ask" box lets a model write code against that company's data. The code runs in a sandbox with no
network, and every attempt is shown.

**What it is not.**
- The SEC does not "audit" companies. Scrutiny comes as Corp Fin filing review (comment letters) and, rarely,
  Enforcement.
- M-score (Beneish 1999), F-score (Dechow et al. 2011) and Benford MAD (Nigrini) here are approximations of published
  academic screens on XBRL data. They are not the SEC's non-public Accounting Quality Model.
- A score is a screen, not a prediction.
- The backtest page shows what happened to 2021–2023 restaters. It makes no accuracy claim.

## Architecture (Pattern A: model writes code, sandbox runs it)

```mermaid
flowchart LR
  U[Browser] -->|HTTPS| C[Caddy<br/>shared with Prove-It]
  C -->|prove-it_web network| A[rr-app<br/>FastAPI UI + agent<br/>holds inference key]
  A -->|HTTPS| V[Vultr Serverless Inference<br/>glm-5.3-flash]
  A -->|HTTPS, UA + ≤10 req/s| S[SEC EDGAR / data.sec.gov / AAER list]
  A -->|rr_internal network<br/>POST /run job,attempt| R[rr-runner<br/>docker socket, no keys,<br/>no public port]
  R -->|docker run| X[[Sandbox container<br/>--network none, read-only,<br/>512MB, 1 CPU, 64 pids, 30s,<br/>cap-drop ALL, uid 10001, empty env]]
  A -. writes code / data .-> J[(/var/lib/rr/jobs)]
  X -. /data ro, /code ro, /out rw .-> J
```

- **rr-app** fetches all SEC data itself, outside the sandbox. It stages the data read-only, asks the model for
  code, and has the runner execute it. Errors go back to the model (3 attempts max). The model's numbers are then
  cross-checked against deterministic reference code (`rr/xbrl.py`, `rr/screens.py`). Mismatches are shown, and the
  reference wins.
- **rr-runner** is the only component with the docker socket. It holds no API keys and sits only on an internal
  network. It accepts just a validated job id and attempt number; the image and flags are fixed in code.
- **Every attempt is logged.** That includes replies with no code, errors, timeouts, OOM kills, and network failures
  inside the sandbox. The UI flags a "Contained: network blocked" event in red.

## Vultr services used
- **Vultr Cloud Compute** VM (Docker, Caddy TLS via sslip.io). This is a separate compose project `rr` next to
  Prove-It.
- **Vultr Serverless Inference** (OpenAI-compatible, `glm-5.3-flash`), used for code generation and explanations.

## Run
```
docker compose -p rr up -d --build      # .env needs VULTR_INFERENCE_API_KEY (never committed, never passed to sandbox)
python3 scripts/backtest.py             # regenerates data/backtest.json
python3 -m pytest -q tests
```
Data sources: SEC EDGAR full-text search, submissions, companyfacts, the comment-letter (CORRESP/UPLOAD) index, and
the AAER list. The User-Agent is set as the SEC requires.

## Known limits
- XBRL tag gaps (custom tags, missing receivables or COGS) make screens "insufficient data". This is common for SPACs
  and banks.
- AAER matching is by exact normalized company name, so misses are possible. An AAER may also concern a different
  matter than the restatement.
- The model sometimes mislabels or misreads data. The cross-check catches numeric errors but not prose errors in
  explanations.
