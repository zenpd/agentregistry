"""Risk register lifecycle: reconciling a scan with stored findings, the
transitions a person may make, and the register's summary views. Pure
functions over plain dicts.

Statuses: open -> acknowledged -> mitigating -> resolved, or accepted until
a date. A scan only moves auto findings (matched by rule_id); manual and
context findings change only through a person, except that an acceptance
past its date reopens any finding.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from governance.risk_categories import CATEGORY_LABELS, SEVERITY_ORDER, SEVERITY_WEIGHT, RiskCategory
from governance.risk_detection import legacy_rule_id

OPEN_STATUSES = ("open", "acknowledged", "mitigating")
# What the register lists by default and what portfolio counts include.
ACTIVE_STATUSES = OPEN_STATUSES + ("accepted",)
ALL_STATUSES = ACTIVE_STATUSES + ("resolved",)
MANUAL_SOURCES = ("manual", "context")
MAX_ACCEPTANCE_DAYS = 365
CATEGORIES = tuple(c.value for c in RiskCategory)

_PROGRESS = {"open": 0, "acknowledged": 1, "mitigating": 2, "resolved": 3}
_ACTION_TARGET = {"acknowledge": "acknowledged", "mitigate": "mitigating", "resolve": "resolved"}
ACTIONS = ("acknowledge", "mitigate", "resolve", "accept", "reopen", "update")
_PAST_TENSE = {
    "acknowledge": "acknowledged",
    "mitigate": "mitigating",
    "resolve": "resolved",
    "accept": "accepted",
    "reopen": "reopened",
}


class RiskValidationError(ValueError):
    pass


def history_entry(now: datetime, by: str, action: str, note: str | None = None) -> dict[str, Any]:
    return {"at": now.isoformat(), "by": by, "action": action, "note": note}


def to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise RiskValidationError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def is_overdue(row: dict[str, Any], today: date) -> bool:
    due = to_date(row.get("due_date"))
    return bool(due and due < today and row.get("status") in OPEN_STATUSES)


def acceptance_expired(row: dict[str, Any], today: date) -> bool:
    if row.get("status") != "accepted":
        return False
    until = to_date(row.get("accepted_until"))
    return until is None or until < today


def _matches_rule(rule_id: str | None, prefixes: Iterable[str]) -> bool:
    return bool(rule_id) and any(rule_id == p or rule_id.startswith(p + ".") for p in prefixes)


class _Change:
    """Accumulates field changes and history entries for one stored row."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.fields: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = list(row.get("history") or [])
        self.actions: list[str] = []

    def set(self, **fields: Any) -> None:
        self.fields.update(fields)

    def log(self, now: datetime, by: str, action: str, note: str | None = None) -> None:
        self.history.append(history_entry(now, by, action, note))
        self.actions.append(action)

    def result(self) -> dict[str, Any]:
        changes = dict(self.fields)
        if self.actions:
            changes["history"] = self.history
        return {"id": self.row["id"], "changes": changes, "actions": list(self.actions)}


def _expire_acceptance(change: _Change, now: datetime) -> None:
    change.set(status="open")
    change.log(now, "system", "acceptance expired", f"Accepted until {change.row.get('accepted_until') or 'no date'}.")


def expire_acceptances(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Updates for every accepted row whose acceptance date has passed."""
    updates = []
    for row in rows:
        if acceptance_expired(row, now.date()):
            change = _Change(row)
            _expire_acceptance(change, now)
            updates.append(change.result())
    return updates


def _index_existing(
    existing_rows: list[dict[str, Any]], detected_by_rule: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict], list[dict], set[str], dict[str, str]]:
    """(rows by rule_id, auto rows no current finding matches, duplicate row
    ids, backfilled rule_id by row id)."""
    by_rule: dict[str, dict[str, Any]] = {}
    legacy: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for row in existing_rows:
        if row.get("source") in MANUAL_SOURCES:
            continue
        rule_id = row.get("rule_id")
        if not rule_id:
            legacy.append(row)
        elif rule_id in by_rule:
            duplicates.append(row)
        else:
            by_rule[rule_id] = row

    detected_by_title = {(f["category"], f["title"]): f["rule_id"] for f in detected_by_rule.values()}
    backfilled: dict[str, str] = {}
    unknown: list[dict[str, Any]] = []
    for row in legacy:
        key = (row.get("category"), row.get("title"))
        rule_id = detected_by_title.get(key) or legacy_rule_id(*key)
        if not rule_id:
            unknown.append(row)
        elif rule_id in by_rule:
            duplicates.append(row)
        else:
            by_rule[rule_id] = row
            backfilled[row["id"]] = rule_id
    cleared = [row for rule_id, row in by_rule.items() if rule_id not in detected_by_rule]
    return by_rule, unknown + cleared + duplicates, {row["id"] for row in duplicates}, backfilled


def reconcile(
    existing_rows: list[dict[str, Any]],
    detected: list[dict[str, Any]],
    now: datetime,
    unevaluated: Iterable[str] = (),
) -> dict[str, Any]:
    """Returns {inserts, updates, closes, counts}. Each update/close is
    {id, changes, actions}; `changes` holds only the fields to write.
    `unevaluated` names rules (or rule_id prefixes) whose input was missing
    this scan: their rows are neither closed nor reopened."""
    today = now.date()
    unevaluated = tuple(unevaluated)
    detected_by_rule = {f["rule_id"]: f for f in detected}
    by_rule, unmatched, duplicate_ids, backfilled = _index_existing(existing_rows, detected_by_rule)

    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    closes: list[dict[str, Any]] = []
    counts = {"inserted": 0, "updated": 0, "reopened": 0, "resolved": 0, "acceptanceExpired": 0,
              "backfilled": len(backfilled), "unchecked": 0}

    for rule_id, finding in detected_by_rule.items():
        row = by_rule.get(rule_id)
        if row is None:
            inserts.append({
                "rule_id": rule_id, "category": finding["category"], "severity": finding["severity"],
                "title": finding["title"], "description": finding.get("description"),
                "source": "auto", "status": "open", "detected_at": now, "last_detected_at": now,
                "history": [history_entry(now, "system", "detected", finding["title"])],
            })
            counts["inserted"] += 1
            continue

        change = _Change(row)
        if row["id"] in backfilled:
            change.set(rule_id=rule_id)
            change.log(now, "system", "rule id backfilled", rule_id)
        if row.get("severity") != finding["severity"]:
            change.log(now, "system", "severity changed", f"{row.get('severity')} -> {finding['severity']}")
        change.set(severity=finding["severity"], title=finding["title"],
                   description=finding.get("description"), last_detected_at=now)

        if row.get("status") == "resolved":
            change.set(status="open", resolved_at=None)
            change.log(now, "system", "reopened", "Condition detected again.")
            counts["reopened"] += 1
        elif acceptance_expired(row, today):
            _expire_acceptance(change, now)
            counts["acceptanceExpired"] += 1
        updates.append(change.result())
        counts["updated"] += 1

    for row in unmatched:
        status = row.get("status")
        rule_id = backfilled.get(row["id"]) or row.get("rule_id")
        change = _Change(row)
        if row["id"] in backfilled:
            change.set(rule_id=rule_id)
            change.log(now, "system", "rule id backfilled", rule_id)
        if acceptance_expired(row, today):
            _expire_acceptance(change, now)
            counts["acceptanceExpired"] += 1
            status = "open"
        is_duplicate = row["id"] in duplicate_ids
        if not is_duplicate and _matches_rule(rule_id, unevaluated):
            counts["unchecked"] += 1
        elif status in OPEN_STATUSES:
            reason = "duplicate of another finding" if is_duplicate else "condition cleared"
            change.set(status="resolved", resolved_at=now)
            change.log(now, "system", f"auto-resolved: {reason}")
            closes.append(change.result())
            counts["resolved"] += 1
            continue
        if change.fields:
            updates.append(change.result())

    manual_rows = [row for row in existing_rows if row.get("source") in MANUAL_SOURCES]
    for update in expire_acceptances(manual_rows, now):
        updates.append(update)
        counts["acceptanceExpired"] += 1

    return {"inserts": inserts, "updates": updates, "closes": closes, "counts": counts}


def _validate_text(value: Any, field: str, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if max_len and len(text) > max_len:
        raise RiskValidationError(f"{field} must be at most {max_len} characters")
    return text or None


def _field_edits(row: dict[str, Any], payload: dict[str, Any], change: _Change) -> list[str]:
    notes = []
    edits = {}
    if "owner" in payload:
        edits["owner"] = _validate_text(payload["owner"], "owner", 255)
    if "mitigation" in payload:
        edits["mitigation"] = _validate_text(payload["mitigation"], "mitigation")
    if "dueDate" in payload:
        edits["due_date"] = to_date(payload["dueDate"])
    for field, value in edits.items():
        before = row.get(field)
        if (to_date(before) if field == "due_date" else before) == value:
            continue
        change.set(**{field: value})
        if field == "mitigation":
            notes.append("mitigation plan updated" if value else "mitigation plan cleared")
        else:
            label = "due date" if field == "due_date" else field
            notes.append(f"{label}: {before or '—'} -> {value or '—'}")
    return notes


def apply_action(row: dict[str, Any], payload: dict[str, Any], actor: str, now: datetime) -> dict[str, Any]:
    """A person's change to one finding. `payload` keys are the API's
    (action, owner, mitigation, dueDate, acceptedUntil, note); only keys
    present are applied. Returns {id, changes, actions}."""
    action = payload.get("action")
    if action not in ACTIONS:
        raise RiskValidationError(f"Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}")
    status = row.get("status") or "open"
    note = _validate_text(payload.get("note"), "note")
    change = _Change(row)
    edits = _field_edits(row, payload, change)

    if action in _ACTION_TARGET:
        target = _ACTION_TARGET[action]
        if status not in _PROGRESS or _PROGRESS[status] >= _PROGRESS[target]:
            raise RiskValidationError(f"Cannot {action} a finding that is '{status}'")
        change.set(status=target)
        if target == "resolved":
            change.set(resolved_at=now)
    elif action == "accept":
        if status not in OPEN_STATUSES:
            raise RiskValidationError(f"Cannot accept a finding that is '{status}'")
        until = to_date(payload.get("acceptedUntil"))
        if until is None:
            raise RiskValidationError("acceptedUntil is required to accept a risk")
        if until < now.date():
            raise RiskValidationError("acceptedUntil must not be in the past")
        if until > now.date() + timedelta(days=MAX_ACCEPTANCE_DAYS):
            raise RiskValidationError(f"acceptedUntil must be within {MAX_ACCEPTANCE_DAYS} days")
        if not actor:
            raise RiskValidationError("accepted_by is required to accept a risk")
        change.set(status="accepted", accepted_until=until, accepted_by=actor)
        note = f"Accepted until {until.isoformat()}" + (f". {note}" if note else "")
    elif action == "reopen":
        if status not in ("resolved", "accepted"):
            raise RiskValidationError(f"Cannot reopen a finding that is '{status}'")
        change.set(status="open", resolved_at=None, accepted_until=None, accepted_by=None)
    elif not edits and not note:
        raise RiskValidationError("Nothing to update")

    if action == "update":
        change.log(now, actor, "updated", "; ".join(edits + ([note] if note else [])))
    else:
        detail = "; ".join(([note] if note else []) + edits) or None
        change.log(now, actor, _PAST_TENSE[action], detail)
    return change.result()


def new_manual_risk(payload: dict[str, Any], actor: str, now: datetime) -> dict[str, Any]:
    category = str(payload.get("category") or "").upper()
    if category not in CATEGORIES:
        raise RiskValidationError(f"category must be one of: {', '.join(CATEGORIES)}")
    severity = str(payload.get("severity") or "").upper()
    if severity not in SEVERITY_ORDER:
        raise RiskValidationError(f"severity must be one of: {', '.join(SEVERITY_ORDER)}")
    title = _validate_text(payload.get("title"), "title", 255)
    if not title:
        raise RiskValidationError("title is required")
    return {
        "rule_id": None, "category": category, "severity": severity, "title": title,
        "description": _validate_text(payload.get("description"), "description"),
        "owner": _validate_text(payload.get("owner"), "owner", 255),
        "due_date": to_date(payload.get("dueDate")),
        "source": "manual", "status": "open", "detected_at": now, "last_detected_at": None,
        "history": [history_entry(now, actor, "created", _validate_text(payload.get("note"), "note"))],
    }


def score(findings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Worst severity and counts over the given (already active) findings."""
    by_severity = {s: 0 for s in SEVERITY_ORDER}
    by_category = {c: 0 for c in CATEGORIES}
    worst = None
    total = 0
    for f in findings:
        severity, category = f.get("severity"), f.get("category")
        if severity not in by_severity or category not in by_category:
            continue
        total += 1
        by_severity[severity] += 1
        by_category[category] += 1
        if worst is None or SEVERITY_WEIGHT[severity] > SEVERITY_WEIGHT[worst]:
            worst = severity
    return {"worst": worst, "total": total, "countsBySeverity": by_severity, "countsByCategory": by_category}


def portfolio_summary(findings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Pie (byCategory) and heatmap (category x severity) shapes."""
    grid = {c: {s: 0 for s in SEVERITY_ORDER} for c in CATEGORIES}
    total = 0
    for f in findings:
        category, severity = f.get("category"), f.get("severity")
        if category not in grid or severity not in SEVERITY_ORDER:
            continue  # a malformed row must never blank the whole summary
        grid[category][severity] += 1
        total += 1
    return {
        "totalFindings": total,
        "byCategory": [
            {"category": c, "label": CATEGORY_LABELS[c], "count": sum(grid[c].values())} for c in CATEGORIES
        ],
        "severities": list(SEVERITY_ORDER),
        "heatmap": [{"category": c, "label": CATEGORY_LABELS[c], "counts": grid[c]} for c in CATEGORIES],
    }
