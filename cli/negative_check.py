from __future__ import annotations

"""Severity classification for negative API test outcomes.

Source of truth for the negative-testing verdict (see
docs/api-negative-testing-reference.md). Pure logic — no DB, no I/O. Mirrors the
shape of cli/schema_diff.py::classify_drift: a fixed-shape verdict object with a
per-case list, counts, and a worst-severity roll-up.

The runner (cli/api_runner.py) performs the mutated sends and the assertion
evaluation, then hands each case's *raw outcome* to `classify`. This module owns
only the severity policy and the aggregation, so it stays trivially testable.

Raw per-case outcome (input to classify), one dict per enabled case:
    {
        "id", "category", "subtype", "target", "label": echoed from the case
        "method": the HTTP method actually sent
        "expected_status": int | None   (the contract's expected code)
        "actual_status": int | None     (None = the send errored / timed out)
        "status_ok": bool               (did the status contract pass — computed
                                         by the runner via _compare)
        "no_500": bool                  (injection guard requested)
        "no_reflect": bool              (injection reflection guard requested)
        "reflected": bool               (payload found verbatim in the body)
        "error": str | None             (transport error message, if any)
    }

Severity policy (fixed):
    - Critical: a false pass (success status where a client error was expected),
      an injection payload reflected, or a 5xx on a fuzzed input.
    - Major: a 5xx crash on an ordinary validation case, or a wholly wrong
      status family.
    - Minor: a rejection with the wrong specific 4xx code.
    - none: the case passed.
"""

_SEVERITY_RANK = {"none": 0, "minor": 1, "major": 2, "critical": 3}


def _is_success(status) -> bool:
    return isinstance(status, int) and status < 400


def _is_server_error(status) -> bool:
    return isinstance(status, int) and status >= 500


def _is_client_error(status) -> bool:
    return isinstance(status, int) and 400 <= status < 500


def classify_case(case: dict) -> dict:
    """Return the case dict enriched with `passed`, `severity`, `false_pass`,
    and a plain-words `note`. Category-aware — injection is judged on
    no-500 / no-reflect, everything else on the expected 4xx contract."""
    out = dict(case)
    category = case.get("category")
    actual = case.get("actual_status")
    expected = case.get("expected_status")

    passed = False
    severity = "minor"
    false_pass = False
    note = ""

    if actual is None:
        # The send never produced a response (transport error / timeout).
        # Inconclusive — never a false pass, never force-fails the run.
        severity = "minor"
        note = case.get("error") or "request did not complete"

    elif category == "injection":
        # An injection payload is handled correctly when the server neither
        # crashes (5xx) nor echoes it back. The specific 2xx/4xx code doesn't
        # matter — safely neutralised input (200) and rejected input (400) are
        # both acceptable.
        if case.get("no_reflect") and case.get("reflected"):
            severity, note = "critical", "payload reflected in the response"
        elif case.get("no_500") and _is_server_error(actual):
            severity, note = "critical", f"server error ({actual}) on a fuzzed input"
        else:
            passed, severity = True, "none"

    else:
        # input-validation / request-level: a specific client error is expected.
        if _is_success(actual):
            severity, false_pass, note = "critical", True, f"accepted invalid input ({actual}) — expected a 4xx rejection"
        elif _is_server_error(actual):
            severity, note = "major", f"server error ({actual}) instead of a client-error rejection"
        elif case.get("status_ok"):
            passed, severity = True, "none"
        elif _is_client_error(actual):
            severity, note = "minor", f"rejected with {actual}, expected {expected}"
        else:
            severity, note = "major", f"unexpected status {actual}"

    out["passed"] = passed
    out["severity"] = severity
    out["false_pass"] = false_pass
    out["note"] = note
    return out


def classify(case_results: list) -> dict:
    """Build the negative_result verdict object from raw per-case outcomes."""
    cases = [classify_case(c) for c in (case_results or [])]

    if not cases:
        return skipped("no-cases")

    total = len(cases)
    passed = sum(1 for c in cases if c["passed"])
    false_pass = sum(1 for c in cases if c["false_pass"])
    worst = "none"
    for c in cases:
        if _SEVERITY_RANK[c["severity"]] > _SEVERITY_RANK[worst]:
            worst = c["severity"]

    by_category: dict[str, dict] = {}
    for c in cases:
        bucket = by_category.setdefault(c.get("category", "other"), {"passed": 0, "total": 0})
        bucket["total"] += 1
        if c["passed"]:
            bucket["passed"] += 1

    # A Critical or Major outcome fails the run; Minor-only or all-pass stays green.
    verdict = "fail" if worst in ("critical", "major") else "pass"

    return {
        "checked": True,
        "verdict": verdict,
        "skipped_reason": None,
        "worst_severity": worst,
        "counts": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "false_pass": false_pass,
        },
        "by_category": by_category,
        "cases": cases,
    }


def skipped(reason: str) -> dict:
    """Verdict object for negatives that did not run (disabled / no cases)."""
    return {
        "checked": False,
        "verdict": "skipped",
        "skipped_reason": reason,
        "worst_severity": "none",
        "counts": {"total": 0, "passed": 0, "failed": 0, "false_pass": 0},
        "by_category": {},
        "cases": [],
    }
