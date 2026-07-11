"""
activator.py
--------------------
Layer 4 of the ClickPost intent pipeline: takes the top 5 scored accounts
and generates 1 LinkedIn message + 1 follow-up email each, explicitly
grounded in that brand's single strongest signal (not generic AI copy).

INPUT:  scored_accounts.csv (output of score.py)
        + the original research CSV (for the raw signal text/detail)
OUTPUT: outreach_top5.csv - one row per brand with both messages


"""

import csv
import os
import json
import urllib.request
import urllib.error
from score import load_and_score  # reuse Stage 3's scoring + breakdown logic

RAW_CSV = "CP-scorebook.csv"
SCORED_CSV = "scored_accounts.csv"
OUTPUT_CSV = "outreach_top5.csv"
TOP_N = 5

# Groq - hosted, free-tier API for open-weight models (Llama 3.3 etc).
# Chosen over local Ollama so a reviewer can run this with just a free API key,
# no local model install required.
# Ollama - runs fully locally, no API key, no network/Cloudflare issues.
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
USE_LLM_EXPLANATIONS = os.environ.get("USE_LLM_EXPLANATIONS", "").lower() == "true"

# Maps each scoring category to the raw research column that holds the
# actual sentence a human wrote about that signal - this is the text we
# quote from in the outreach, not the tier code.
CATEGORY_TO_RAW_COLUMN = {
    "complaints": "Customer Complaints ",
    "leadership": "New Joinee (new CTO/CX/Founder)",
    "tech_stack": "Current Vendor",
    "hiring": "Hiring (Job Postings/ Listings for CTO/CXH)",
}


def load_raw_research(csv_path):
    """Returns {brand_name: row_dict} for the original research columns."""
    raw = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            brand = row.get("Brand", "").strip()
            if brand:
                raw[brand] = row
    return raw


def strongest_category(breakdown):
    """
    Picks the single highest-scoring category from the breakdown dict.
    Growth is intentionally excluded here - it's a multiplier on another
    signal, not a standalone hook a sales message can point to.
    """
    core = {k: v for k, v in breakdown.items() if k != "growth_bonus"}
    return max(core, key=core.get)


def call_ollama(system_prompt, user_prompt):
    """
    Calls a local Ollama server. Returns the generated text, or None if the
    call fails for any reason (Ollama not running, model not pulled, etc).
    Callers must fall back to the template version on None - the pipeline
    should never crash or go silent just because the LLM step failed.
    """
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["message"]["content"].strip()
    except Exception as e:
        print(f"  [Ollama call failed - {type(e).__name__}: {e}. Is 'ollama serve' running, and is '{OLLAMA_MODEL}' pulled?]")
        return None


# Shared grounding rule given to the LLM for every message - this is the
# guardrail that keeps output traceable back to real research instead of
# the model inventing plausible-sounding but fabricated details.
GROUNDING_RULE = (
    "You are writing on behalf of an SDR at ClickPost, a post-purchase/returns "
    "software company for D2C brands. You MUST reference ONLY the specific fact "
    "given below - do not invent any other detail, statistic, name, or event about "
    "the brand. Do not use generic filler like 'I hope this finds you well.' "
    "Keep it short, specific, and human - like a real SDR would write, not a template."
)


def build_linkedin_message_llm(brand, category, signal_text, tech_state):
    angle = {
        ("tech_stack", "NT"): "they have no returns platform (manual process) - lead with the value/ROI of fixing that",
        ("tech_stack", "C"): "they use a competitor tool but still have complaints - lead with curiosity about whether it's actually working, not a hard pitch (this is a harder sell, keep it low-pressure)",
    }.get((category, tech_state), f"their {category.replace('_', ' ')} signal below")

    user_prompt = (
        f"Brand: {brand}\n"
        f"Signal category: {category}\n"
        f"Specific researched fact: \"{signal_text}\"\n"
        f"Angle: {angle}\n\n"
        f"Write a short LinkedIn connection/outreach message (3-4 sentences max) "
        f"that references this fact directly and ends with a soft ask for a quick chat."
    )
    result = call_ollama(GROUNDING_RULE, user_prompt)
    if result:
        return result
    return build_linkedin_message(brand, category, signal_text, tech_state)  # template fallback


def build_email_llm(brand, category, signal_text, tech_state):
    angle = {
        ("tech_stack", "NT"): "they have no returns platform (manual process) - lead with the value/ROI of fixing that",
        ("tech_stack", "C"): "they use a competitor tool but still have complaints - lead with curiosity about whether it's actually working, not a hard pitch",
    }.get((category, tech_state), f"their {category.replace('_', ' ')} signal below")

    user_prompt = (
        f"Brand: {brand}\n"
        f"Signal category: {category}\n"
        f"Specific researched fact: \"{signal_text}\"\n"
        f"Angle: {angle}\n\n"
        f"Write a short follow-up cold email (under 120 words) with a subject line. "
        f"Format your response as:\nSUBJECT: <subject line>\nBODY: <email body>\n"
        f"Reference the fact directly, end with a specific, low-friction ask (e.g. 15 min call)."
    )
    result = call_ollama(GROUNDING_RULE, user_prompt)
    if result and "SUBJECT:" in result and "BODY:" in result:
        subject = result.split("SUBJECT:")[1].split("BODY:")[0].strip()
        body = result.split("BODY:")[1].strip()
        return subject, body
    return build_email(brand, category, signal_text, tech_state)  # template fallback


def build_linkedin_message(brand, category, signal_text, tech_state):
    """
    Builds a short LinkedIn message. Angle changes based on WHICH signal
    is strongest, per Mimi's clarified pitch logic:
      - no current tool (NT)      -> lead with value/ROI of adding a fix
      - competitor + complaints (C) -> lead with "is our solution better
        than the incumbent, is switching worth it" (this is the HARDER
        sell per her notes, so keep it low-pressure/curious in tone)
      - everything else            -> lead with the specific signal itself
    """
    if category == "tech_stack" and tech_state == "NT":
        hook = (f"Noticed {brand} is currently handling returns manually - "
                 f"({signal_text.strip()}). Most teams at your stage end up losing real "
                 f"revenue to that gap before they realize it.")
        ask = "Worth a quick chat on what a dedicated returns flow could save you?"
    elif category == "tech_stack" and tech_state == "C":
        hook = (f"Saw {brand} is on a returns platform already, but this stood out: "
                 f"{signal_text.strip()}")
        ask = "Curious whether the current setup is actually solving that, or just routing around it?"
    elif category == "complaints":
        hook = f"Came across this about {brand}'s post-purchase experience: {signal_text.strip()}"
        ask = "This is exactly the kind of thing ClickPost is built to fix - open to a quick chat?"
    elif category == "leadership":
        hook = f"Saw the news on {brand}'s leadership: {signal_text.strip()}"
        ask = "New leadership usually means a fresh look at the vendor stack - happy to share how ClickPost fits in if useful."
    elif category == "hiring":
        hook = f"Noticed {brand} is hiring for this: {signal_text.strip()}"
        ask = "Usually a sign the current post-purchase setup needs backup - worth a quick conversation?"
    else:
        hook = f"Been following {brand}'s post-purchase experience lately."
        ask = "Would love to share how ClickPost could help."

    return f"Hi [First Name] - {hook} {ask}"


def build_email(brand, category, signal_text, tech_state):
    subject = f"Quick note on {brand}'s post-purchase experience"

    if category == "tech_stack" and tech_state == "NT":
        body = (f"Hi [First Name],\n\n"
                 f"Following up on my LinkedIn note - I noticed {brand} appears to handle "
                 f"returns manually right now ({signal_text.strip()}).\n\n"
                 f"At your order volume, that usually means real revenue leaking through slow refunds, "
                 f"manual support load, or lost repeat customers. ClickPost automates that flow end-to-end - "
                 f"happy to walk through what it could look like for {brand} specifically, no pressure.\n\n"
                 f"Worth 15 minutes?")
    elif category == "tech_stack" and tech_state == "C":
        body = (f"Hi [First Name],\n\n"
                 f"Following up on my note - {brand} looks to already be on a returns platform, "
                 f"but I came across this: {signal_text.strip()}\n\n"
                 f"That's usually a sign the current tool isn't fully solving the problem it was brought in for. "
                 f"I'd rather show you concretely where ClickPost is different than make a generic pitch - "
                 f"open to a short call to see if a switch is even worth the effort?")
    elif category == "complaints":
        body = (f"Hi [First Name],\n\n"
                 f"Following up on my note - I came across this about {brand}: {signal_text.strip()}\n\n"
                 f"This is squarely the kind of post-purchase friction ClickPost is built to fix - "
                 f"faster refunds, fewer manual escalations, better retention. Happy to share a few "
                 f"specific examples relevant to {brand}'s situation if useful.")
    elif category == "leadership":
        body = (f"Hi [First Name],\n\n"
                 f"Following up - saw this about {brand}'s leadership: {signal_text.strip()}\n\n"
                 f"New leadership is often a good moment to revisit the post-purchase stack. "
                 f"Happy to share how ClickPost has helped similar teams if it's useful timing.")
    elif category == "hiring":
        body = (f"Hi [First Name],\n\n"
                 f"Following up - noticed {brand} is hiring for: {signal_text.strip()}\n\n"
                 f"That's often a sign the current post-purchase process needs more support than "
                 f"the team can give it manually. ClickPost might save you from needing to solve this "
                 f"purely through headcount - worth a quick look?")
    else:
        body = f"Hi [First Name],\n\nWould love to share how ClickPost could help {brand}'s post-purchase experience."

    return subject, body


def generate_outreach():
    scored = load_and_score(RAW_CSV)
    raw = load_raw_research(RAW_CSV)
    top5 = scored[:TOP_N]

    results = []
    for entry in top5:
        brand = entry["brand"]
        breakdown = entry["breakdown"]
        category = strongest_category(breakdown)

        raw_row = raw.get(brand, {})
        column_name = CATEGORY_TO_RAW_COLUMN.get(category)
        signal_text = raw_row.get(column_name, "").strip() if column_name else ""
        tech_state = raw_row.get("Current_Returns_Vendor_Status", "").strip().upper()

        if not signal_text or signal_text.lower().startswith("not yet"):
            # Safety net: don't generate a message pointing at empty/unresearched data.
            signal_text = "[NO VERIFIED SIGNAL TEXT FOUND - DO NOT SEND, RESEARCH GAP]"

        linkedin_msg = build_linkedin_message_llm(brand, category, signal_text, tech_state)
        subject, email_body = build_email_llm(brand, category, signal_text, tech_state)

        results.append({
            "brand": brand,
            "score": entry["score"],
            "strongest_signal_category": category,
            "linkedin_message": linkedin_msg,
            "email_subject": subject,
            "email_body": email_body,
        })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "brand", "score", "strongest_signal_category",
            "linkedin_message", "email_subject", "email_body"
        ])
        writer.writeheader()
        writer.writerows(results)

    return results


if __name__ == "__main__":
    if USE_LLM_EXPLANATIONS:
        print(f"Using local Ollama ({OLLAMA_MODEL}) for outreach generation.")
    else:
        print("LLM generation off - using templates instead. "
              "Set USE_LLM_EXPLANATIONS=true and run 'ollama serve' to enable.")
    results = generate_outreach()
    print(f"\n=== Outreach generated for top {TOP_N} accounts ===\n")
    for r in results:
        print(f"--- {r['brand']} (Score: {r['score']}, driven by: {r['strongest_signal_category']}) ---")
        print(f"LinkedIn: {r['linkedin_message']}\n")
        print(f"Email Subject: {r['email_subject']}")
        print(f"Email Body:\n{r['email_body']}\n")
        print("=" * 70 + "\n")
    print(f"Saved to {OUTPUT_CSV}")