# lablab.ai submission — Vultr hackathon

**Challenge:** Challenge 1, "Blast Radius Zero", Pattern A (model writes code, sandbox runs it)

**Title:** Restatement Risk Agent

**Short description:** When a company says "don't rely on our past financials," did the stock fall, and when? Event studies around SEC Item 4.02 notices, class-action lookups, what changed, and forensic screens. A model's code runs in a no-network sandbox, checked against reference code.

**Long description:**
When a company files an 8-K Item 4.02 notice, it is telling investors not to rely on its past financial statements. The first question is whether the stock fell, and when. For each notice, Restatement Risk Agent:
- sets day 0 from the EDGAR acceptance time (after the 4 pm close counts as the next trading day);
- charts the price with the notice marked;
- reports raw and Russell-2000-adjusted returns over 0–1, 0–5 and 0–30 trading days, with exact dates;
- flags same-day earnings releases and other 8-Ks that could explain the move;
- checks CourtListener for securities class actions filed within a year.

Across all 1,031 companies with a first notice in 2021–2023, 474 were operating companies, and 307 of those had usable prices. Their median move over day 0 to 5 was −2.0% net of IWM, and 21% fell more than 10%. SPACs (557 companies, mostly the 2021 warrant-accounting wave) barely moved. This is descriptive, not a prediction. The app also shows what changed between the original and restated XBRL numbers, the SEC comment letters, any AAER naming the company, and three published screens: Beneish M-score, Dechow F-score and Benford MAD.

A model on Vultr Serverless Inference writes Python code that runs against the staged data. That code runs in a throwaway container with no network, no keys, a read-only filesystem, 512 MB of memory, 1 CPU and a 30-second limit. A separate runner service holds the Docker socket, and the app holding the inference key never runs model code. Every attempt is logged, including failures. An audit hook in the sandbox records every network attempt, so the UI flags a containment event even when the model's code swallows the error. In testing, the model tried to download 10-K/A text from sec.gov for PetMed Express and GoPro, and both attempts were blocked and logged.

The model's numbers are cross-checked against deterministic reference code, and the reference wins. The model is often wrong; one GoPro run failed 19 checks. The page shows each failure rather than hiding it.

Caveats: the SEC does not "audit" companies. Follow-up comes as comment letters or Enforcement. The scores are screens, not predictions, and they are not the SEC's Accounting Quality Model. Stock-reaction numbers are descriptive, not causal or predictive. Prices come from an unofficial Yahoo endpoint, best-effort.

**Tags:** Vultr, Serverless Inference, Docker, Sandbox, AI Agents, SEC EDGAR, XBRL, Forensic Accounting, FastAPI, Python

**Technologies / Vultr services:** Vultr Cloud Compute (VM, Docker, Caddy), Vultr Serverless Inference (glm-5.3-flash)

**Repository:** https://github.com/banksythequantLab/restatement-risk

**Live app:** https://rr.207-246-93-241.sslip.io

**Video:** [PLACEHOLDER: hosted video link] (local file: submission/restatement-risk-demo.mp4, 3:42, 1080p)

**Cover / screenshots:** shots/04-report-GPRO.png, shots/07-ask-PETS-10KA-network-blocked.png, submission/frame_*.png
