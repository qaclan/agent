from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, SCRIPTS_DIR, get_sensitive_field_patterns, SECRET_CATEGORIES, get_editor_mode
from cli.script_strategies import SUPPORTED_LANGUAGES, get_strategy
from cli.script_strategies._shared import (
    scan_var_keys as _scan_var_keys,
    detect_qaclan_harness,
    extract_between_harness_markers,
    ImportWarning,
)

logger = logging.getLogger("qaclan.record")

bp = Blueprint('scripts', __name__)


def _require_active_project():
    return get_active_project_id()


@bp.route('/api/scripts/sensitive-patterns', methods=['GET'])
def get_sensitive_patterns():
    """Return the active sensitive field patterns for client-side field detection."""
    try:
        return jsonify({
            "ok": True,
            "patterns": get_sensitive_field_patterns(),
            "secret_categories": list(SECRET_CATEGORIES),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# Default-tick heuristic for Scan & Add Smart Waits (auto-wait-plan.md §4.5).
# A button/generic click whose locator name contains one of these words
# usually sends a request or loads data. Navigational roles (link, row, etc.)
# and getByText clicks are recommended by role on the client, independent of
# this list.
_WAIT_RECOMMEND_WORDS = [
    "login", "log in", "signin", "sign in", "signup", "sign up",
    "submit", "search", "save", "continue", "next", "apply", "create",
    "add", "delete", "remove", "update", "refresh", "load", "list", "view",
    "open", "go", "send", "confirm", "ok", "run", "filter", "fetch",
    "import", "export", "upload", "download", "proceed", "finish",
]


@bp.route('/api/scripts/wait-config', methods=['GET'])
def get_wait_config():
    """Return per-language config for the Scan & Add Smart Waits flow.

    The scan/rewrite runs client-side (mirroring Scan & Bind); this serves the
    language-specific settle snippet, the already-waited marker, and the
    default-tick word list. See docs/auto-wait-plan.md §5.3.
    """
    try:
        language = (request.args.get('language') or '').strip()
        if language not in SUPPORTED_LANGUAGES:
            return jsonify({
                "ok": False,
                "error": f"Unknown language '{language}'. "
                         f"Expected one of {sorted(SUPPORTED_LANGUAGES)}.",
            }), 400
        strategy = get_strategy(language)
        return jsonify({
            "ok": True,
            "settle_snippet": strategy.settle_call_snippet(),
            "settle_marker": strategy.settle_marker(),
            "recommend_words": _WAIT_RECOMMEND_WORDS,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# Default-tick heuristics for Scan & Convert Search Inputs
# (docs/typed-input-plan.md §4.3, docs/review-wizard-plan.md §3.2).
#
# Three tiers, scored top-to-bottom on the locator-chain source text:
# - high_confidence_signals: semantic role / type markers — searchbox / combobox
#   / type=search inputs are typed-search by definition.
# - keyword_signals: name / placeholder / label / aria-label tokens that
#   strongly suggest a search or filter field.
# - short_name_signals: whole-word matches inside name= / id= arguments —
#   conventional short identifiers for search inputs.
_TYPED_INPUT_HIGH_CONFIDENCE_SIGNALS = [
    "getByRole('searchbox'",
    "getByRole(\"searchbox\"",
    "getByRole('combobox'",
    "getByRole(\"combobox\"",
    "get_by_role('searchbox'",
    "get_by_role(\"searchbox\"",
    "get_by_role('combobox'",
    "get_by_role(\"combobox\"",
    "type=\"search\"",
    "type='search'",
]

_TYPED_INPUT_KEYWORD_SIGNALS = [
    "search", "filter", "query", "find", "lookup",
    "autocomplete", "suggest", "typeahead", "keyword",
    "search by", "type to search", "start typing", "search anything",
]

_TYPED_INPUT_SHORT_NAME_SIGNALS = ["q", "s", "searchTerm", "keyword"]


@bp.route('/api/scripts/typed-input-config', methods=['GET'])
def get_typed_input_config():
    """Return per-language config for the Scan & Convert Search Inputs flow.

    The scan/rewrite runs client-side; this serves the language-specific
    `.fill(` anchor, the already-converted marker, the rewrite template, and
    the confidence-tier signal lists. See docs/typed-input-plan.md §4.3 and
    docs/review-wizard-plan.md §3.2.
    """
    try:
        language = (request.args.get('language') or '').strip()
        if language not in SUPPORTED_LANGUAGES:
            return jsonify({
                "ok": False,
                "error": f"Unknown language '{language}'. "
                         f"Expected one of {sorted(SUPPORTED_LANGUAGES)}.",
            }), 400
        strategy = get_strategy(language)
        return jsonify({
            "ok": True,
            "fill_marker": strategy.fill_call_marker(),
            "typed_marker": strategy.typed_fill_marker(),
            "typed_call_template": strategy.typed_fill_call_template(),
            "high_confidence_signals": _TYPED_INPUT_HIGH_CONFIDENCE_SIGNALS,
            "keyword_signals": _TYPED_INPUT_KEYWORD_SIGNALS,
            "short_name_signals": _TYPED_INPUT_SHORT_NAME_SIGNALS,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/settings', methods=['GET'])
def get_settings():
    """Return agent settings the frontend needs on startup."""
    try:
        return jsonify({
            "ok": True,
            "settings": {
                "editor_mode": get_editor_mode(),
            },
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


_MAX_IMPORT_BYTES = 256 * 1024

# Per-script "Wait limit" override (Layer 2, expect-timeout-strategy-plan.md).
# NULL/None means "inherit the run-level wait limit".
_ALLOWED_WAIT_TIMEOUTS = {5000, 10000, 15000, 30000, 45000, 60000}


def _coerce_wait_timeout(raw):
    """Return (value, error). value is an allowed int, or None for inherit.
    error is a message string when raw is an unsupported value."""
    if raw is None or raw == "":
        return None, None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None, "wait_timeout must be an integer or null"
    if val not in _ALLOWED_WAIT_TIMEOUTS:
        return None, f"wait_timeout must be one of {sorted(_ALLOWED_WAIT_TIMEOUTS)} or null"
    return val, None

# Filename suffix → strategy. Order matters — longest match first.
_EXT_TO_LANGUAGE = [
    (".spec.ts", "typescript_test"),
    (".spec.js", "javascript_test"),
    (".test.ts", "typescript_test"),
    (".test.js", "javascript_test"),
    (".tsx", "typescript"),
    (".ts", "typescript"),
    (".mjs", "javascript"),
    (".cjs", "javascript"),
    (".js", "javascript"),
    (".py", "python"),
]


def _detect_codegen_layout(content: str, language: str) -> bool:
    """Return True if ``content`` looks like raw output from
    ``playwright codegen --target ...`` for the given language. Matches the
    bookends each strategy's ``_extract_actions`` already keys on."""
    if language == "python":
        # Codegen output is a `def run(playwright):` function body. Hand-written
        # scripts overwhelmingly use `with sync_playwright() as p:`. Both forms
        # contain the new_page/close bookends, so distinguish on the wrapper.
        return (
            "def run(playwright" in content
            and "page = context.new_page()" in content
            and "page.close()" in content
            and "from playwright.sync_api" in content
        )
    if language in ("javascript", "typescript"):
        # Codegen wraps actions in a top-level `(async () => {` IIFE with a
        # single `chromium.launch()` call. Hand-written scripts often add
        # helpers / multiple browsers / module exports.
        return (
            "(async () => {" in content
            and "context.newPage()" in content
            and ("await context.close()" in content or "await browser.close()" in content)
        )
    if language in ("javascript_test", "typescript_test"):
        # codegen --target playwright-test emits exactly one `test()` block,
        # no hooks, no test.use, no test.extend, no module-level helpers.
        # Anything else is freeform — route through the freeform extractor so
        # warnings (multiple_tests_dropped, hook_dropped, etc.) surface.
        has_import = (
            "@playwright/test" in content
            and ("import { test" in content or "require('@playwright/test')" in content
                 or "require(\"@playwright/test\")" in content)
        )
        if not has_import:
            return False
        test_blocks = len(re.findall(r"^\s*test\s*\(", content, re.MULTILINE))
        if test_blocks != 1:
            return False
        if re.search(r"^\s*test\.(use|beforeAll|beforeEach|afterAll|afterEach|extend)\s*\(",
                     content, re.MULTILINE):
            return False
        return bool(re.search(r"\btest\s*\(.*async\s*\(\s*\{[^}]*\}\s*\)\s*=>\s*\{", content))
    return False


def _detect_language(content: str, filename: str, override: str):
    """Return ``(language, source)`` where source is ``user|extension|content``.

    Raises ValueError on unresolvable input."""
    if override:
        if override not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{override}'. Supported: {list(SUPPORTED_LANGUAGES)}"
            )
        return override, "user"

    name_lower = (filename or "").lower()
    for suffix, lang in _EXT_TO_LANGUAGE:
        if name_lower.endswith(suffix):
            return lang, "extension"

    # Content sniff fallback.
    if "from playwright.sync_api" in content or "import playwright.sync_api" in content:
        return "python", "content"
    has_pw_test = (
        "@playwright/test" in content
        and ("import { test" in content or "require('@playwright/test')" in content
             or "require(\"@playwright/test\")" in content)
    )
    is_ts_hint = bool(re.search(r":\s*(?:string|number|boolean|Page|Locator|Browser)\b", content)) \
        or "as const" in content or "import type" in content
    if has_pw_test:
        return ("typescript_test" if is_ts_hint else "javascript_test"), "content"
    if "require('playwright')" in content or "require(\"playwright\")" in content \
            or "from 'playwright'" in content or 'from "playwright"' in content:
        return ("typescript" if is_ts_hint else "javascript"), "content"

    raise ValueError("Could not determine script language from filename or content.")


_GOTO_URL_RE = re.compile(r'\bpage\s*\.\s*goto\s*\(\s*["\']([^"\']+)["\']')


def _detect_goto_urls(content: str):
    """Return list of `{url, occurrences}` dicts for distinct `page.goto()`
    string literals in ``content``, ordered by occurrences desc. Skips URLs
    that already contain a `{{KEY}}` placeholder."""
    counts = {}
    for match in _GOTO_URL_RE.finditer(content):
        url = match.group(1).strip()
        if not url or "{{" in url:
            continue
        counts[url] = counts.get(url, 0) + 1
    return [
        {"url": u, "occurrences": n}
        for u, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _url_origin(url: str) -> str:
    """Return scheme://host[:port] for ``url``, or the input unchanged when
    no path/query is present. ``rewrite_url_template`` matches on this base."""
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9+.\-]*://[^/?#]+)', url)
    return m.group(1) if m else url


def _normalize_imported_script(content: str, filename: str, language_override: str,
                                url_key: str = "", url_value: str = ""):
    """Normalize ``content`` into the matching strategy's harness.

    Returns dict with normalized content, warnings, layout, var_keys, etc.
    Raises ValueError for unrecoverable input (rejected at request layer)."""
    if not content or not content.strip():
        raise ValueError("Empty file.")
    if "\x00" in content:
        raise ValueError("File contains NUL bytes — refusing.")
    if len(content.encode("utf-8", errors="replace")) > _MAX_IMPORT_BYTES:
        raise ValueError(f"File exceeds {_MAX_IMPORT_BYTES} bytes.")

    language, source = _detect_language(content, filename, language_override)
    strategy = get_strategy(language)
    warnings = []

    # Auto-promote .spec.* mismatches: filename says spec but extension picked
    # plain. Already covered by _EXT_TO_LANGUAGE precedence; only flag when the
    # user override conflicts with the extension.
    if source == "user":
        try:
            ext_lang, ext_source = _detect_language(content, filename, "")
            if ext_source == "extension" and ext_lang != language:
                warnings.append(ImportWarning(
                    severity="warn", code="lang_mismatch_extension",
                    message=f"Selected language '{language}' differs from filename hint '{ext_lang}'.",
                ).to_dict())
        except ValueError:
            pass

    layout = "freeform"
    if detect_qaclan_harness(content):
        layout = "qaclan_harness"
        actions = extract_between_harness_markers(content) or ""
        normalized = strategy._render_harness(actions)
    elif _detect_codegen_layout(content, language):
        layout = "playwright_codegen"
        normalized = strategy.post_process_recording(content)
        warnings.append(ImportWarning(
            severity="info", code="harness_marker_missing",
            message="Recognized as raw playwright codegen output; wrapped in harness.",
        ).to_dict())
    else:
        actions, freeform_warnings = strategy.extract_actions_freeform(content)
        warnings.extend(w.to_dict() for w in freeform_warnings)
        if actions.strip():
            normalized = strategy._render_harness(actions)
        else:
            # Extraction failed entirely — render empty harness with the raw
            # content placed above the BEGIN marker as a comment block so the
            # user sees what we received.
            normalized = strategy.starter_template()

    detected_urls = _detect_goto_urls(normalized)

    start_url_key = ""
    start_url_value = ""
    if url_key and url_value:
        url_key = url_key.strip()
        url_value = url_value.strip()
        # Collision check — same scaffold names that block import.
        scaffold_names = {
            "_BROWSER", "_HEADLESS", "_VIEWPORT", "_STATE", "_ARTIFACTS",
            "_SCREENSHOT", "_consoleErrors", "_networkFailures", "_contextOpts",
            "_writeArtifacts", "run",
        }
        if url_key in scaffold_names:
            warnings.append(ImportWarning(
                severity="error", code="qaclan_var_collision",
                message=f"URL key '{url_key}' collides with QAClan scaffold name.",
            ).to_dict())
        else:
            base = _url_origin(url_value)
            normalized = strategy.rewrite_url_template(normalized, base, url_key)
            start_url_key = url_key
            start_url_value = base
            warnings.append(ImportWarning(
                severity="info", code="start_url_templated",
                message=f"Templated {base} as {{{{{url_key}}}}}.",
            ).to_dict())
            # Flag remaining distinct hosts so user knows others were left literal.
            other_hosts = {_url_origin(u["url"]) for u in detected_urls} - {base}
            if other_hosts:
                warnings.append(ImportWarning(
                    severity="info", code="multiple_base_urls_detected",
                    message=f"Other hosts left untouched: {sorted(other_hosts)}.",
                ).to_dict())

    needs_manual_review = any(
        w.get("code") == "extraction_failed" or w.get("severity") == "error"
        for w in warnings
    )

    var_keys = _scan_var_keys(normalized)
    if var_keys:
        warnings.append(ImportWarning(
            severity="info", code="var_keys_detected",
            message=f"Found {{KEY}} placeholders: {var_keys}",
        ).to_dict())

    # Sensitive-literal hint: any .fill("...") with hardcoded value.
    if re.search(r'\.fill\s*\(\s*["\'][^"\']+["\']\s*,\s*["\'][^"\']+["\']\s*\)', normalized):
        warnings.append(ImportWarning(
            severity="warn", code="sensitive_literal",
            message="Hardcoded values present in .fill() calls — review with Scan & Bind.",
        ).to_dict())

    return {
        "language": language,
        "language_source": source,
        "layout": layout,
        "content": normalized,
        "var_keys": var_keys,
        "detected_urls": detected_urls,
        "start_url_key": start_url_key,
        "start_url_value": start_url_value,
        "warnings": warnings,
        "needs_manual_review": needs_manual_review,
    }


@bp.route('/api/scripts/import-preview', methods=['POST'])
def import_preview():
    """Pure-transform endpoint: take a user-supplied script file, return the
    normalized harness + diagnostics. Does not touch DB or disk."""
    try:
        data = request.get_json(force=True) or {}
        content = data.get("content", "")
        filename = (data.get("filename") or "").strip()
        language_override = (data.get("language") or "").strip()
        url_key = (data.get("url_key") or "").strip()
        url_value = (data.get("url_value") or "").strip()

        if not isinstance(content, str):
            return jsonify({"ok": False, "error": "content must be a string"}), 400
        if url_key and not url_value:
            return jsonify({"ok": False, "error": "url_value required when url_key is set"}), 400

        result = _normalize_imported_script(content, filename, language_override,
                                            url_key=url_key, url_value=url_value)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e), "code": "import_invalid"}), 400
    except Exception as e:
        logger.exception("import-preview failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/starter-template', methods=['GET'])
def get_starter_template():
    """Return the empty harness scaffolding for the given language."""
    try:
        language = (request.args.get("language") or "").strip()
        if language not in SUPPORTED_LANGUAGES:
            return jsonify({
                "ok": False,
                "error": f"Unsupported language '{language}'. Supported: {list(SUPPORTED_LANGUAGES)}",
            }), 400
        content = get_strategy(language).starter_template()
        return jsonify({"ok": True, "content": content})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts', methods=['GET'])
def list_scripts():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        feature_id = request.args.get("feature_id")

        if feature_id:
            rows = conn.execute(
                "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
                "s.channel, s.source, s.language, s.created_at, s.created_by "
                "FROM scripts s JOIN features f ON s.feature_id = f.id "
                "WHERE s.project_id = ? AND s.feature_id = ? "
                "ORDER BY s.created_at DESC",
                (project_id, feature_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
                "s.channel, s.source, s.language, s.created_at, s.created_by "
                "FROM scripts s JOIN features f ON s.feature_id = f.id "
                "WHERE s.project_id = ? "
                "ORDER BY s.created_at DESC",
                (project_id,),
            ).fetchall()

        scripts = [dict(r) for r in rows]
        return jsonify({"ok": True, "scripts": scripts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>', methods=['GET'])
def get_script(script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
            "s.channel, s.source, s.language, s.file_path, s.created_at, s.created_by, "
            "s.start_url_key, s.start_url_value, s.var_keys, s.wait_timeout "
            "FROM scripts s JOIN features f ON s.feature_id = f.id "
            "WHERE s.id = ? AND s.project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        script = dict(row)

        # Parse var_keys JSON for the client
        try:
            script["var_keys"] = json.loads(script.get("var_keys") or "[]")
        except (TypeError, ValueError):
            script["var_keys"] = []

        # Read file content from disk
        content = ""
        file_path = script.get("file_path", "")
        if file_path and os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        script["content"] = content

        return jsonify({"ok": True, "script": script})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts', methods=['POST'])
def create_script():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        feature_id = data.get("feature_id", "").strip()
        content = data.get("content", "")
        language = (data.get("language") or "python").strip()
        start_url_key = (data.get("start_url_key") or "").strip() or None
        start_url_value = (data.get("start_url_value") or "").strip() or None
        wait_timeout, wt_err = _coerce_wait_timeout(data.get("wait_timeout"))
        if wt_err:
            return jsonify({"ok": False, "error": wt_err}), 400

        if not name:
            return jsonify({"ok": False, "error": "Script name is required"}), 400
        if not feature_id:
            return jsonify({"ok": False, "error": "Feature ID is required"}), 400
        if language not in SUPPORTED_LANGUAGES:
            return jsonify({
                "ok": False,
                "error": f"Unsupported language '{language}'. Supported: {list(SUPPORTED_LANGUAGES)}",
            }), 400

        conn = get_conn()

        # Verify feature exists and belongs to active project
        feat = conn.execute(
            "SELECT id FROM features WHERE id = ? AND project_id = ?",
            (feature_id, project_id),
        ).fetchone()
        if not feat:
            return jsonify({"ok": False, "error": f"Feature {feature_id} not found"}), 404

        script_id = generate_id("script")
        now = datetime.now(timezone.utc).isoformat()

        # Write script file to disk with the extension matching its language
        strategy = get_strategy(language)
        scripts_dir = Path(SCRIPTS_DIR)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(scripts_dir / f"{script_id}{strategy.file_extension}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        from cli.config import get_user_name
        created_by = get_user_name()
        # Scan {{KEY}} placeholders so var_keys is populated for runtime substitution
        var_keys_list = _scan_var_keys(content)
        if start_url_key and start_url_key not in var_keys_list:
            var_keys_list.append(start_url_key)
        conn.execute(
            "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, language, "
            "created_at, created_by, start_url_key, start_url_value, var_keys, wait_timeout) "
            "VALUES (?, ?, ?, 'web', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (script_id, feature_id, project_id, name, file_path, content, language, now, created_by,
             start_url_key, start_url_value, json.dumps(var_keys_list), wait_timeout),
        )
        conn.commit()

        from cli.sync_queue import enqueue
        enqueue("script", script_id, "upsert")

        return jsonify({"ok": True, "id": script_id, "name": name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>', methods=['PUT'])
def update_script(script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id, file_path, language FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        data = request.get_json(force=True)
        name = data.get("name")
        content = data.get("content")
        language = data.get("language")

        if name is not None:
            name = name.strip()
            if not name:
                return jsonify({"ok": False, "error": "Script name cannot be empty"}), 400
            conn.execute(
                "UPDATE scripts SET name = ? WHERE id = ?", (name, script_id)
            )

        # wait_timeout: present key = set (int or null-to-inherit); absent = leave.
        if "wait_timeout" in data:
            wait_timeout, wt_err = _coerce_wait_timeout(data.get("wait_timeout"))
            if wt_err:
                return jsonify({"ok": False, "error": wt_err}), 400
            conn.execute(
                "UPDATE scripts SET wait_timeout = ? WHERE id = ?", (wait_timeout, script_id)
            )

        # Language change: validate, rename the on-disk file to the new
        # extension, and update file_path + language. The caller is expected
        # to also send matching ``content`` if the body needs rewriting —
        # changing language without new content will leave a broken script
        # on disk, which is the user's responsibility.
        file_path = row["file_path"]
        if language is not None:
            language = language.strip()
            if language not in SUPPORTED_LANGUAGES:
                return jsonify({
                    "ok": False,
                    "error": f"Unsupported language '{language}'. Supported: {list(SUPPORTED_LANGUAGES)}",
                }), 400
            if language != row["language"] and file_path:
                new_ext = get_strategy(language).file_extension
                new_path = str(Path(file_path).with_suffix(new_ext))
                if new_path != file_path and os.path.exists(file_path):
                    os.rename(file_path, new_path)
                    file_path = new_path
                    conn.execute(
                        "UPDATE scripts SET file_path = ? WHERE id = ?",
                        (file_path, script_id),
                    )
            conn.execute(
                "UPDATE scripts SET language = ? WHERE id = ?",
                (language, script_id),
            )

        if content is not None:
            if file_path:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
            # Re-scan {{KEY}} placeholders so var_keys stays in sync with the body
            new_var_keys = _scan_var_keys(content)
            conn.execute(
                "UPDATE scripts SET source = ?, var_keys = ? WHERE id = ?",
                (content, json.dumps(new_var_keys), script_id),
            )

        conn.commit()

        from cli.sync_queue import enqueue
        enqueue("script", script_id, "upsert")

        return jsonify({"ok": True, "id": script_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/record', methods=['POST'])
def record_script_route():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        feature_id = data.get("feature_id", "").strip()
        url = data.get("url", "").strip() or None
        env_name = data.get("env_name", "").strip() or None
        url_key = data.get("url_key", "").strip() or None
        path_suffix = data.get("path_suffix", "").strip() or ""
        language = (data.get("language") or "python").strip()
        resolution = (data.get("resolution") or "").strip() or None

        if not name:
            return jsonify({"ok": False, "error": "Script name is required"}), 400
        if not feature_id:
            return jsonify({"ok": False, "error": "Feature ID is required"}), 400
        if language not in SUPPORTED_LANGUAGES:
            return jsonify({
                "ok": False,
                "error": f"Unsupported language '{language}'. Supported: {list(SUPPORTED_LANGUAGES)}",
            }), 400

        # If env+key provided, resolve the actual URL from the env var
        resolved_url_key = None
        resolved_url_key_value = None
        if env_name and url_key:
            conn = get_conn()
            env_row = conn.execute(
                "SELECT id FROM environments WHERE project_id = ? AND name = ?",
                (project_id, env_name),
            ).fetchone()
            if not env_row:
                return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404
            var_row = conn.execute(
                "SELECT value FROM env_vars WHERE environment_id = ? AND key = ?",
                (env_row["id"], url_key),
            ).fetchone()
            if not var_row:
                return jsonify({"ok": False, "error": f"Variable \"{url_key}\" not found in env \"{env_name}\""}), 404
            base_value = (var_row["value"] or "").rstrip("/")
            if not base_value:
                return jsonify({"ok": False, "error": f"Variable \"{url_key}\" has an empty value in env \"{env_name}\""}), 400
            url = base_value + path_suffix
            resolved_url_key = url_key
            resolved_url_key_value = base_value

        logger.info("POST /api/scripts/record: project=%s, feature=%s, name=%s, url=%s, url_key=%s, language=%s",
                     project_id, feature_id, name, url, resolved_url_key, language)

        from cli import runtime_setup
        try:
            get_strategy(language).validate_runtime()
        except (ValueError, RuntimeError) as e:
            if not runtime_setup.runtime_initialized():
                return jsonify(runtime_setup.runtime_needs_setup_payload(str(e))), 400
            return jsonify({"ok": False, "error": str(e)}), 400

        from cli.commands.web.record import record_script
        script_id, dest = record_script(
            project_id, feature_id, name, url,
            url_key=resolved_url_key,
            url_key_value=resolved_url_key_value,
            language=language,
            resolution=resolution,
        )
        logger.info("Recording succeeded: script_id=%s, dest=%s", script_id, dest)
        return jsonify({"ok": True, "id": script_id, "name": name}), 201
    except (ValueError, RuntimeError) as e:
        logger.error("Recording failed (expected): %s", e)
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Recording failed (unexpected): %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>', methods=['DELETE'])
def delete_script(script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id, file_path FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        # Delete file from disk
        file_path = row["file_path"]
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)

        # Delete DB row
        conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
        conn.commit()

        from cli.sync_queue import enqueue
        enqueue("script", script_id, "delete")

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>/run', methods=['POST'])
def run_script_solo(script_id):
    """Run a single script ad-hoc without a suite. Creates a temporary suite_run."""
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True) or {}
        env_name = data.get("env_name")
        browser_type = data.get("browser", "chromium")
        headless = data.get("headless", False)
        resolution = data.get("resolution") or None

        conn = get_conn()
        script_row = conn.execute(
            "SELECT * FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not script_row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        script = dict(script_row)

        # Find or create a solo-run suite
        solo_suite = conn.execute(
            "SELECT id FROM suites WHERE project_id = ? AND name = '__solo_runs__' LIMIT 1",
            (project_id,),
        ).fetchone()
        if not solo_suite:
            solo_suite_id = generate_id("suite")
            now_ts = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO suites (id, project_id, channel, name, created_at) VALUES (?, ?, 'web', '__solo_runs__', ?)",
                (solo_suite_id, project_id, now_ts),
            )
            conn.commit()
        else:
            solo_suite_id = solo_suite["id"]

        # Delegate to execute_run logic by posting to /api/runs internally
        # We build a minimal suite_items entry temporarily
        # Simpler: inline the run logic here for the single script case
        import os, time, json, subprocess
        from pathlib import Path
        from cli.script_strategies import get_strategy
        from cli.db import generate_id as gen_id
        from cli.script_strategies._shared import substitute_template_vars
        from web.routes.runs import (
            RUNS_DIR, SCREENSHOTS_DIR, PER_SCRIPT_TIMEOUT_SEC,
            DEFAULT_RECORD_RESOLUTION, _read_artifacts, _build_error_detail,
            get_default_playwright_browsers_path, is_frozen_binary,
        )
        from cli import runtime_setup

        language = script.get("language") or "python"
        try:
            get_strategy(language).validate_runtime()
        except (ValueError, RuntimeError) as e:
            if not runtime_setup.runtime_initialized():
                return jsonify(runtime_setup.runtime_needs_setup_payload(str(e))), 400
            return jsonify({"ok": False, "error": str(e)}), 400

        env_vars_dict = {}
        environment_id = None
        if env_name:
            env_row = conn.execute(
                "SELECT * FROM environments WHERE project_id = ? AND name = ?",
                (project_id, env_name),
            ).fetchone()
            if not env_row:
                return jsonify({"ok": False, "error": f"Environment '{env_name}' not found"}), 404
            environment_id = env_row["id"]
            from cli.crypto import decrypt
            for v in conn.execute("SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
                                  (env_row["id"],)).fetchall():
                val = v["value"]
                if v["is_secret"] and val:
                    val = decrypt(val)
                env_vars_dict[v["key"]] = val

        run_id = gen_id("run")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at, browser, resolution, headless) "
            "VALUES (?, ?, ?, ?, 'web', 'RUNNING', 1, ?, ?, ?, ?)",
            (run_id, solo_suite_id, project_id, environment_id, now, browser_type, resolution, 1 if headless else 0),
        )
        conn.commit()

        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        state_file = run_dir / "state.json"

        srun_id = gen_id("srun")
        script_now = now
        script_start = time.time()
        screenshot_path = SCREENSHOTS_DIR / f"{srun_id}.png"
        artifacts_path = run_dir / f"{srun_id}.artifacts.json"

        try:
            strategy = get_strategy(language)
            script_path = script.get("file_path")
            if not script_path or not os.path.exists(script_path):
                raise FileNotFoundError(f"Script file not found: {script_path}")
            source = Path(script_path).read_text(encoding="utf-8")

            try:
                script_var_keys = json.loads(script.get("var_keys") or "[]")
            except (TypeError, ValueError):
                script_var_keys = []
            if script_var_keys:
                source, _ = substitute_template_vars(
                    source, script_var_keys, env_vars_dict,
                    script.get("start_url_key"), script.get("start_url_value"),
                    escape_fn=strategy.escape_for_literal,
                )

            rendered_path = run_dir / f"{srun_id}{strategy.file_extension}"
            rendered_path.write_text(source, encoding="utf-8")

            child_env = os.environ.copy()
            child_env.update(env_vars_dict)
            child_env["QACLAN_STORAGE_STATE"] = str(state_file)
            child_env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
            child_env["QACLAN_SCREENSHOT_PATH"] = str(screenshot_path)
            child_env["QACLAN_BROWSER"] = browser_type
            child_env["QACLAN_HEADLESS"] = "1" if headless else "0"
            child_env["QACLAN_VIEWPORT"] = resolution or DEFAULT_RECORD_RESOLUTION
            child_env["QACLAN_EXPECT_TIMEOUT"] = "15000"
            child_env["QACLAN_ACTION_TIMEOUT"] = "15000"

            pw_browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
            rt_browsers = runtime_setup.browsers_path_if_present()
            if not pw_browsers_path and rt_browsers:
                child_env["PLAYWRIGHT_BROWSERS_PATH"] = str(rt_browsers)
            elif is_frozen_binary() and not pw_browsers_path:
                default_browsers = get_default_playwright_browsers_path()
                if os.path.isdir(default_browsers):
                    child_env["PLAYWRIGHT_BROWSERS_PATH"] = default_browsers

            child_env.update(strategy.extra_env())
            cmd = strategy.build_run_command(str(rendered_path))

            proc = subprocess.run(cmd, env=child_env, capture_output=True, text=True, timeout=PER_SCRIPT_TIMEOUT_SEC)
            duration_ms = int((time.time() - script_start) * 1000)
            finished_at = datetime.now(timezone.utc).isoformat()
            console_errors, network_failures, artifacts_error = _read_artifacts(artifacts_path)

            if proc.returncode == 0:
                status = "PASSED"
                error_msg = None
                error_detail = None
                saved_screenshot = None
            else:
                status = "FAILED"
                error_detail, error_msg = _build_error_detail(
                    kind="subprocess", returncode=proc.returncode,
                    stdout=proc.stdout, stderr=proc.stderr,
                    artifacts_error=artifacts_error,
                    has_network_failures=bool(network_failures),
                )
                saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None

            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                "duration_ms, error_message, error_detail, console_errors, network_failures, "
                "screenshot_path, started_at, finished_at) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (srun_id, run_id, script_id, status, duration_ms,
                 error_msg, json.dumps(error_detail) if error_detail else None,
                 len(console_errors), len(network_failures), saved_screenshot,
                 script_now, finished_at),
            )
            final_status = status
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - script_start) * 1000)
            finished_at = datetime.now(timezone.utc).isoformat()
            error_detail, error_msg = _build_error_detail(kind="timeout")
            status = "FAILED"
            saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None
            console_errors, network_failures, _ = _read_artifacts(artifacts_path)
            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                "duration_ms, error_message, error_detail, console_errors, network_failures, "
                "screenshot_path, started_at, finished_at) VALUES (?, ?, ?, 0, 'FAILED', ?, ?, ?, ?, ?, ?, ?, ?)",
                (srun_id, run_id, script_id, duration_ms, error_msg,
                 json.dumps(error_detail), len(console_errors), len(network_failures),
                 saved_screenshot, script_now, finished_at),
            )
            final_status = "FAILED"
        except Exception as exc:
            duration_ms = int((time.time() - script_start) * 1000)
            finished_at = datetime.now(timezone.utc).isoformat()
            error_detail, error_msg = _build_error_detail(kind="internal", exc=exc)
            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                "duration_ms, error_message, error_detail, started_at, finished_at) "
                "VALUES (?, ?, ?, 0, 'FAILED', ?, ?, ?, ?, ?)",
                (srun_id, run_id, script_id, duration_ms, error_msg,
                 json.dumps(error_detail), script_now, finished_at),
            )
            final_status = "FAILED"

        env_vars_dict.clear()
        conn.execute(
            "UPDATE suite_runs SET status=?, passed=?, failed=?, finished_at=? WHERE id=?",
            (final_status, 1 if final_status == "PASSED" else 0,
             0 if final_status == "PASSED" else 1, finished_at, run_id),
        )
        conn.commit()

        return jsonify({
            "ok": True,
            "result": {
                "run_id": run_id,
                "script_id": script_id,
                "name": script.get("name"),
                "status": final_status,
                "duration_ms": duration_ms,
                "error_message": error_msg if final_status != "PASSED" else None,
                "error_detail": error_detail if final_status != "PASSED" else None,
                "screenshot_path": saved_screenshot if final_status != "PASSED" else None,
            },
        })

    except Exception as e:
        logger.exception("run_script_solo")
        return jsonify({"ok": False, "error": str(e)}), 500
