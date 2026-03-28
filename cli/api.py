import requests
from cli.config import get_server_url


def _raise_with_body(r):
    """Like raise_for_status but includes the response body in the error message."""
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        body = r.text[:500]
        raise requests.exceptions.HTTPError(f"{e} — {body}", response=r) from e


def _headers(auth_key):
    return {
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
    }


def validate_auth_key(server_url, auth_key):
    """GET /api/auth/me — returns user dict or None if 401."""
    r = requests.get(f"{server_url}/api/auth/me", headers=_headers(auth_key))
    if r.status_code == 200:
        return r.json()
    return None


def sync_status(auth_key):
    """GET /api/sync/status — health check."""
    r = requests.get(f"{get_server_url()}/api/sync/status", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_run(auth_key, payload):
    """POST /api/sync/run — push test run results."""
    r = requests.post(f"{get_server_url()}/api/sync/run", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_feature(auth_key, payload):
    """POST /api/sync/feature — push feature metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/feature", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_suite(auth_key, payload):
    """POST /api/sync/suite — push suite metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/suite", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_script(auth_key, payload):
    """POST /api/sync/script — push script metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/script", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_project(auth_key, payload):
    """POST /api/sync/project — push project metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/project", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def pull_workspace(auth_key):
    """GET /api/pull/workspace — fetch workspace structure."""
    r = requests.get(f"{get_server_url()}/api/pull/workspace", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def pull_runs(auth_key, page=1, per_page=50):
    """GET /api/pull/runs — fetch run history."""
    r = requests.get(
        f"{get_server_url()}/api/pull/runs",
        params={"page": page, "per_page": per_page},
        headers=_headers(auth_key),
    )
    _raise_with_body(r)
    return r.json()


def pull_run_detail(auth_key, run_id):
    """GET /api/pull/runs/<run_id> — fetch single run with script results."""
    r = requests.get(f"{get_server_url()}/api/pull/runs/{run_id}", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()
