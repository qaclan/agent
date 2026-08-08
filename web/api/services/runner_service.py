from __future__ import annotations
import json
import logging
from cli.db import get_conn
from cli.config import get_active_project_id
from cli.env_loader import load_env_vars
from cli.schema_infer import infer_schema

logger = logging.getLogger("qaclan.runner_service")


def _infer_response_schema(response_headers: dict | None, response_body: str | None):
    """Best-effort schema inference from a JSON response body. Returns None
    when the response isn't JSON or can't be parsed — callers must leave any
    already-stored schema untouched in that case, not clear it."""
    if not response_body:
        return None
    content_type = ""
    for k, v in (response_headers or {}).items():
        if k.lower() == "content-type":
            content_type = v or ""
            break
    if "json" not in content_type:
        return None
    try:
        return infer_schema(json.loads(response_body))
    except Exception:
        return None


def _resolve_auth(req: dict, col: dict | None) -> dict:
    """Return req with auth resolved: 'inherit' replaced by collection's auth."""
    if req.get("auth_type") != "inherit" or col is None:
        return req
    resolved = dict(req)
    resolved["auth_type"] = col.get("auth_type") or "none"
    resolved["auth_config"] = col.get("auth_config") or "{}"
    return resolved


def _resolve_schema_check(req: dict, col: dict | None) -> bool:
    """Effective schema-check enablement: request override wins, else collection default.

    Override is 'inherit' | 'on' | 'off'; collection default is 'on' | 'off'.
    Resolved per run — nothing is copied to request rows on a collection flip.
    """
    override = req.get("schema_check") or "inherit"
    if override in ("on", "off"):
        return override == "on"
    return ((col or {}).get("schema_check_default") or "off") == "on"


def _resolve_negative_check(req: dict, col: dict | None) -> bool:
    """Effective negative-testing enablement: request override wins, else
    collection default. Mirrors _resolve_schema_check."""
    override = req.get("negative_check") or "inherit"
    if override in ("on", "off"):
        return override == "on"
    return ((col or {}).get("negative_check_default") or "off") == "on"


def _enabled_negative_cases(req: dict) -> list:
    """The request's enabled negative cases (deserialized list)."""
    cases = req.get("negative_cases") or []
    if isinstance(cases, str):
        try:
            cases = json.loads(cases)
        except (ValueError, TypeError):
            cases = []
    return [c for c in cases if isinstance(c, dict) and c.get("enabled", True)]


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _mutating_negative_methods(req: dict) -> list:
    """Distinct mutating HTTP methods among the request's enabled negative cases
    — the input to the destructive-run safety gate."""
    from cli.negative_gen import case_method
    method = (req.get("method") or "GET").upper()
    found = set()
    for c in _enabled_negative_cases(req):
        m = case_method(method, c)
        if m in _MUTATING_METHODS:
            found.add(m)
    return sorted(found)


def _negatives_for_run(req: dict, col: dict | None, confirm_destructive: bool,
                       mode: str = "default"):
    """Resolve what negatives to actually run for one request in a collection run.

    `mode` is the run-level negatives mode:
      - "default": negatives run only when resolved on (inheritance).
      - "off": negatives never run this run (happy-path only).
      - "only": negatives run only for requests resolved on AND with cases (the
        happy-path assertions are suppressed by the caller). A request that is
        resolved off, or has no enabled cases, runs no negatives — same as
        "default" for enablement; it just drops the happy path.

    Enablement is checked the same way in "default" and "only": a resolved-off
    request returns (False, []) in both. Requests with negatives off do not run
    negatives even in only-mode.

    Returns (enabled, cases). The safety gate is applied **per case**: an
    unconfirmed run keeps the read-only cases and drops only the state-changing
    (mutating-verb) ones — so a request with a mix still exercises its safe
    negatives, and a wholly-mutating request (e.g. a POST) runs none until
    `confirm_destructive`. This is what the reference doc means by "safe
    negatives still run".
    """
    if mode == "off":
        return False, []
    if not _resolve_negative_check(req, col):
        return False, []
    cases = req.get("negative_cases") or []
    if isinstance(cases, str):
        try:
            cases = json.loads(cases)
        except (ValueError, TypeError):
            cases = []
    if confirm_destructive:
        run_cases = list(cases)
    else:
        from cli.negative_gen import case_method
        method = (req.get("method") or "GET").upper()
        run_cases = []
        for c in cases:
            if isinstance(c, dict) and c.get("enabled", True) \
                    and (case_method(method, c) or method).upper() in _MUTATING_METHODS:
                continue  # skip the mutating case in an unconfirmed run
            run_cases.append(c)
    enabled = any(isinstance(c, dict) and c.get("enabled", True) for c in run_cases)
    return enabled, run_cases


def _requests_for_run(requests: list, col: dict | None, confirm_destructive: bool,
                      mode: str) -> list:
    """The ordered requests that will actually execute this collection run.

    In only-mode this drops requests that would run no negatives (resolved off,
    or no enabled cases) so the run's request set — its total, its per-request
    indices, and the live view — contains exactly the qualifying requests, with
    contiguous order indices. Other modes run every request unchanged.
    """
    if mode != "only":
        return list(requests)
    return [r for r in requests
            if _negatives_for_run(r, col, confirm_destructive, "only")[0]]


def _maybe_capture_baseline(request_id: str, baseline, result: dict):
    """Capture the first successful JSON response as the frozen response_schema
    baseline — only when nothing is stored yet (baseline is None) and the
    response was JSON with status < 400. Never overwrites an existing baseline
    (that is what the explicit "Update response schema" action is for). Runs
    regardless of whether the schema check is enabled, so the extractor picker
    and Schema tab get populated on first send. Returns the effective baseline.
    """
    if baseline is not None:
        return baseline
    inferred = result.get("inferred_schema")
    status_code = result.get("status_code") or 0
    if inferred is not None and status_code < 400:
        from web.api.repositories.request_repo import RequestRepo
        RequestRepo().update(request_id, {"response_schema": inferred})
        return inferred
    return baseline


class RunnerService:
    def run_request(self, request_id: str, project_id: str, env_name: str | None = None) -> dict:
        """Run a single api_request ad-hoc. Result is NOT stored in api_runs."""
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.collection_vars_repo import CollectionVarsRepo
        from cli.api_runner import run_api_request

        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")

        col = None
        if req.get("collection_id"):
            col = CollectionRepo().get(req["collection_id"], project_id)

        # Inherit env from collection if not specified
        if not env_name and col:
            env_name = col.get("env_name")

        env_vars = load_env_vars(project_id, env_name)

        # Seed state with collection vars initial values
        seed_vars: dict = {}
        if req.get("collection_id"):
            seed_vars = CollectionVarsRepo().as_seed_dict(req["collection_id"])
        state: dict = {"qaclan_vars": seed_vars} if seed_vars else {}

        schema_check_enabled = _resolve_schema_check(req, col)
        baseline_schema = req.get("response_schema")
        result = run_api_request(
            _resolve_auth(req, col), env_vars, state, state_path=None,
            baseline_schema=baseline_schema, schema_check_enabled=schema_check_enabled,
        )

        # Capture the first successful JSON response as the frozen baseline.
        # Never overwrites an existing response_schema — it stays frozen so the
        # drift check has a stable reference (updated only via set_response_schema).
        _maybe_capture_baseline(request_id, baseline_schema, result)

        # Persist extracted vars back to collection_vars so subsequent single sends see them
        if result.get("state_updates") and req.get("collection_id"):
            from web.api.repositories.collection_vars_repo import CollectionVarsRepo
            vars_repo = CollectionVarsRepo()
            for key, value in result["state_updates"].items():
                vars_repo.upsert(req["collection_id"], key, str(value))

        return result

    def set_response_schema(self, request_id: str, project_id: str,
                            schema=None, response_body: str | None = None,
                            response_headers: dict | None = None):
        """Re-accept a response shape as the request's frozen response_schema
        baseline — the "Update response schema" action.

        Accepts an already-inferred `schema` (the UI passes the last send's
        inferred shape) or falls back to inferring from a supplied response
        body. Overwrites api_requests.response_schema. Returns the stored schema.
        """
        from web.api.repositories.request_repo import RequestRepo
        repo = RequestRepo()
        req = repo.get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")
        if schema is None and response_body is not None:
            schema = _infer_response_schema(
                response_headers or {"content-type": "application/json"}, response_body)
        if schema is None:
            raise ValueError("No JSON response available to save as the response schema")
        repo.update(request_id, {"response_schema": schema})
        return schema

    def plan_request_negatives(self, request_id: str, project_id: str,
                               env_name: str | None = None) -> dict:
        """Preview a request's negative run for the safety gate: how many cases,
        which mutating methods, and the active environment. No requests sent."""
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_repo import CollectionRepo
        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")
        col = None
        if req.get("collection_id"):
            col = CollectionRepo().get(req["collection_id"], project_id)
        if not env_name and col:
            env_name = col.get("env_name")
        cases = _enabled_negative_cases(req)
        mutating = _mutating_negative_methods(req)
        return {
            "enabled": _resolve_negative_check(req, col),
            "case_count": len(cases),
            "mutating_methods": mutating,
            "needs_confirm": bool(mutating),
            "environment": env_name,
        }

    def run_negatives(self, request_id: str, project_id: str,
                      env_name: str | None = None,
                      confirm_destructive: bool = False) -> dict:
        """Run a single request's negative cases (a dedicated action, distinct
        from an ordinary send). Enforces the destructive-run safety gate: if any
        enabled case uses a mutating verb and the caller has not confirmed,
        nothing is sent and a needs_confirm plan is returned instead."""
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.collection_vars_repo import CollectionVarsRepo
        from cli.api_runner import run_api_request

        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")
        col = None
        if req.get("collection_id"):
            col = CollectionRepo().get(req["collection_id"], project_id)
        if not env_name and col:
            env_name = col.get("env_name")

        cases = _enabled_negative_cases(req)
        if not cases:
            return {"ok": False, "reason": "no-cases"}

        mutating = _mutating_negative_methods(req)
        if mutating and not confirm_destructive:
            return {
                "ok": False,
                "needs_confirm": True,
                "mutating_methods": mutating,
                "case_count": len(cases),
                "environment": env_name,
            }

        env_vars = load_env_vars(project_id, env_name)
        seed_vars: dict = {}
        if req.get("collection_id"):
            seed_vars = CollectionVarsRepo().as_seed_dict(req["collection_id"])
        state: dict = {"qaclan_vars": seed_vars} if seed_vars else {}

        result = run_api_request(
            _resolve_auth(req, col), env_vars, state, state_path=None,
            negative_enabled=True, negative_cases=req.get("negative_cases") or [],
        )
        return {"ok": True, "result": result, "environment": env_name}

    def generate_negatives(self, request_id: str, project_id: str,
                           regenerate: bool = False) -> dict:
        """Generate (or regenerate) a request's negative cases from its shape and
        any stored field_constraints. On regenerate, returns the case diff so the
        UI can merge without discarding edits; does not itself persist."""
        from web.api.repositories.request_repo import RequestRepo
        from cli.negative_gen import generate_cases, diff_cases
        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")
        new_cases = generate_cases(req, req.get("field_constraints"))
        if regenerate:
            old = req.get("negative_cases") or []
            return {"cases": new_cases, "diff": diff_cases(old, new_cases)}
        return {"cases": new_cases, "diff": None}

    def plan_collection_negatives(self, collection_id: str, project_id: str) -> dict:
        """Preview a collection run's negatives for the safety gate: which
        requests contribute mutating negative cases. No requests sent."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")
        mutating_requests = []
        has_negatives = False      # any request resolved on AND with cases (what actually runs)
        resolved_on = 0            # requests whose negatives are on by inheritance
        for req in RequestRepo().list(project_id, collection_id=collection_id):
            if not _resolve_negative_check(req, col):
                continue
            resolved_on += 1
            if _enabled_negative_cases(req):
                # A request only runs negatives when resolved on AND it has cases.
                has_negatives = True
            methods = _mutating_negative_methods(req)
            if methods:
                mutating_requests.append({"name": req.get("name", ""), "methods": methods})
        return {
            "needs_confirm": bool(mutating_requests),
            "mutating_requests": mutating_requests,
            "has_negatives": has_negatives,
            "resolved_on": resolved_on,
            "environment": col.get("env_name"),
        }

    def start_collection_run(self, collection_id: str, project_id: str,
                              env_name: str | None = None,
                              seed_vars: dict | None = None,
                              confirm_destructive: bool = False,
                              negatives_mode: str = "default") -> tuple[str, bool]:
        """
        Returns (run_id, already_running).
        If a RUNNING run exists for this collection, returns it without spawning a new thread.
        confirm_destructive gates mutating-verb negative cases (see the safety gate).
        negatives_mode ∈ {"default","off","only"} — run happy-path + negatives as
        configured, happy-path only, or negatives only (happy-path assertions
        suppressed).
        """
        import threading
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_run_repo import CollectionRunRepo
        from datetime import datetime, timezone

        run_repo = CollectionRunRepo()

        existing_run_id = run_repo.get_running_for_collection(collection_id)
        if existing_run_id:
            logger.info("start_collection_run: collection %s already running as %s", collection_id, existing_run_id)
            return existing_run_id, True

        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        # In only-mode the run executes just the qualifying requests, so the run's
        # total must reflect that set (not the whole collection).
        run_requests = _requests_for_run(requests, col, confirm_destructive, negatives_mode)
        started_at = datetime.now(timezone.utc).isoformat()
        run_id = run_repo.create_run(
            collection_id=collection_id,
            project_id=project_id,
            collection_name=col["name"],
            env_name=env_name,
            started_at=started_at,
            total=len(run_requests),
        )

        thread = threading.Thread(
            target=self._execute_collection,
            args=(run_id, collection_id, project_id, env_name, seed_vars, confirm_destructive, negatives_mode),
            daemon=True,
        )
        thread.start()
        logger.info("start_collection_run: run_id=%s thread started", run_id)
        return run_id, False

    def _execute_collection(self, run_id: str, collection_id: str, project_id: str,
                             env_name: str | None, seed_vars: dict | None,
                             confirm_destructive: bool = False,
                             negatives_mode: str = "default") -> None:
        """Thread target. Checks stop_requested before each request."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_run_repo import CollectionRunRepo
        from web.api.repositories.collection_vars_repo import CollectionVarsRepo
        from cli.api_runner import run_api_request
        from datetime import datetime, timezone

        run_repo = CollectionRunRepo()
        vars_repo = CollectionVarsRepo()
        results: list = []
        final_status = "ERROR"

        try:
            col = CollectionRepo().get(collection_id, project_id)
            if col is None:
                logger.error("_execute_collection: collection %s not found", collection_id)
                return

            requests = RequestRepo().list(project_id, collection_id=collection_id)
            # Only-mode runs just the qualifying requests, with contiguous indices —
            # so the live view and results show exactly those requests.
            requests = _requests_for_run(requests, col, confirm_destructive, negatives_mode)
            env_vars = load_env_vars(project_id, env_name)

            # Seed state from persisted collection vars (same as single-request run)
            cv_seed = vars_repo.as_seed_dict(collection_id)
            state: dict = {"qaclan_vars": dict(cv_seed)} if cv_seed else {}
            # Explicitly passed seed_vars override persisted values
            if seed_vars:
                state.setdefault("qaclan_vars", {}).update(seed_vars)

            for idx, req in enumerate(requests):
                if run_repo.is_stop_requested(run_id):
                    logger.info("_execute_collection: stop requested at idx %d for run %s", idx, run_id)
                    final_status = "STOPPED"
                    break
                run_repo.update_current_index(run_id, idx)
                schema_check_enabled = _resolve_schema_check(req, col)
                baseline_schema = req.get("response_schema")
                neg_enabled, neg_cases = _negatives_for_run(req, col, confirm_destructive, negatives_mode)
                call_req = _resolve_auth(req, col)
                if negatives_mode == "only":
                    # Negatives-only run: suppress the happy-path checks; the base
                    # send still happens (it's the mutation source) but its status
                    # is judged by negatives alone. (Non-qualifying requests were
                    # already filtered out of `requests`.)
                    call_req = {**call_req, "assertions": []}
                    schema_check_enabled = False
                result = run_api_request(
                    call_req, env_vars, state, state_path=None,
                    baseline_schema=baseline_schema, schema_check_enabled=schema_check_enabled,
                    negative_enabled=neg_enabled, negative_cases=neg_cases,
                )
                _maybe_capture_baseline(req["id"], baseline_schema, result)
                results.append(result)
                run_repo.create_request_result(run_id, req, result, idx)
                # Persist extracted/script vars so subsequent requests and future runs see them
                if result.get("state_updates"):
                    for key, value in result["state_updates"].items():
                        vars_repo.upsert(collection_id, key, str(value))
            else:
                passed = sum(1 for r in results if r.get("status") == "PASSED")
                failed_c = sum(1 for r in results if r.get("status") == "FAILED")
                err_c = sum(1 for r in results if r.get("status") == "ERROR")
                final_status = "PASSED" if (failed_c + err_c) == 0 and results else "FAILED"

        except Exception:
            logger.exception("_execute_collection: unhandled error in run %s", run_id)

        finally:
            passed = sum(1 for r in results if r.get("status") == "PASSED")
            failed_c = sum(1 for r in results if r.get("status") == "FAILED")
            err_c = sum(1 for r in results if r.get("status") == "ERROR")
            run_repo.finish_run(
                run_id=run_id,
                status=final_status,
                total=len(results),
                passed=passed,
                failed=failed_c,
                error_count=err_c,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            from cli.sync_queue import enqueue
            enqueue("api_collection_run", run_id, "upsert")
            logger.info("_execute_collection: run %s → %s", run_id, final_status)

    def run_collection(self, collection_id: str, project_id: str,
                       env_name: str | None = None,
                       seed_vars: dict | None = None,
                       confirm_destructive: bool = False,
                       negatives_mode: str = "default") -> dict:
        """Run all requests in a collection sequentially. Results persisted to api_collection_runs."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_run_repo import CollectionRunRepo
        from cli.api_runner import run_api_request
        from datetime import datetime, timezone

        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        # Only-mode runs just the qualifying requests (contiguous indices).
        requests = _requests_for_run(requests, col, confirm_destructive, negatives_mode)
        env_vars = load_env_vars(project_id, env_name)

        state: dict = {"qaclan_vars": dict(seed_vars)} if seed_vars else {}

        started_at = datetime.now(timezone.utc).isoformat()
        run_repo = CollectionRunRepo()
        run_id = run_repo.create_run(
            collection_id=collection_id,
            project_id=project_id,
            collection_name=col["name"],
            env_name=env_name,
            started_at=started_at,
        )

        results = []
        try:
            for idx, req in enumerate(requests):
                schema_check_enabled = _resolve_schema_check(req, col)
                baseline_schema = req.get("response_schema")
                neg_enabled, neg_cases = _negatives_for_run(req, col, confirm_destructive, negatives_mode)
                call_req = _resolve_auth(req, col)
                if negatives_mode == "only":
                    # Non-qualifying requests already filtered out of `requests`.
                    call_req = {**call_req, "assertions": []}
                    schema_check_enabled = False
                result = run_api_request(
                    call_req, env_vars, state, state_path=None,
                    baseline_schema=baseline_schema, schema_check_enabled=schema_check_enabled,
                    negative_enabled=neg_enabled, negative_cases=neg_cases,
                )
                _maybe_capture_baseline(req["id"], baseline_schema, result)
                results.append({
                    "request_id": req["id"],
                    "name": req["name"],
                    "method": req["method"],
                    "url": result.get("url", ""),
                    **result,
                })
                run_repo.create_request_result(run_id, req, result, idx)
        finally:
            passed = sum(1 for r in results if r["status"] == "PASSED")
            failed = sum(1 for r in results if r["status"] == "FAILED")
            error_count = sum(1 for r in results if r["status"] == "ERROR")
            final_status = "PASSED" if (failed + error_count) == 0 else "FAILED"
            finished_at = datetime.now(timezone.utc).isoformat()
            run_repo.finish_run(
                run_id=run_id,
                status=final_status,
                total=len(results),
                passed=passed,
                failed=failed,
                error_count=error_count,
                finished_at=finished_at,
            )
            from cli.sync_queue import enqueue
            enqueue("api_collection_run", run_id, "upsert")

        return {
            "run_id": run_id,
            "collection_id": collection_id,
            "collection_name": col["name"],
            "status": final_status,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
