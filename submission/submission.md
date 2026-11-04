# lablab.ai submission — Vultr hackathon

**Challenge:** Challenge 1, "Blast Radius Zero", Pattern A (model writes code, sandbox runs it)

**Title:** Restatement Risk Agent

**Short description:** For companies that restated their financials, it shows what changed, SEC correspondence and forensic screens from SEC XBRL. A model's code runs in a no-network sandbox and is cross-checked against reference code.

**Long description:**
When a company files an 8-K Item 4.02 non-reliance notice or an amended 10-K/10-Q, people want to know what changed and whether more scrutiny is likely. Restatement Risk Agent pulls the company's SEC filings, XBRL financial data, comment-letter correspondence and the AAER list. It then recomputes published academic screens: Beneish M-score, Dechow F-score and Benford MAD.

A model on Vultr Serverless Inference writes Python code that runs against the staged data. That code runs in a throwaway container with no network, no keys, a read-only filesystem, 512 MB of memory, 1 CPU and a 30-second limit. A separate runner service holds the Docker socket, and the app holding the inference key never runs model code. Every attempt is logged, including failures. An audit hook in the sandbox records every network attempt, so the UI flags a containment event even when the model's code swallows the error. In testing, the model tried to download 10-K/A text from sec.gov for PetMed Express and GoPro, and both attempts were blocked and logged.

The model's numbers are cross-checked against deterministic reference code, and the reference wins. The model is often wrong; one GoPro run failed 19 checks. The page shows each failure rather than hiding it.

Caveats: the SEC does not "audit" companies. Follow-up comes as comment letters or Enforcement. The scores are screens, not predictions, and they are not the SEC's Accounting Quality Model. The backtest page shows what happened to 2021–2023 restaters and makes no accuracy claim.

**Tags:** Vultr, Serverless Inference, Docker, Sandbox, AI Agents, SEC EDGAR, XBRL, Forensic Accounting, FastAPI, Python

**Technologies / Vultr services:** Vultr Cloud Compute (VM, Docker, Caddy), Vultr Serverless Inference (glm-5.3-flash)

**Repository:** https://github.com/banksythequantLab/restatement-risk

**Live app:** https://rr.207-246-93-241.sslip.io

**Video:** [PLACEHOLDER: hosted video link] (local file: submission/restatement-risk-demo.mp4, 2:59, 1080p)

**Cover / screenshots:** shots/04-report-GPRO.png, shots/07-ask-PETS-10KA-network-blocked.png, submission/frame_*.png
