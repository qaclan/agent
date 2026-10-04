"""Single source of truth for script time budgets.

Runner (web/routes/runs.py), solo run (web/routes/scripts.py) and the suite
timeout preview all call into this module so the preview cannot drift from
what a real run applies. See docs/test-timeout-budget-plan.md.

Three knobs, all in milliseconds:

- wait limit       one value driving both QACLAN_EXPECT_TIMEOUT and
                   QACLAN_ACTION_TIMEOUT
- max script time  hard ceiling for one script; the subprocess kill is
                   derived from it (+ KILL_MARGIN_MS) so the in-process test
                   timeout always fires first
- test timeout     per-test timeout for @playwright/test strategies; `auto`
                   (scaled from the action count) unless a fixed value is set
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from cli.script_strategies._shared import extract_between_harness_markers

# ---- Built-in defaults and limits ------------------------------------------

DEFAULT_WAIT_TIMEOUT = 15000
ALLOWED_WAIT_TIMEOUTS = frozenset({5000, 10000, 15000, 30000, 45000, 60000})

DEFAULT_MAX_SCRIPT_TIME = 280000
MIN_MAX_SCRIPT_TIME = 60000
MAX_MAX_SCRIPT_TIME = 1800000

# Subprocess kill = max script time + this margin.
KILL_MARGIN_MS = 20000

# Auto test timeout: min(CAP, max(FLOOR, BASE + PER_ACTION * n_actions)).
# FLOOR = wait limit + FLOOR_HEADROOM_MS, i.e. the previous flat formula, so
# no script ever gets a shorter budget than before. Recalibrate here only.
TEST_TIMEOUT_BASE_MS = 30000
TEST_TIMEOUT_PER_ACTION_MS = 5000
FLOOR_HEADROOM_MS = 60000
MIN_FIXED_TEST_TIMEOUT = 30000

# Estimates (preview only). Typical rates come from local run history:
# ~10s browser start, ~2.5s per action. Worst case adds every settle running
# to its own soft cap (_waitForNetworkSettle never throws on the cap).
ESTIMATE_STARTUP_MS = 10000
ESTIMATE_PER_ACTION_MS = 2500
SETTLE_SOFT_CAP_MS = 15000

# Strategies that run under @playwright/test and therefore have a per-test
# timeout. The others are limited only by the max script time.
TEST_TIMEOUT_LANGUAGES = frozenset({"javascript_test", "typescript_test"})

# Levels reported by the resolvers.
LEVEL_SCRIPT = "script"
LEVEL_RUN = "run"
LEVEL_SUITE = "suite"
LEVEL_PROJECT = "project"
LEVEL_DEFAULT = "default"
LEVEL_AUTO = "auto"


# ---- Validation helpers ----------------------------------------------------

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def valid_wait_timeout(v) -> bool:
    return _is_int(v) and v in ALLOWED_WAIT_TIMEOUTS


def valid_max_script_time(v) -> bool:
    return _is_int(v) and MIN_MAX_SCRIPT_TIME <= v <= MAX_MAX_SCRIPT_TIME


def valid_fixed_test_timeout(v, cap: int = MAX_MAX_SCRIPT_TIME) -> bool:
    return _is_int(v) and MIN_FIXED_TEST_TIMEOUT <= v <= cap


SETTING_KEYS = ("wait_timeout", "test_timeout", "max_script_time")


def validate_settings(payload, current=None, parent=None):
    """Validate a project/suite settings save.

    ``payload`` holds only the keys the caller sent (null clears). ``current``
    is the entity's stored values (mapping or None); ``parent`` is the level
    above (project for a suite, None for a project) and only supplies the cap.

    Returns (updates, error). ``updates`` maps each sent key to the value to
    store; on any violation ``updates`` is None and ``error`` is a message and
    nothing should be stored. A fixed test timeout is checked against the max
    script time that will be in effect after this save.
    """
    def get(row, name):
        if row is None:
            return None
        try:
            return row[name]
        except (KeyError, IndexError):
            return None

    updates = {}
    for key in SETTING_KEYS:
        if key not in payload:
            continue
        v = payload[key]
        if v is None:
            updates[key] = None
            continue
        if key == "wait_timeout" and not valid_wait_timeout(v):
            allowed = ", ".join(str(x) for x in sorted(ALLOWED_WAIT_TIMEOUTS))
            return None, f"wait_timeout must be one of: {allowed} (ms) or null"
        if key == "max_script_time" and not valid_max_script_time(v):
            return None, (f"max_script_time must be an integer from {MIN_MAX_SCRIPT_TIME} "
                          f"to {MAX_MAX_SCRIPT_TIME} (ms) or null")
        if key == "test_timeout" and not (_is_int(v) and v >= MIN_FIXED_TEST_TIMEOUT):
            return None, f"test_timeout must be an integer of at least {MIN_FIXED_TEST_TIMEOUT} (ms) or null (auto)"
        updates[key] = v

    def after(key):
        return updates[key] if key in updates else get(current, key)

    test_timeout = after("test_timeout")
    if test_timeout is not None:
        cap, _ = resolve_max_script_time(after("max_script_time"), get(parent, "max_script_time"))
        if test_timeout > cap:
            return None, (f"test_timeout ({test_timeout}) cannot exceed the max script time "
                          f"({cap}); raise max_script_time or lower test_timeout")
    return updates, None


def _col(row, name):
    """Read an optional column from a sqlite3.Row / dict / None."""
    if row is None:
        return None
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


# ---- Resolution chains -----------------------------------------------------

def resolve_wait_timeout(script=None, run_pick=None, suite=None, project=None) -> Tuple[int, str]:
    """Highest wins: script > run dialog pick > suite > project > default.

    Each argument is the raw value (int or None). Values outside the allowed
    set are ignored rather than trusted, matching the previous runner.
    """
    for value, level in (
        (script, LEVEL_SCRIPT),
        (run_pick, LEVEL_RUN),
        (suite, LEVEL_SUITE),
        (project, LEVEL_PROJECT),
    ):
        if valid_wait_timeout(value):
            return value, level
    return DEFAULT_WAIT_TIMEOUT, LEVEL_DEFAULT


def resolve_max_script_time(suite=None, project=None) -> Tuple[int, str]:
    """Suite > project > default. A solo run passes suite=None."""
    for value, level in ((suite, LEVEL_SUITE), (project, LEVEL_PROJECT)):
        if valid_max_script_time(value):
            return value, level
    return DEFAULT_MAX_SCRIPT_TIME, LEVEL_DEFAULT


def resolve_fixed_test_timeout(suite=None, project=None) -> Tuple[Optional[int], str]:
    """Suite > project. None means auto. Range is checked against the cap by
    compute_test_timeout (which clamps) and on save (which rejects)."""
    for value, level in ((suite, LEVEL_SUITE), (project, LEVEL_PROJECT)):
        if valid_fixed_test_timeout(value):
            return value, level
    return None, LEVEL_AUTO


# ---- Step counting ---------------------------------------------------------

# Calls that cost real time. Same names in all strategies except Python's
# snake_case select_option.
_ACTION_RE = re.compile(
    r"\.(?:goto|click|fill|selectOption|select_option|check|uncheck|press|hover|dblclick)\("
)


def _action_block(source: str) -> str:
    block = extract_between_harness_markers(source)
    return source if block is None else block


def count_steps(source: str, strategy) -> dict:
    """Return {'actions': int, 'settles': int} for ``source``.

    Counts only the action block between BEGIN/END ACTIONS when the harness
    markers exist (the whole source otherwise). Comment-only lines are
    ignored. Settles use the strategy's own settle marker.
    """
    marker = strategy.settle_marker()
    actions = 0
    settles = 0
    for line in _action_block(source or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        if marker in line:
            settles += 1
            continue
        if _ACTION_RE.search(line):
            actions += 1
    return {"actions": actions, "settles": settles}


# ---- Test timeout ----------------------------------------------------------

def has_test_timeout(language: str) -> bool:
    return language in TEST_TIMEOUT_LANGUAGES


def test_timeout_floor(wait_timeout: int) -> int:
    return wait_timeout + FLOOR_HEADROOM_MS


def compute_test_timeout(n_actions: int, wait_timeout: int, cap: int,
                         fixed: Optional[int] = None) -> int:
    """Per-test timeout in ms.

    fixed -> min(fixed, cap) (clamped if a lower level reduced the cap).
    auto  -> min(cap, max(floor, BASE + PER_ACTION * n_actions)).
    """
    if fixed is not None:
        return min(fixed, cap)
    formula = TEST_TIMEOUT_BASE_MS + TEST_TIMEOUT_PER_ACTION_MS * max(0, n_actions)
    return min(cap, max(test_timeout_floor(wait_timeout), formula))


def subprocess_timeout_sec(cap: int) -> float:
    """Subprocess kill in seconds: max script time + margin."""
    return (cap + KILL_MARGIN_MS) / 1000.0


def estimate(n_actions: int, n_settles: int, wait_timeout: int, cap: int,
             fixed: Optional[int] = None, language: str = "javascript_test") -> dict:
    """Preview numbers for one script.

    Returns {test_timeout, typical_ms, worst_ms, over_cap, clamped}.
    test_timeout is None for strategies without a per-test timeout. worst
    assumes every settle runs to its soft cap; over_cap compares it with the
    max script time. clamped is True when a fixed test timeout was reduced by
    the cap.
    """
    typical = ESTIMATE_STARTUP_MS + ESTIMATE_PER_ACTION_MS * max(0, n_actions)
    worst = typical + SETTLE_SOFT_CAP_MS * max(0, n_settles)
    test_timeout = None
    clamped = False
    if has_test_timeout(language):
        test_timeout = compute_test_timeout(n_actions, wait_timeout, cap, fixed)
        clamped = fixed is not None and fixed > cap
    return {
        "test_timeout": test_timeout,
        "typical_ms": typical,
        "worst_ms": worst,
        "over_cap": worst > cap,
        "clamped": clamped,
    }


# ---- Convenience for callers ----------------------------------------------

def resolve_for_script(*, language: str, source: str, strategy,
                       script_wait=None, run_pick=None,
                       suite=None, project=None) -> dict:
    """Resolve every budget value for one script in one call.

    ``suite`` / ``project`` are mappings (sqlite3.Row or dict) or None, read
    for the optional wait_timeout / test_timeout / max_script_time columns.
    Returns a dict the runner exports and records:

      wait_timeout, wait_level, max_script_time, max_level,
      test_timeout (None when the strategy has none), test_mode
      ('auto' | 'fixed'), test_level, subprocess_timeout_sec, steps
    """
    def col(row, name):
        if row is None:
            return None
        try:
            return row[name]
        except (KeyError, IndexError):
            return None

    wait, wait_level = resolve_wait_timeout(
        script_wait, run_pick, col(suite, "wait_timeout"), col(project, "wait_timeout"))
    cap, cap_level = resolve_max_script_time(
        col(suite, "max_script_time"), col(project, "max_script_time"))
    fixed, fixed_level = resolve_fixed_test_timeout(
        col(suite, "test_timeout"), col(project, "test_timeout"))
    steps = count_steps(source, strategy)
    test_timeout = None
    if has_test_timeout(language):
        test_timeout = compute_test_timeout(steps["actions"], wait, cap, fixed)
    return {
        "wait_timeout": wait,
        "wait_level": wait_level,
        "max_script_time": cap,
        "max_level": cap_level,
        "test_timeout": test_timeout,
        "test_mode": "fixed" if fixed is not None else "auto",
        "test_level": fixed_level,
        "subprocess_timeout_sec": subprocess_timeout_sec(cap),
        "steps": steps,
    }


# ---- Run record ------------------------------------------------------------

_LEVEL_WORDS = {
    LEVEL_SCRIPT: "script",
    LEVEL_RUN: "run dialog",
    LEVEL_SUITE: "suite",
    LEVEL_PROJECT: "project",
    LEVEL_DEFAULT: "built-in default",
    LEVEL_AUTO: "auto",
}


def suite_snapshot(run_pick=None, suite=None, project=None) -> dict:
    """Suite-level timeout configuration for a run, stored as JSON on
    suite_runs.timeout_config. Excludes per-script overrides (those are on
    script_runs.effective_*). Each value carries the level it came from."""
    def col(row, name):
        if row is None:
            return None
        try:
            return row[name]
        except (KeyError, IndexError):
            return None

    wait, wait_level = resolve_wait_timeout(
        None, run_pick, col(suite, "wait_timeout"), col(project, "wait_timeout"))
    cap, cap_level = resolve_max_script_time(
        col(suite, "max_script_time"), col(project, "max_script_time"))
    fixed, fixed_level = resolve_fixed_test_timeout(
        col(suite, "test_timeout"), col(project, "test_timeout"))
    return {
        "run_pick": run_pick if valid_wait_timeout(run_pick) else None,
        "wait_timeout": {"value": wait, "source": wait_level},
        "test_timeout": {
            "mode": "fixed" if fixed is not None else "auto",
            "value": fixed,
            "source": fixed_level,
        },
        "max_script_time": {"value": cap, "source": cap_level},
        "subprocess_timeout_sec": subprocess_timeout_sec(cap),
    }


def _secs(ms) -> str:
    s = ms / 1000
    return f"{int(s)}s" if s == int(s) else f"{s:g}s"


def describe_snapshot(snapshot, effective_test_timeout=None) -> Optional[str]:
    """Plain-words summary of a stored snapshot, e.g.
    "wait limit 15s from suite, test timeout 130s auto, max script time 280s
    from project". Returns None for a missing/unreadable snapshot (runs from
    before the record existed). ``effective_test_timeout`` is a script's own
    computed test timeout; without it the mode alone is shown.
    """
    if not isinstance(snapshot, dict):
        return None
    try:
        w = snapshot["wait_timeout"]
        t = snapshot["test_timeout"]
        m = snapshot["max_script_time"]
        parts = [f"wait limit {_secs(w['value'])} from {_LEVEL_WORDS.get(w['source'], w['source'])}"]
        if t["mode"] == "fixed":
            parts.append(f"test timeout {_secs(t['value'])} fixed from {_LEVEL_WORDS.get(t['source'], t['source'])}")
        elif effective_test_timeout:
            parts.append(f"test timeout {_secs(effective_test_timeout)} auto")
        else:
            parts.append("test timeout auto")
        parts.append(f"max script time {_secs(m['value'])} from {_LEVEL_WORDS.get(m['source'], m['source'])}")
        return ", ".join(parts)
    except (KeyError, TypeError):
        return None


# ---- Suite preview ---------------------------------------------------------

NEAR_BUDGET_RATIO = 0.8


def preview_script_row(*, language: str, source: str, strategy, script_wait=None,
                       suite=None, project=None, last_duration_ms=None) -> dict:
    """One row of the suite timeout preview, built from the same resolver the
    runner uses so the numbers match what a run then records."""
    b = resolve_for_script(language=language, source=source, strategy=strategy,
                           script_wait=script_wait, suite=suite, project=project)
    fixed, _ = resolve_fixed_test_timeout(_col(suite, "test_timeout"), _col(project, "test_timeout"))
    est = estimate(b["steps"]["actions"], b["steps"]["settles"], b["wait_timeout"],
                   b["max_script_time"], fixed, language)
    # The budget this script is actually held to: its test timeout, else the cap.
    budget = b["test_timeout"] if b["test_timeout"] is not None else b["max_script_time"]
    used = None
    if last_duration_ms is not None and budget:
        used = last_duration_ms / budget
    return {
        "language": language,
        "actions": b["steps"]["actions"],
        "settles": b["steps"]["settles"],
        "wait_timeout": b["wait_timeout"],
        "wait_source": b["wait_level"],
        "test_timeout": b["test_timeout"],
        "test_mode": b["test_mode"] if b["test_timeout"] is not None else None,
        "max_script_time": b["max_script_time"],
        "budget_ms": budget,
        "typical_ms": est["typical_ms"],
        "worst_ms": est["worst_ms"],
        "over_cap": est["over_cap"],
        "clamped": est["clamped"],
        "last_duration_ms": last_duration_ms,
        "budget_used": used,
        "near_budget": used is not None and used > NEAR_BUDGET_RATIO,
    }
