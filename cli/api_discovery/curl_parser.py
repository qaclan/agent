from __future__ import annotations
import base64
import json
import logging
import os
import re
import shlex
from urllib.parse import urlsplit, urlunsplit, parse_qsl

from cli.api_discovery.har_parser import parse_multipart_text

logger = logging.getLogger("qaclan.curl_parser")

_CONTINUATION_RE = re.compile(r"[\\^]\s*\r?\n")
_LEADING_PROMPT_RE = re.compile(r"^[\$>]\s*")
# Bash ANSI-C quoting: $'...\r\n...'. shlex has no notion of this — left alone,
# the literal '$' stays and escapes like \r\n never become real bytes. Browsers'
# "Copy as cURL" commonly emits --data-raw $'...' for multipart bodies, so this
# must be expanded to a plain-quoted token before shlex.split ever sees it.
_ANSI_C_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
_ANSI_C_ESCAPES = {
    "n": "\n", "r": "\r", "t": "\t", "\\": "\\", "'": "'", '"': '"',
    "a": "\a", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
}


def _decode_ansi_c(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in _ANSI_C_ESCAPES:
            out.append(_ANSI_C_ESCAPES[s[i + 1]])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _expand_ansi_c_quotes(command: str) -> str:
    def repl(m):
        decoded = _decode_ansi_c(m.group(1))
        # Re-quote as a normal single-quoted token; embedded literal quotes use
        # the standard '\'' shell idiom so shlex still parses it as one token.
        return "'" + decoded.replace("'", "'\\''") + "'"
    return _ANSI_C_RE.sub(repl, command)

_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}
_IGNORED_FLAGS_NO_ARG = {
    "--compressed", "-s", "--silent", "-v", "--verbose", "-i", "--include",
    "-k", "--insecure", "-L", "--location", "--http1.1", "--http2", "-#",
    "--progress-bar", "-f", "--fail",
}


def _split_commands(text: str) -> list[str]:
    """Join backslash/caret line continuations, then split into individual
    curl invocations on newlines only. Deliberately does NOT split on bare
    ';'/'&&' — those characters routinely appear inside quoted header
    values (e.g. 'Cookie: a=1; b=2') and a naive split there would corrupt
    a single command instead of separating multiple ones."""
    joined = _CONTINUATION_RE.sub(" ", text.replace("\r\n", "\n"))
    commands = []
    for line in joined.split("\n"):
        line = _LEADING_PROMPT_RE.sub("", line.strip()).strip()
        if re.match(r"^curl(\.exe)?\b", line, re.IGNORECASE):
            commands.append(line)
    return commands


def _parse_one(command: str) -> dict | None:
    tokens = shlex.split(_expand_ansi_c_quotes(command), posix=True)
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
            row = {"key": key.strip(), "enabled": True}
            if val.startswith("@"):
                # curl file-upload syntax: field=@/path/to/file;filename=x;type=y
                # A shell-quoted arg like 'file=@"/a b/c.pdf"' keeps its inner
                # double quotes literal once shlex strips the outer single
                # quotes, so those must be peeled off by hand here.
                file_ref, _, extra = val[1:].partition(";")
                if len(file_ref) >= 2 and file_ref[0] == file_ref[-1] and file_ref[0] in "\"'":
                    file_ref = file_ref[1:-1]
                filename_override = None
                type_override = None
                for part in extra.split(";"):
                    if part.startswith("filename="):
                        filename_override = part[len("filename="):].strip()
                    elif part.startswith("type="):
                        type_override = part[len("type="):].strip()
                row["filename"] = filename_override or os.path.basename(file_ref)
                row["is_file"] = True
                if type_override:
                    row["content_type"] = type_override
                try:
                    with open(file_ref, "rb") as f:
                        row["value"] = base64.b64encode(f.read()).decode("ascii")
                except OSError:
                    row["value"] = ""
                    logger.warning(
                        "curl_parser: could not read form file %r referenced by --form; "
                        "imported field will have no content", file_ref,
                    )
            else:
                row["value"] = val.strip()
            form_rows.append(row)
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

    # Chrome/DevTools "Copy as cURL" emits multipart bodies as --data-raw with
    # the literal MIME text (boundaries + headers) instead of -F flags. Detect
    # that via the Content-Type header and decode it the same way HAR bodies are.
    if not is_multipart and raw_data_parts:
        content_type_header = next(
            (h["value"] for h in headers if h["key"].lower() == "content-type"), ""
        )
        if "multipart/form-data" in content_type_header.lower():
            parsed_fields = parse_multipart_text(content_type_header, "".join(raw_data_parts))
            if parsed_fields:
                is_multipart = True
                form_rows = parsed_fields
                raw_data_parts = []

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
