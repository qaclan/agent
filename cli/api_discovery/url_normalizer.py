from __future__ import annotations
import re
from urllib.parse import urlparse

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_INT_RE = re.compile(r'^\d+$')
_HEX_RE = re.compile(r'^[0-9a-f]{20,}$', re.IGNORECASE)
_SEMVER_RE = re.compile(r'^v\d+(\.\d+)*$')


def _prev_segment_name(result: list[str]) -> str:
    """Return a param name based on the preceding path segment."""
    for seg in reversed(result):
        if not (seg.startswith('{') and seg.endswith('}')):
            clean = seg.rstrip('s')  # naive singularize: users → user
            return clean + '_id' if not clean.endswith('_id') else clean
    return 'id'


def normalize_path(path: str) -> str:
    """Replace dynamic segments (IDs, UUIDs, hashes) with {param} placeholders."""
    segments = path.strip('/').split('/')
    result = []
    for seg in segments:
        if not seg:
            continue
        if _UUID_RE.match(seg):
            result.append('{uuid}')
        elif _INT_RE.match(seg):
            result.append('{' + _prev_segment_name(result) + '}')
        elif _HEX_RE.match(seg):
            result.append('{hash}')
        elif _SEMVER_RE.match(seg):
            result.append(seg)  # keep version literals: v1, v2.0
        else:
            result.append(seg)
    return '/' + '/'.join(result) if result else '/'


def normalize_url(url: str) -> str:
    """Extract and normalize the path from a full URL."""
    try:
        parsed = urlparse(url)
        return normalize_path(parsed.path or '/')
    except Exception:
        return '/'
