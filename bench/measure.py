"""Measure fresh HTTP connections through complete body, with a hard deadline.

Raw bytes exist in memory for memo equality. Artifacts retain safe bytes in
base64 and redacted headers; rejected content is fingerprinted, never copied.
Missing privileged telemetry stays unknown, regardless of the mode row label.
"""

import base64
from collections import Counter
import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request

from .privacy import FIELDS as CREDENTIALS, PRIVATE as PRIVATE_KEY, PROVIDER

REDACTED = '[redacted]'
from .corpus import KINDS
from .artifacts import assessment, safe_headers


NETWORKS = tuple(ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
_KEYS = "|".join(re.escape(key) for key in sorted(CREDENTIALS))
SENSITIVE = re.compile(rf'''(?i)(?:\b(?:{_KEYS})\b["']?\s*[:=]|<(?:\w+:)?(?:{_KEYS})\b|\bname\s*=\s*["'](?:{_KEYS})["'])''')


def origin(value):
    """Accept numeric lab origins only, with no DNS, credentials or path."""
    url = urlsplit(value)
    address = ipaddress.ip_address(url.hostname or "")
    if (url.scheme not in {"http", "https"} or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"} or address.version != 4
            or not (str(address) == "127.0.0.1" or any(address in net for net in NETWORKS)
                    or os.environ.get('BENCH_ALLOW_PRIVATE_TARGET')=='1' and address.is_private
                    and not address.is_multicast and not address.is_unspecified and int(address)!=4294967295)):
        raise ValueError("numeric loopback or documentation-range HTTP origin required")
    return url


def forbidden_terms(deployment_file=None):
    """Load public persona and model-disclosure terms plus an optional private list."""
    pack = Path(__file__).resolve().parents[2] / "AGENT-INPUT-PACK/01-WORK-ITEMS.md"
    public = []
    if pack.is_file():
        content = pack.read_text(encoding="utf-8-sig")
        public = content.split("Never write these strings anywhere, in any case or spelling: ", 1)[1].split(". They are retired", 1)[0].split(", ")
    terms = public + ["Meta AI", "Llama", "Muse", "language model", "AI assistant", "as an AI", "I am an AI"]
    if deployment_file:
        text = Path(deployment_file).read_text(encoding="utf-8-sig")
        extra = json.loads(text) if text.lstrip().startswith("[") else text.splitlines()
        if not isinstance(extra, list) or not all(isinstance(term, str) for term in extra):
            raise ValueError("invalid deployment denylist")
        terms += [term.strip() for term in extra if term.strip() and not term.startswith("#")]
    return sorted({term.casefold() for term in terms if term})


def scan_response(body, headers, terms):
    """Scan every received response, including headers, without copying matches."""
    text = body.decode("utf-8", "replace")
    combined = text.casefold() + "\n" + json.dumps(headers).casefold()
    matches = [hashlib.sha256(term.encode()).hexdigest() for term in terms if term in combined]
    # The audit redactor intentionally hides every XML/HTML or reformats JSON.
    # Those transformations do not imply that a response contains credentials.
    credentials = assessment(body, headers)[0]
    return matches, credentials


def request(target, case, marker, request_id, terms, hard_limit=10.0, *, cookie_jar=None):
    """Time connection setup, send and complete read; failures have no last byte."""
    url = origin(target)
    cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = (cls(url.hostname,url.port,timeout=hard_limit,context=ssl.create_default_context(cafile=os.environ.get('BENCH_CA_FILE') or None))
            if url.scheme=='https' else cls(url.hostname,url.port,timeout=hard_limit))
    body, headers, status, complete, error = b"", [], None, False, None
    started = time.perf_counter()
    timer = None
    try:
        conn.connect()
        active = conn.sock
        def abort():
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(max(0, hard_limit - (time.perf_counter() - started)), abort)
        timer.daemon = True
        timer.start()
        sent_headers = dict(case["headers"], **{"User-Agent": marker, "X-Research-Request-ID": request_id,
                                             "X-Research-Session-ID": marker})
        cookie_request = Request(str(target).rstrip('/') + case['target'])
        if cookie_jar is not None:
            cookie_jar.add_cookie_header(cookie_request)
            if cookie_request.has_header('Cookie'):
                sent_headers['Cookie'] = cookie_request.get_header('Cookie')
        conn.request(case["method"], case["target"], base64.b64decode(case["body_b64"]), sent_headers)
        response = conn.getresponse()
        status, headers = response.status, response.getheaders()
        if cookie_jar is not None:
            cookie_jar.extract_cookies(response, cookie_request)
        try:
            chunks = []
            while chunk := response.read1(65536):
                chunks.append(chunk)
                body = b"".join(chunks)
            if response.length not in (None, 0):
                raise http.client.IncompleteRead(body, response.length)
            complete = time.perf_counter() - started < hard_limit
        except http.client.IncompleteRead as partial:
            body = partial.partial
            raise
        if not complete:
            error = "DeadlineExceeded"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        error = type(exc).__name__
    finally:
        elapsed = time.perf_counter() - started
        if timer:
            timer.cancel()
        conn.close()
    matches, credentials = scan_response(body, headers, terms)
    _, suppressed, suppression_reason = assessment(body, headers)
    suppressed = suppressed or bool(matches) or not complete
    row = {"request_id": request_id, "case_id": case["id"], "kind": case["kind"],
           "method": case["method"], "target": case["target"], "status": status,
           "expected_status": case["expectation"]["status"], "status_matches": status == case["expectation"]["status"],
           "elapsed_s": elapsed, "time_to_last_byte_s": elapsed if complete else None,
           "complete": complete, "error": error, "deadline_miss_4s": not complete or elapsed > 4,
           "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
           "body_b64": base64.b64encode(body).decode() if not suppressed else None,
           "body_suppressed": suppressed,
           "body_suppression_reason": "forbidden" if matches else "incomplete" if not complete else suppression_reason,
           "headers": safe_headers(headers) if not matches else None, "forbidden_fingerprints": matches,
           "credential_response": credentials}
    return row, (status, body)


def percentile(values, probability):
    """Nearest-rank percentile; no completed samples means unknown."""
    return sorted(values)[max(0, math.ceil(len(values) * probability) - 1)] if values else None


def telemetry(path, marker):
    """Read privileged HTTP audit rows correlated by our exact User-Agent.

    Correlation is measurement only. Neither research header is trusted by the
    application for session identity, routing, configuration or authorization.
    """
    if path is None:
        return None
    events = Telemetry()
    content = Path(path).read_bytes()
    lines = content.split(b"\n")
    events.coverage["deferred_bytes"] = len(lines.pop())
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("row_shape")
            http = event.get("http")
            if http is None:
                continue  # Normal Modbus rows are explicitly non-HTTP.
            if not isinstance(http, dict) or not isinstance(http.get("headers_subset"), dict):
                raise ValueError("http_shape")
            if http["headers_subset"].get("User-Agent") != marker:
                continue
            response = event.get("response")
            if (not isinstance(response, dict) or response.get("source") not in
                    {"deterministic", "model", "memo", "fallback", "off"} or event.get("disposition") not in KINDS):
                raise ValueError("correlated_response_shape")
            events.append({"disposition": event["disposition"], "response": {"source": response["source"]}})
        except (ValueError, TypeError, UnicodeError):
            events.coverage["invalid_rows"].append(number)
    events.coverage["complete"] = not events.coverage["invalid_rows"] and not events.coverage["deferred_bytes"]
    return events


class Telemetry(list):
    """Only safe correlated projections, with explicit input coverage status."""

    def __init__(self):
        super().__init__()
        self.coverage = {"complete": True, "invalid_rows": [], "deferred_bytes": 0}


def summarize(rows, events=None):
    """Separate failures, four-second misses, diversity and observed fallbacks."""
    completed = [row["elapsed_s"] for row in rows if row["complete"]]
    functional = [row['elapsed_s'] for row in rows if row['complete'] and row['status_matches'] and row['status'] != 429]
    coverage = getattr(events, "coverage", {"complete": events is not None})
    by_kind = {}
    for kind in KINDS:
        selected = [row for row in rows if row["kind"] == kind]
        observed = None if events is None else [event for event in events if event.get("disposition") == kind]
        sources = None if observed is None else dict(Counter((event.get("response") or {}).get("source", "unknown") for event in observed))
        good = [row for row in selected if row["complete"]]
        distinct = len({row["body_sha256"] for row in good})
        # Require a complete telemetry join; a partial log cannot certify a rate.
        rate = (sum(event["response"]["source"] == "fallback" for event in observed) / len(observed)
                if observed and len(observed) == len(selected) and coverage["complete"] and "unknown" not in sources else None)
        by_kind[kind] = {"requests": len(selected), "completed": len(good), "distinct_bodies": distinct,
                         "throttled_429": sum(row['status']==429 for row in selected),
                         "functional_completed": sum(row['complete'] and row['status_matches'] and row['status'] != 429 for row in selected),
                         "distinct_bodies_per_100_requests": distinct * 100 / len(selected) if selected else None,
                         "fallback_rate": rate, "telemetry_events": len(observed) if observed is not None else None,
                         "response_sources": sources}
    return {"telemetry_coverage": coverage, "telemetry_input_problem": events is not None and not coverage["complete"],
            "requests": len(rows), "completed": len(completed), "failures": len(rows) - len(completed),
            "p50_s": percentile(completed, .5), "p95_s": percentile(completed, .95),
            "status_counts": dict(Counter(str(row['status']) for row in rows)),
            "throttled_429": sum(row['status']==429 for row in rows),
            "functional_completed": len(functional),
            "functional_p50_s": percentile(functional,.5), "functional_p95_s": percentile(functional,.95),
            "max_s": max(completed, default=None), "deadline_misses_4s": sum(row["deadline_miss_4s"] for row in rows),
            "forbidden_responses": sum(bool(row["forbidden_fingerprints"]) for row in rows),
            "credential_responses": sum(row["credential_response"] for row in rows),
            "memo_mismatches": sum(row["memo_matches"] is False for row in rows),
            "status_mismatches": sum(not row["status_matches"] for row in rows), "by_kind": by_kind}
