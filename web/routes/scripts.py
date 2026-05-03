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
            "s.start_url_key, s.start_url_value, s.var_keys "
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
            "created_at, created_by, start_url_key, start_url_value, var_keys) "
            "VALUES (?, ?, ?, 'web', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (script_id, feature_id, project_id, name, file_path, content, language, now, created_by,
             start_url_key, start_url_value, json.dumps(var_keys_list)),
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

        from cli.commands.web.record import record_script
        script_id, dest = record_script(
            project_id, feature_id, name, url,
            url_key=resolved_url_key,
            url_key_value=resolved_url_key_value,
            language=language,
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
