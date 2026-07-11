from __future__ import annotations
import re
from cli.api_discovery.url_normalizer import normalize_url

_SKIP_SEGMENTS = {"api", "rest", "graphql", "gateway", "gql"}
_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$", re.IGNORECASE)


def suggest_folder_name(url: str) -> str | None:
    """Derive a one-level folder name from a request URL's first meaningful path
    segment. Reuses url_normalizer's dynamic-segment detection (IDs/UUIDs/hashes
    already collapsed to {param} placeholders) so numeric/UUID segments are
    skipped without re-implementing that heuristic. Returns None when no
    meaningful segment exists (root path, or every segment is a namespace/
    version/ID) — caller should leave the request at collection root."""
    path = normalize_url(url)
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        if seg.startswith("{") and seg.endswith("}"):
            continue
        if seg.lower() in _SKIP_SEGMENTS:
            continue
        if _VERSION_RE.match(seg):
            continue
        return seg
    return None
