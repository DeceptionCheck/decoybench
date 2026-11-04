"""Load the supplied direct-HTTP corpus and schedule consecutive request pairs."""

import base64
import json
from pathlib import Path


KINDS = ("unknown_path", "rejected_form", "unsupported_method", "operational_unavailable")
DEFAULT_CASES = Path(__file__).resolve().parent / "corpus/v1.0/wire_mix.jsonl"


def load_cases(path=DEFAULT_CASES):
    """Require the four canonical kinds and valid structured HTTP requests."""
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if {case["kind"] for case in cases} != set(KINDS):
        raise ValueError("corpus must contain exactly the four declared kinds")
    for case in cases:
        if not case["target"].startswith("/") or any(c in case["target"] for c in "\r\n"):
            raise ValueError("invalid origin-relative target")
        if not case["method"].isalpha() or not isinstance(case["headers"], dict):
            raise ValueError("invalid structured HTTP request")
        base64.b64decode(case["body_b64"], validate=True)
    return cases


def schedule(cases, requests, clients):
    """Return closed-loop worker queues, half unknown, every selection repeated.

    Request totals must be divisible by four: alternating pairs give exactly
    half unknown traffic. Pairs stay on one worker and are never interleaved
    within that worker. Each condition contains requests total, not per worker.
    """
    if requests < 4 or requests % 4 or clients not in (1, 2, 4, 8):
        raise ValueError("requests must be a positive multiple of four; clients 1,2,4,8")
    by_kind = {kind: [case for case in cases if case["kind"] == kind] for kind in KINDS}
    queues, counters = [[] for _ in range(clients)], {kind: 0 for kind in KINDS}
    for pair in range(requests // 2):
        kind = "unknown_path" if pair % 2 == 0 else KINDS[1 + (pair // 2) % 3]
        case = by_kind[kind][counters[kind] % len(by_kind[kind])]
        counters[kind] += 1
        queues[pair % clients].append((pair, case))
    return queues
