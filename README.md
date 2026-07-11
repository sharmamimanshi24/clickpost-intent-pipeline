# ClickPost Intent Scoring Pipeline

A prototype that scores D2C brands on buying intent for ClickPost's post-purchase/returns software, and generates personalized outreach for the top-ranked accounts.

Full reasoning (signal taxonomy, methodology, tradeoffs, limitations) is in `CP-Memo.docx`. This README covers setup and how to run the code.

---

## What's in this repo

| File | What it does |
|---|---|
| `CP-scorebook.xlsx` | Manually researched signals for 25 D2C brands, with real source URLs |
| `tier.py` | Classifies raw research text into tier codes (S/M/W/N, Y/N, etc.) using a local LLM, following a fixed rubric. Run separately so its output can be checked before scoring. |
| `score.py` | Reads the tier codes, applies a fixed point rubric, and produces a ranked, explainable score for every brand. No AI in the scoring math. |
| `activator.py` | Takes the top 5 scored brands and generates a LinkedIn message + follow-up email for each, grounded in the specific signal that drove their score. |
| `main.py` | Runs `score.py` then `activator.py` in order, one command. |
| `scored_accounts.csv` | Sample output: all 25 brands, ranked with scores and reasoning |
| `outreach_top5.csv` | Sample output: generated outreach for the top 5 |

---

## Setup

**1. Install Python dependencies:**
```bash
pip install -r requirements.txt
```
This installs `openpyxl` (needed to read/write the Excel file). Everything else the pipeline uses is built into Python — no other packages required.

**2. (Optional) Set up a local LLM for AI-assisted classification and writing:**

The pipeline works completely without this step — it falls back to plain rule-based text and templates automatically. AI is used to speed up two things:
- `tier.py`: classifying raw research text into tier codes
- `score.py` / `activator.py`: writing more natural explanation text and outreach copy

To enable it:
1. Install [Ollama](https://ollama.com/download)
2. Pull a model: `ollama pull llama3.2`
3. Start the server: `ollama serve` (leave this running in its own terminal)
4. Set the environment variable before running anything:
   ```bash
   # Windows PowerShell
   $env:USE_LLM_EXPLANATIONS="true"

   # Mac/Linux
   export USE_LLM_EXPLANATIONS=true
   ```

If you skip this entirely, everything still runs correctly using deterministic rule-based text.

---

## How to run it

**Step 1 — Classify tiers (run this separately, so you can check its output):**
```bash
python tier.py
```
This only fills in *blank* tier cells — it won't overwrite anything you've already set. To force it to reclassify everything from scratch:
```bash
python tier.py --overwrite
```

If `USE_LLM_EXPLANATIONS` isn't set, this step just exports the spreadsheet to CSV as-is (no classification happens) — safe to run either way.

**Step 2 — Score and generate outreach:**
```bash
python main.py
```
This runs `score.py` then `activator.py` and produces:
- `scored_accounts.csv` — all 25 brands, ranked, with intent level, recommended action, top reasons, and evidence sources
- `outreach_top5.csv` — LinkedIn message + email for the top 5 accounts

---

## Notes on the data

- **`tier.py` classifies 5 signals from raw text**: complaint severity, leadership hire recency, current returns-vendor status, open hiring postings, and growth/expansion.
- **`Product_Fits_Returns_Category` is set manually, not by AI** — determining whether a brand's product category (e.g. food/beverage vs. apparel) generates real returns friction needs real-world knowledge, not text pattern-matching, so this one column is intentionally excluded from automated classification.
- Brands where `Product_Fits_Returns_Category = N` (e.g. food and beverage brands) are automatically skipped by `tier.py` and score 0 on the tech-stack category in `score.py` — they're not realistic ClickPost prospects.
- Highlighting a raw-text cell **red** in the spreadsheet tells `tier.py` to skip it entirely.

---

## Design choices worth noting

- **Scoring is 100% deterministic** — the same tier codes always produce the same score. AI is only ever used to help classify raw text into those codes, or to rewrite explanation/outreach wording — never to decide the actual point values.
- **Every LLM call has a safe fallback.** If Ollama isn't installed or running, the pipeline still produces complete, correct output using rule-based text and templates instead.
- Full rubric, signal taxonomy, and reasoning behind every design decision are documented in `CP-Memo.docx`.
