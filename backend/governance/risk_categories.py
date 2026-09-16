"""The fixed risk-category taxonomy — six categories, closed set.

Not a free-text field anywhere in this codebase: a category is one of these
six, always, so a pie/heatmap never has to handle an unbounded legend. Five
are stored in AgentRisk (see db/models.py); FINANCIAL is deliberately NOT
stored there — it's derived live from the existing WasteFinding/CostAnomaly
tables so the two concepts never drift out of sync with each other.
"""

from __future__ import annotations

import enum


class RiskCategory(str, enum.Enum):
    SECURITY = "SECURITY"
    DATA_PRIVACY = "DATA_PRIVACY"
    OPERATIONAL = "OPERATIONAL"
    FINANCIAL = "FINANCIAL"
    COMPLIANCE = "COMPLIANCE"
    REPUTATIONAL = "REPUTATIONAL"


CATEGORY_LABELS: dict[str, str] = {
    RiskCategory.SECURITY: "Security",
    RiskCategory.DATA_PRIVACY: "Data Privacy",
    RiskCategory.OPERATIONAL: "Operational",
    RiskCategory.FINANCIAL: "Financial",
    RiskCategory.COMPLIANCE: "Compliance",
    RiskCategory.REPUTATIONAL: "Reputational",
}

# Fixed severity ladder, low to high — every risk-producing module in this
# package picks from exactly these four, so a heatmap's color scale is
# always the same four steps regardless of which signal produced the row.
SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SEVERITY_WEIGHT: dict[str, int] = {s: i + 1 for i, s in enumerate(SEVERITY_ORDER)}


def max_severity(severities: list[str]) -> str:
    """The single worst severity in a list, defaulting to LOW for an empty
    list (no findings is the good case, not an error)."""
    if not severities:
        return "LOW"
    return max(severities, key=lambda s: SEVERITY_WEIGHT.get(s, 0))
