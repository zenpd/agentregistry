"""Classification of an agent: questions on purpose, people affected, data used and
decisions made, and the rules that turn the answers into a suggested EU AI Act
category and a registry risk level, each with the reasons that produced it.
Pure functions. A named person confirms the result (api/routers/ops/classification.py)."""
from __future__ import annotations

from typing import Any, Mapping

CATEGORIES = ("Minimal Risk", "Limited Risk", "High Risk", "Unacceptable Risk")
LEVELS = ("LOW", "MEDIUM", "HIGH")

# Article 5 practices: an agent doing any of these must not be used in the EU.
PROHIBITED = {
    "manipulation": "Influences people's decisions with techniques they are not aware of",
    "exploits_vulnerability": "Exploits people's age, disability or social or economic situation",
    "social_scoring": "Scores people on their social behaviour or personal traits",
    "crime_prediction": "Predicts whether a person will commit a crime from profiling alone",
    "face_scraping": "Builds facial recognition databases by untargeted scraping of images",
    "emotion_at_work": "Infers emotions of people at work or in education",
    "biometric_categorisation": "Sorts people by biometric data into race, beliefs, sexual orientation or similar",
    "realtime_biometric_police": "Identifies people remotely in real time in public spaces for law enforcement",
}
# Annex III areas: an agent used in one of these is high risk.
HIGH_RISK_AREAS = {
    "biometrics": "Biometric identification or categorisation of people",
    "critical_infrastructure": "Safety parts of critical infrastructure (energy, water, transport, digital networks)",
    "education": "Admission to, assessment in or monitoring of education or training",
    "employment": "Hiring, promotion, task allocation or monitoring of workers",
    "essential_services": "Access to essential services: public benefits, credit scoring, life or health insurance pricing, emergency calls",
    "law_enforcement": "Law enforcement",
    "migration": "Migration, asylum or border control",
    "justice": "Justice or democratic processes, such as elections",
}
AUDIENCES = {"staff": "Only people inside the organisation", "public": "Customers or the public", "both": "Both"}
DATA = {
    "none": "No personal data",
    "personal": "Personal data (names, contact details, account data)",
    "special": "Special category data (health, biometrics, ethnic origin, religion, sexual orientation, criminal records)",
}
DECISIONS = {
    "suggests": "It only suggests, and a person decides",
    "decides_reviewed": "It decides, and a person checks the decisions afterwards",
    "decides_alone": "It decides on its own",
}

RETENTION = {
    "not_kept": "Not kept after the request is answered",
    "30_days": "Up to 30 days",
    "1_year": "Up to 1 year",
    "longer": "Longer than 1 year",
    "legal": "As long as a law requires",
}

QUESTIONS = [
    {"key": "prohibited", "kind": "multi", "label": "Does the agent do any of these?",
     "help": "These practices are banned in the EU (EU AI Act Article 5). Leave all unticked if none applies.",
     "options": [{"value": k, "label": v} for k, v in PROHIBITED.items()]},
    {"key": "area", "kind": "single", "label": "Is the agent used in one of these areas?",
     "help": "These are the high-risk areas of EU AI Act Annex III. Choose \"None of these\" if none applies.",
     "options": [{"value": "none", "label": "None of these"}] + [{"value": k, "label": v} for k, v in HIGH_RISK_AREAS.items()]},
    {"key": "narrow_task", "kind": "bool", "label": "In that area, does it only do a narrow preparatory task?",
     "help": "For example, it sorts documents for a person who then assesses them, and it does not profile people. "
             "Article 6(3) can then lower the category. Answer only when an area is chosen above.",
     "showIf": {"key": "area", "not": "none"}},
    {"key": "interacts", "kind": "bool", "label": "Do people talk to the agent directly, or read text, images or audio it generates?",
     "help": "People must then be told they are dealing with AI (EU AI Act Article 50)."},
    {"key": "audience", "kind": "single", "label": "Who is affected by what the agent does?",
     "options": [{"value": k, "label": v} for k, v in AUDIENCES.items()]},
    {"key": "data", "kind": "single", "label": "What data about people does it use?",
     "options": [{"value": k, "label": v} for k, v in DATA.items()]},
    {"key": "retention", "kind": "single", "label": "How long does it keep the personal data it uses?",
     "help": "Include logs and traces that hold personal data. This feeds the data and retention report.",
     "options": [{"value": k, "label": v} for k, v in RETENTION.items()], "showIf": {"key": "data", "not": "none"}},
    {"key": "decisions", "kind": "single", "label": "How are its outputs used?",
     "options": [{"value": k, "label": v} for k, v in DECISIONS.items()]},
]
REQUIRED = ("area", "interacts", "audience", "data", "decisions")


def missing_answers(answers: Mapping[str, Any]) -> list[str]:
    out = [k for k in REQUIRED if answers.get(k) in (None, "")]
    if answers.get("area") not in (None, "", "none") and answers.get("narrow_task") is None:
        out.append("narrow_task")
    if answers.get("data") in ("personal", "special") and not answers.get("retention"):
        out.append("retention")
    return out


def _max_level(*levels: str | None) -> str:
    ranked = [lv for lv in levels if lv in LEVELS]
    return max(ranked, key=LEVELS.index) if ranked else "LOW"


def suggest(answers: Mapping[str, Any], tool_class: str | None = None, tool_source: str | None = None) -> dict:
    """{category, riskLevel, reasons: [str]} from the answers and, when known, the
    highest risk class among the agent's approved tools."""
    reasons: list[str] = []
    banned = [PROHIBITED[p] for p in answers.get("prohibited") or [] if p in PROHIBITED]
    area = answers.get("area") or "none"
    narrow = bool(answers.get("narrow_task"))
    audience, data, decisions = answers.get("audience"), answers.get("data"), answers.get("decisions")

    if banned:
        category = "Unacceptable Risk"
        reasons.append(f"Unacceptable Risk: it does a practice banned by Article 5 ({'. '.join(banned)}). It must not be used in the EU.")
    elif area != "none" and not narrow:
        category = "High Risk"
        reasons.append(f"High Risk: it is used in an Annex III area ({HIGH_RISK_AREAS.get(area, area)}).")
    elif answers.get("interacts"):
        category = "Limited Risk"
        reasons.append("Limited Risk: people talk to it or read what it generates, so they must be told it is AI (Article 50).")
    else:
        category = "Minimal Risk"
        reasons.append("Minimal Risk: no banned practice, no Annex III area and no direct contact with people.")
    if area != "none" and narrow and not banned:
        reasons.append(f"Not High Risk although it works in an Annex III area ({HIGH_RISK_AREAS.get(area, area)}): "
                       "it only does a narrow preparatory task (Article 6(3)). Record why in the note.")

    level = "LOW"
    high = []
    if category in ("High Risk", "Unacceptable Risk"):
        high.append(f"the EU AI Act category is {category}")
    if data == "special":
        high.append("it uses special category data")
    if decisions == "decides_alone" and audience in ("public", "both"):
        high.append("it decides on its own about customers or the public")
    if high:
        level = "HIGH"
        reasons.append(f"Risk level from the answers: HIGH, because {', and '.join(high)}.")
    else:
        medium = []
        if data == "personal":
            medium.append("it uses personal data")
        if decisions in ("decides_alone", "decides_reviewed"):
            medium.append("it makes decisions rather than only suggesting")
        if audience in ("public", "both"):
            medium.append("it affects customers or the public")
        if medium:
            level = "MEDIUM"
            reasons.append(f"Risk level from the answers: MEDIUM, because {', and '.join(medium)}.")
        else:
            reasons.append("Risk level from the answers: LOW, because only staff are affected, no personal data is used and a person makes every decision.")
    if tool_class in LEVELS and LEVELS.index(tool_class) > LEVELS.index(level):
        reasons.append(f"Raised to {tool_class}: it uses a tool approved as {tool_class} ({tool_source or 'see the tool list'}).")
        level = tool_class
    return {"category": category, "riskLevel": level, "reasons": reasons}


def is_lower(category: str, level: str, suggested_category: str, suggested_level: str) -> bool:
    """Whether a confirmed result is below the suggestion, which needs a written reason."""
    return CATEGORIES.index(category) < CATEGORIES.index(suggested_category) or LEVELS.index(level) < LEVELS.index(suggested_level)


MIN_NOTE_WHEN_LOWER = 20
