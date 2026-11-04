"""Direct-HTTP ingress harness. --dry-run qualifies local measuring code only.

The mode argument labels operator-configured deployment state. It never sends
a control header or changes remote configuration. Session identity in this
build is source plus surface, with a 30-minute idle timeout, not research IDs.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid


# Support the contract's direct script invocation as well as python -m.
ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from bench.corpus import DEFAULT_CASES, load_cases, schedule
from bench.measure import forbidden_terms, origin, request, summarize, telemetry


class LocalTarget(str):
    def __new__(cls,value,backend):
        result=super().__new__(cls,value);result.backend=backend;return result


@contextmanager
def local_decoy():
    """Run a disposable model-off HMI with real handlers and private audit log."""
    try:
        from decoy_web.server import DecoyHTTPServer
        from sim.eventlog import EventLog
        from sim.station import StationSim
    except ModuleNotFoundError as error:
        if error.name.split('.')[0] not in {'decoy_web','sim'}:raise
        from bench.ingress_fixture import neutral_ingress
        with neutral_ingress() as (target,audit):yield LocalTarget(target,'neutral-standalone-wire-fixture'),audit
        return
    with tempfile.TemporaryDirectory(prefix="psz-bench-") as folder:
        event_path = Path(folder) / "events.jsonl"
        saved = {key: os.environ.get(key) for key in ("PSZ_MODEL", "PSZ_BRAIN_URL")}
        os.environ.update(PSZ_MODEL="off", PSZ_BRAIN_URL="")
        try:
            server = DecoyHTTPServer("hmi", StationSim(), EventLog(event_path), host="127.0.0.1")
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                yield LocalTarget(f"http://127.0.0.1:{server.server_port}",'application-deterministic-handlers'), event_path
            finally:
                server.shutdown()
                server.server_close()
                thread.join(1)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def condition(target, cases, count, clients, mode, marker, terms, event_path=None, *, cookies=True):
    """Run one closed-loop condition, preserving pairs within each worker."""
    queues = schedule(cases, count, clients)
    barrier = threading.Barrier(clients)
    def worker(index):
        rows = []
        jar = CookieJar() if cookies else None
        barrier.wait()
        for pair, case in queues[index]:
            previous = None
            for repetition in range(2):
                ident = f"{marker}-{index}-{pair}-{repetition}"
                row, signature = request(target, case, marker, ident, terms, cookie_jar=jar)
                paired = previous is not None and row["complete"] and rows[-1]["complete"]
                # A throttle did not reach the same functional reply contract.
                comparable = paired and row['status_matches'] and rows[-1]['status_matches'] and row['status'] != 429 and rows[-1]['status'] != 429
                row.update(mode_label=mode, clients=clients, worker=index, pair=pair, repetition=repetition,
                           paired_response_changed=(signature != previous) if paired else None,
                           memo_matches=(signature == previous) if comparable else None)
                rows.append(row)
                previous = signature
        return rows
    with ThreadPoolExecutor(max_workers=clients) as pool:
        rows = [row for result in pool.map(worker, range(clients)) for row in result]
    # Audit is written after the HTTP body; allow its final flush to catch up.
    events = None
    if event_path is not None:
        until = time.monotonic() + 1
        while True:
            events = telemetry(event_path, marker)
            if len(events) >= len(rows) or time.monotonic() >= until:
                break
            time.sleep(.01)
    return rows, dict(summarize(rows, events), clients=clients, mode_label=mode, correlation=marker)


def run(args, target, event_path):
    """Write safe request artifacts and a separate summary with provenance."""
    started_utc = datetime.now(timezone.utc).isoformat()
    origin(target)
    cases = load_cases(args.cases)
    terms = forbidden_terms(args.denylist)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    result_path, summary_path = output / (stamp + ".jsonl"), output / (stamp + ".summary.json")
    conditions = []
    with result_path.open("x", encoding="utf-8", newline="\n") as stream:
        for clients in args.clients:
            marker = "psz-bench-" + uuid.uuid4().hex
            rows, summary = condition(target, cases, args.requests, clients, args.mode, marker, terms, event_path,
                                      cookies=getattr(args,'cookies','per-client')=='per-client')
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            conditions.append(summary)
    fingerprint_files = ["brain/config/PROFILE.json", "brain/config/PROMPTS.json", "brain/integration/validator_v2.py"]
    try:commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):commit=None
    report = {"schema": "ingress-v1", "start_utc": stamp, "dry_run": args.dry_run,
              'started_utc': started_utc, 'completed_utc': datetime.now(timezone.utc).isoformat(),
              'python_version': sys.version, 'platform': sys.platform,
              'code_sha256': {name:hashlib.sha256((ROOT/'bench'/name).read_bytes()).hexdigest()
                              for name in ('run_ingress.py','measure.py','corpus.py','artifacts.py','privacy.py')},
              "mode_label": args.mode, "model_enabled_verified": False,
              "qualification": "local deterministic fixture only" if args.dry_run else "operator-configured origin; installed gates not certified",
              "session_contract": "server-issued cookies retained per worker; research IDs are correlation only" if getattr(args,'cookies','per-client')=='per-client' else "fresh connections without cookie persistence; repeated rows may be different server sessions",
              "cookies": getattr(args,'cookies','per-client'),
              "deployment_denylist_loaded": bool(args.denylist),
              "dry_run_backend": getattr(target,'backend',None),
              "cases_sha256": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),
              "code_commit": commit,
              "fingerprints": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() if (ROOT/name).is_file() else None for name in fingerprint_files},
              "conditions": conditions}
    summary_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines=['# DecoyBench ingress results','',report['qualification'],
           'Backend: '+str(report['dry_run_backend'] or 'operator-configured origin')+'.',
           'Mode is a label, not proof that a model ran. Missing telemetry remains unknown.','',
           '| Clients | Requests | Complete HTTP | Functional replies | Throttled 429 | Functional p50 s | Functional p95 s | Four-second misses | Status mismatches |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    lines.extend('| '+' | '.join(str(row[key]) for key in ('clients','requests','completed','functional_completed','throttled_429','functional_p50_s','functional_p95_s','deadline_misses_4s','status_mismatches'))+' |' for row in conditions)
    lines += ['', 'Functional means a complete reply with the corpus-expected status, excluding 429. It is not model qualification.',
              'All-response latency remains in the JSON. Paired response changes involving a throttle/status mismatch are retained separately from functional memo comparisons.']
    lines+=['','## Fallback and response diversity','',
            '| Clients | Kind | Requests | Fallback rate | Distinct bodies per100 requests |',
            '| --- | --- | --- | --- | --- |']
    for row in conditions:
        for kind,value in row['by_kind'].items():
            lines.append(f"| {row['clients']} | {kind} | {value['requests']} | {value['fallback_rate']} | {value['distinct_bodies_per_100_requests']} |")
    lines+=['','No installed model, second-machine route or native drain qualification is implied.','']
    (output/(stamp+'.SUMMARY.md')).write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({"results": str(result_path.resolve()), "summary": str(summary_path.resolve())}))
    return int(any(summary[key] for summary in conditions for key in
                   ("failures", "deadline_misses_4s", "forbidden_responses", "credential_responses", "memo_mismatches", "status_mismatches", "telemetry_input_problem")))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target", help="numeric lab HTTP origin; required outside dry run")
    parser.add_argument("--cases", "--mix", dest='cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument("--mode", choices=("off", "on"), default="off")
    parser.add_argument("--clients", type=lambda value: [int(n) for n in value.split(",")], default=[1, 2, 4, 8])
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--event-log", type=Path, help="privileged local audit for source/fallback counts")
    parser.add_argument('--cookies',choices=('per-client','none'),default='per-client',
                        help='retain server-issued cookies separately for each client, or explicitly disable persistence')
    parser.add_argument("--denylist", default=os.environ.get("DC_DENYLIST"))
    parser.add_argument("--out", type=Path, default=ROOT / "bench/results")
    args = parser.parse_args(argv)
    if args.requests < 4 or args.requests % 4 or not args.clients or any(n not in (1, 2, 4, 8) for n in args.clients):
        parser.error("requests must be a multiple of four; clients are 1,2,4,8")
    if args.dry_run:
        if args.mode != "off" or args.target or args.event_log:
            parser.error("dry run owns its model-off target and audit log")
        with local_decoy() as (target, log):
            return run(args, target, log)
    if not args.target:
        parser.error("--target is required")
    return run(args, args.target, args.event_log)


if __name__ == "__main__":
    raise SystemExit(main())
