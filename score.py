"""
score.py
--------
Layer 3 of the ClickPost intent pipeline: turns manually-researched signal
tiers into an explainable intent score per brand.

INPUT:  a CSV with the research columns Mimi filled in by hand, plus the
        5 tier columns (Complaints_Tier, Leadership_Tier, TechStack_State,
        Hiring_Tier, Growth_Paired).
OUTPUT: a ranked list, printed to console + saved as scored_accounts.csv,
        with one human-readable explanation sentence per brand.

Design choice: this script has ZERO LLM calls. Scoring is pure Python
using a fixed rubric (see RUBRIC below). This is intentional - it means
the score is 100% reproducible and auditable. The judgment calls (what
counts as "moderate" vs "strong") were made by Mimi while researching,
not guessed by a model here.
"""

import csv
import os
import json
import urllib.request
import urllib.error

# Ollama - runs fully locally, no API key, no network/Cloudflare issues.
# Used ONLY to turn the already-computed signals into a crisper plain-English
# sentence - it never touches the actual scoring math. If Ollama isn't running
# locally, the rule-based explanation below (built from the LABEL dicts) is used.
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")  # change if you have a different model pulled
USE_LLM_EXPLANATIONS = os.environ.get("USE_LLM_EXPLANATIONS", "").lower() == "true"


def call_ollama(system_prompt, user_prompt):
    """Calls a local Ollama server. Returns None on any failure (not running, wrong model, etc.) so callers fall back."""
    if not USE_LLM_EXPLANATIONS:
        return None
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["message"]["content"].strip()
    except Exception as e:
        print(f"  [Ollama call failed - {type(e).__name__}: {e}. Is 'ollama serve' running, and is '{OLLAMA_MODEL}' pulled?]")
        return None

# ---------------------------------------------------------------------
# THE RUBRIC - the only numbers this script is allowed to use.
# Scaled so a brand hitting every category maxes out around ~100.
# ---------------------------------------------------------------------
COMPLAINTS_POINTS = {"N": 0, "W": 10, "M": 20, "S": 35, "": 0}
LEADERSHIP_POINTS = {"Y": 20, "N": 0, "": 0}
TECHSTACK_POINTS = {"H": 5, "NT": 15, "C": 20, "": 0}
HIRING_POINTS = {"N": 0, "P": 5, "CL": 10, "": 0}
# Combo bonus removed: TechStack="C" already means "competitor + complaints" -
# awarding a bonus on top of that double-counts the same underlying evidence.
GROWTH_BONUS = 5        # only if Growth_Paired == "Y"

# Human-readable labels, used to build the one-line explanation.
# Kept in plain, everyday language - no jargon like "signal" or "trigger."
COMPLAINTS_LABEL = {"N": "no customer complaints about returns/refunds found", "W": "a few complaints, but not a clear pattern",
                     "M": "some recent complaints about returns/refunds", "S": "many recent, well-documented complaints about returns/refunds",
                     "": "complaints not checked yet"}
LEADERSHIP_LABEL = {"N": "no recent leadership change found", "Y": "a relevant leadership change (CX Head/COO/CTO/Founder) in roughly the last 12 months",
                     "": "leadership not checked yet"}
TECHSTACK_LABEL = {"H": "using a competitor's tool, and customers seem happy with it",
                    "NT": "no returns software in place - doing it manually",
                    "C": "using a competitor's tool, but customers are still complaining - it's not working for them",
                    "": "current tool not confirmed yet"}
HIRING_LABEL = {"N": "not hiring for returns/logistics roles", "P": "hiring for a couple of returns/logistics roles",
                 "CL": "hiring for several returns/logistics roles at once", "": "hiring not checked yet"}


def get_intent_level(score):
    """
    Buckets the already-computed score into a simple label. This is purely
    a DISPLAY bucket - it reads the score, never recalculates it.
    Thresholds tightened so "High" stays meaningful even as more brands get
    the growth bonus - otherwise too many mid-range scores get lumped in.
    """
    if score == 0:
        return "None"
    elif score < 25:
        return "Low"
    elif score < 55:
        return "Medium"
    else:
        return "High"


RECOMMENDED_ACTION = {
    "High": "Contact Immediately",
    "Medium": "Good Prospect",
    "Low": "Monitor",
    "None": "Low Priority",
}


# One-line, rule-based (no LLM) outreach angle per strongest signal category -
# mirrors the pitch logic already used in stage4_activator.py, kept consistent
# so the SDR sees the same story here as in the actual outreach message.
def get_outreach_angle(category, tech_state):
    if category == "tech_stack" and tech_state == "NT":
        return "Lead with the cost of staying manual - no returns platform means real revenue is likely leaking through slow refunds and support load."
    elif category == "tech_stack" and tech_state == "C":
        return "Lead with curiosity, not a hard pitch - they're already paying for a competitor tool that clearly isn't solving their complaints."
    elif category == "complaints":
        return "Lead directly with the specific complaint pattern found - this is active, visible pain they're already dealing with."
    elif category == "leadership":
        return "Lead with the recent leadership change - new hires typically re-evaluate the vendor stack in their first few months."
    elif category == "hiring":
        return "Lead with their open roles - they're already investing headcount into a problem software could solve more cheaply."
    else:
        return "No strong signal to anchor a pitch on yet - more research needed before outreach."


# Raw research columns to check for "Missing Information" - matches the
# columns Mimi fills in by hand. A brand missing several of these has an
# incomplete score, and the SDR should know that before trusting it fully.
RAW_COLUMNS_TO_CHECK = {
    "Customer Complaints ": "Complaints",
    "Hiring (Job Postings/ Listings for CTO/CXH)": "Hiring postings",
    "New Joinee (new CTO/CX/Founder)": "Leadership hire",
    "Growth/ expansion": "Growth/expansion",
    "Current Vendor": "Current returns vendor",
}
MISSING_MARKERS = ("not yet checked", "not yet researched", "not yet confirmed", "")


def get_missing_info(raw_row):
    """Returns a list of plain-English field names that weren't actually researched yet."""
    missing = []
    for col, label in RAW_COLUMNS_TO_CHECK.items():
        value = raw_row.get(col, "").strip().lower()
        if value in MISSING_MARKERS:
            missing.append(label)
    return missing


def get_evidence_sources(raw_row):
    sources = raw_row.get("Source", "").strip()
    return sources if sources else "No sources logged"


def score_brand(row):
    """
    Takes one CSV row (dict) and returns (total_score, explanation_str, breakdown_dict).
    """
    complaints_tier = row.get("Complaint_Severity", "").strip().upper()
    leadership_tier = row.get("Leadership_Hire_Strength", "").strip().upper()
    techstack_state = row.get("Current_Returns_Vendor_Status", "").strip().upper()
    hiring_tier = row.get("Open_Relevant_Roles", "").strip().upper()
    growth_paired = row.get("Is_Growing_Fast", "").strip().upper()
    icp_fit = row.get("Product_Fits_Returns_Category", "Y").strip().upper()  # default Y if column missing (backward compatible)

    complaints_pts = COMPLAINTS_POINTS.get(complaints_tier, 0)
    leadership_pts = LEADERSHIP_POINTS.get(leadership_tier, 0)
    # Tech-stack signal only means something if the product category actually generates
    # returns in the first place (apparel/footwear/home goods vs. food/beverage).
    # For poor-fit categories, "no returns platform" isn't a real gap - they never needed one.
    techstack_pts = 0 if icp_fit == "N" else TECHSTACK_POINTS.get(techstack_state, 0)
    hiring_pts = HIRING_POINTS.get(hiring_tier, 0)

    # Growth is never scored alone - only counts if paired with a real signal above.
    has_real_signal = (complaints_pts > 0 or leadership_pts > 0 or techstack_pts > 0 or hiring_pts > 0)
    growth_pts = GROWTH_BONUS if (growth_paired == "Y" and has_real_signal) else 0

    total = complaints_pts + leadership_pts + techstack_pts + hiring_pts + growth_pts
    total = min(total, 100)  # display cap, per our earlier decision

    breakdown = {
        "complaints": complaints_pts, "leadership": leadership_pts,
        "tech_stack": techstack_pts, "hiring": hiring_pts,
        "growth_bonus": growth_pts,
    }

    # Build the explanation from whichever categories actually contributed,
    # ranked by point value, so the strongest signal is mentioned first.
    parts = []
    if complaints_pts > 0:
        parts.append((complaints_pts, COMPLAINTS_LABEL[complaints_tier]))
    if leadership_pts > 0:
        parts.append((leadership_pts, LEADERSHIP_LABEL[leadership_tier]))
    if techstack_pts > 0:
        parts.append((techstack_pts, TECHSTACK_LABEL[techstack_state]))
    if hiring_pts > 0:
        parts.append((hiring_pts, HIRING_LABEL[hiring_tier]))
    if growth_pts > 0:
        parts.append((growth_pts, "growing fast, which adds more pressure on returns"))

    parts.sort(key=lambda x: -x[0])
    if parts:
        rule_based_explanation = "; ".join(label for _, label in parts[:3])
    else:
        rule_based_explanation = "no meaningful intent signals found"

    # NOTE: LLM explanation upgrade happens later, only for the top N results
    # after sorting (see enhance_top_explanations) - not here for every brand.
    # Running a local LLM 25 times when only ~5 results matter wastes minutes.
    explanation = rule_based_explanation

    return total, explanation, breakdown, parts


def load_and_score(csv_path):
    """Reads the tiered CSV and returns a list of scored brand dicts, ranked highest first."""
    results = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            brand = row.get("Brand", "").strip()
            if not brand:
                continue  # skip blank rows
            score, explanation, breakdown, parts = score_brand(row)
            intent_level = get_intent_level(score)
            top_category = max(
                {k: v for k, v in breakdown.items() if k != "growth_bonus"}.items(),
                key=lambda kv: kv[1]
            )[0] if any(v > 0 for k, v in breakdown.items() if k != "growth_bonus") else None
            tech_state = row.get("Current_Returns_Vendor_Status", "").strip().upper()

            results.append({
                "brand": brand,
                "score": score,
                "explanation": explanation,
                "breakdown": breakdown,
                "intent_level": intent_level,
                "recommended_action": RECOMMENDED_ACTION[intent_level],
                "top_reasons": [label for _, label in parts[:3]],
                "outreach_angle": get_outreach_angle(top_category, tech_state) if top_category else "No strong signal to anchor a pitch on yet - more research needed.",
                "missing_info": get_missing_info(row),
                "evidence_sources": get_evidence_sources(row),
                "_parts": parts,  # internal use only - feeds the optional LLM upgrade below
            })
    results.sort(key=lambda r: -r["score"])
    return results


def enhance_top_explanations(results, top_n=5):
    """
    Upgrades ONLY the top N results' explanations using the local LLM (if enabled).
    Everyone else keeps the rule-based sentence. This is the key speed decision:
    a local model can take 10-30s per call to warm up/respond, so calling it 25
    times when only the top 5 matter for the memo/outreach would waste minutes
    for no benefit - nobody reads the "why" for rank #20.
    """
    if not USE_LLM_EXPLANATIONS:
        return results
    for r in results[:top_n]:
        parts = r.get("_parts", [])
        if not parts:
            continue
        signal_list = "; ".join(f"{label} ({points} pts)" for points, label in parts)
        llm_result = call_ollama(
            "You are a REWORDING tool, not a judge. A separate rule-based system has "
            "ALREADY decided this brand's score using a fixed point rubric - your only "
            "job is to restate the signals it found, in plain English, as a single "
            "sentence. Do NOT evaluate, judge, or add your own opinion about whether "
            "the brand is doing well or badly. Do NOT say 'scored low' or 'scored high' "
            "- that framing is not your job. Context: a HIGH total score means STRONG "
            "buying intent (good news for our sales team - this brand is a promising "
            "target). Just state the facts you're given, under 20 words, no jargon, "
            "no dashes, no editorializing.",
            f"Signals found: {signal_list}"
        )
        if llm_result:
            r["explanation"] = llm_result
    return results


def save_results(results, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Rank", "Brand", "Score", "Intent_Level", "Recommended_Action",
            "Top_Reasons", "Suggested_Outreach_Angle", "Missing_Information", "Evidence_Sources",
        ])
        for i, r in enumerate(results, start=1):
            writer.writerow([
                i, r["brand"], r["score"], r["intent_level"], r["recommended_action"],
                " | ".join(r["top_reasons"]), r["outreach_angle"],
                ", ".join(r["missing_info"]) if r["missing_info"] else "None - fully researched",
                r["evidence_sources"],
            ])


if __name__ == "__main__":
    INPUT_CSV = "CP-scorebook.csv"
    OUTPUT_CSV = "scored_accounts.csv"

    if USE_LLM_EXPLANATIONS:
        print(f"Using local Ollama ({OLLAMA_MODEL}) to write crisp explanations.")
    else:
        print("LLM explanations off - using rule-based explanations. "
              "Set USE_LLM_EXPLANATIONS=true and run 'ollama serve' to enable.")

    results = load_and_score(INPUT_CSV)
    results = enhance_top_explanations(results, top_n=5)  # only top 5 get the (slower) LLM pass

    print("\n" + "=" * 70)
    print("  CLICKPOST INTENT SCORE — RANKED ACCOUNTS (SDR VIEW)")
    print("=" * 70)

    for i, r in enumerate(results, start=1):
        print(f"\n#{i}  {r['brand'].upper()}   —   {r['score']}/100   [{r['intent_level'].upper()} INTENT]")
        print("-" * 70)
        print(f"  Recommended Action: {r['recommended_action']}")

        print(f"\n  Top Reasons:")
        if r["top_reasons"]:
            for reason in r["top_reasons"]:
                print(f"    • {reason}")
        else:
            print(f"    • No meaningful intent signals found")

        print(f"\n  Suggested Outreach Angle:")
        print(f"    {r['outreach_angle']}")

        print(f"\n  Evidence Sources:")
        print(f"    {r['evidence_sources']}")

        print(f"\n  Missing Information:")
        if r["missing_info"]:
            print(f"    ⚠ {', '.join(r['missing_info'])} - score may be incomplete")
        else:
            print(f"    None - fully researched")

    print("\n" + "=" * 70)

    save_results(results, OUTPUT_CSV)
    print(f"\nSaved full ranked results to {OUTPUT_CSV}")