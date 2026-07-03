from __future__ import annotations
import json
import logging
import re
import shlex
from urllib.parse import urlsplit, urlunsplit, parse_qsl

logger = logging.getLogger("qaclan.curl_parser")

_CONTINUATION_RE = re.compile(r"[\\^]\s*\r?\n")
_LEADING_PROMPT_RE = re.compile(r"^[\$>]\s*")

_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}
_IGNORED_FLAGS_NO_ARG = {
    "--compressed", "-s", "--silent", "-v", "--verbose", "-i", "--include",
    "-k", "--insecure", "-L", "--location", "--http1.1", "--http2", "-#",
    "--progress-bar", "-f", "--fail",
}


def _split_commands(text: str) -> list[str]:
    """Join backslash/caret line continuations, then split into individual
    curl invocations on newlines/&&/;."""
    joined = _CONTINUATION_RE.sub(" ", text.replace("\r\n", "\n"))
    segments = re.split(r"\n|&&|;", joined)
    commands = []
    for seg in segments:
        seg = _LEADING_PROMPT_RE.sub("", seg.strip()).strip()
        if re.match(r"^curl(\.exe)?\b", seg, re.IGNORECASE):
            commands.append(seg)
    return commands


def _parse_one(command: str) -> dict | None:
    tokens = shlex.split(command, posix=True)
    tokens = tokens[1:]  # drop leading 'curl'/'curl.exe'

    method = None
    url = None
    headers: list[dict] = []
    raw_data_parts: list[str] = []
    form_rows: list[dict] = []
    is_multipart = False
    user = None
    cookie = None
    force_query = False

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request"):
            i += 1
            method = tokens[i].upper()
        elif t in ("-H", "--header"):
            i += 1
            key, _, val = tokens[i].partition(":")
            headers.append({"key": key.strip(), "value": val.strip(), "enabled": True})
        elif t in _DATA_FLAGS:
            i += 1
            raw_data_parts.append(tokens[i])
        elif t in ("-F", "--form"):
            i += 1
            is_multipart = True
            key, _, val = tokens[i].partition("=")
            form_rows.append({"key": key.strip(), "value": val.strip(), "enabled": True})
        elif t in ("-u", "--user"):
            i += 1
            user = tokens[i]
        elif t in ("-b", "--cookie"):
            i += 1
            cookie = tokens[i]
        elif t == "-G":
            force_query = True
        elif t in _IGNORED_FLAGS_NO_ARG:
            pass
        elif not t.startswith("-"):
            if url is None:
                url = t
        i += 1

    if not url:
        return None

    split = urlsplit(url)
    params = [
        {"key": k, "value": v, "enabled": True}
        for k, v in parse_qsl(split.query, keep_blank_values=True)
    ]
    clean_url = urlunsplit((split.scheme, split.netloc, split.path, "", ""))

    if cookie:
        headers.append({"key": "Cookie", "value": cookie, "enabled": True})

    auth_type = "none"
    auth_config: dict = {}
    if user:
        username, _, password = user.partition(":")
        auth_type = "basic"
        auth_config = {"username": username, "password": password}

    body_type = None
    body = None
    if is_multipart:
        body_type = "multipart"
        body = json.dumps(form_rows)
    elif raw_data_parts:
        if force_query:
            for part in raw_data_parts:
                for k, v in parse_qsl(part, keep_blank_values=True):
                    params.append({"key": k, "value": v, "enabled": True})
        else:
            body_type = "raw"
            body = "&".join(raw_data_parts) if len(raw_data_parts) > 1 else raw_data_parts[0]

    if not method:
        method = "POST" if (raw_data_parts and not force_query) or is_multipart else "GET"

    return {
        "name": f"{method} {split.path or '/'}",
        "method": method,
        "url": clean_url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": auth_type,
        "auth_config": auth_config,
    }


def parse_curl(text: str) -> list[dict]:
    """Parse one or more curl commands (shell-line-continuation aware) into
    the standard request-dict list used across cli/api_discovery/*_parser.py."""
    results = []
    for command in _split_commands(text):
        try:
            req = _parse_one(command)
            if req:
                results.append(req)
        except Exception:
            logger.warning("parse_curl: skipping unparseable command: %s", command[:120])
    logger.info("parse_curl: extracted %d requests", len(results))
    return results
