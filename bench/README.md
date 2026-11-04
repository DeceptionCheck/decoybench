# DecoyBench

The standalone standard-library harness measures model persona adherence,
usable final-answer latency and decoy ingress behavior. Python 3.11 or newer
is sufficient. No model is started or downloaded. Run from the repository root:

```text
python -m bench.run_model --dry-run --clients 1,2,4,8 --seed 11047 --require-usable-finals --out results/model-fixture
python -m bench.score --results results/model-fixture/results.jsonl --out results/rescored
python -m bench.run_ingress --dry-run --clients 1,2,4,8 --out results/ingress-fixture
```

The model fixture intentionally includes a code violation. In a bench-only
copy, ingress uses a neutral wire fixture; in this application checkout it uses
actual deterministic application handlers. The backend is explicitly recorded.
Neither fixture is model inference.

The strict model-fixture command above requires all 40 planned samples to have
complete usable finals and exits 1 on any missing/failed final. Intentional code
violations remain visible: four code findings, one per client condition. Add
--fail-on-violation when lexical cleanliness is also required; this supplied
negative fixture then intentionally exits 1. SUMMARY.json and SUMMARY.md record
the selected exit criteria and result. Without either flag, exit 0 means only
that measurement artifacts were written, not that every sample passed. Rescore
exit 0 means recomputation completed; inspect its counts and rule findings.

The disposable fixture has a listen backlog of 64 and waits for its
accept loop before yielding its endpoint. It makes no warmup requests or retries.
The real transport retains the 150 ms setup cap and original selected deadline.

Installed clients retain server-issued cookies in separate in-memory jars per
worker, using standard-library domain, path, expiry and Secure checks. Cookie
values are never exported. Use --cookies none for an explicit fresh-session
experiment. Research headers remain correlation only. A pair crossing a 429
or other unexpected status is a paired-response change, not a functional memo
comparison. The Markdown summary separates useful replies from throttles.

## Bare-model measurements

```text
python -m bench.run_model --endpoint http://127.0.0.1:19450/v1/chat/completions --model my-model --system bench/corpus/v1.0/example_system.txt --corpus bench/corpus/v1.0/prompts.jsonl --deadline 4 --clients 1,2 --seed 11047 --runtime-id recorded-runtime --hardware-id recorded-hardware --policy-id own-persona-v1 --out results/my-model
```

Set BENCH_API_KEY in the invoking environment if needed. It is sent only in an
Authorization header. BENCH_CA_FILE supplies a private CA with normal TLS and
hostname checks. No redirects, automatic proxies or retries are used. Supply a
complete endpoint path. Never bypass a deployment's admission coordinator or
call an unowned model. The default contract is chat-completions SSE using
system/user messages and max_tokens. Use --no-stream for JSON responses.
For native llama.cpp use --api llama and the /completion endpoint; its plain
system/newline/user prompt format is recorded, not assumed equivalent to a chat
template. Providers requiring another contract need an explicit adapter.

Each client condition runs the corpus once. --repetitions adds trials. The
seed fixes ordering, not GPU determinism. DNS and TCP/TLS setup have a 150 ms
cap inside the selected original deadline. Success requires complete framing,
nonempty final content, natural stop and no tool call. A length finish,
reasoning-only response, missing SSE terminator or partial body is a failure,
even with HTTP 200. First visible content excludes reasoning and role deltas.
Usage, reasoning/cache token counts and native timings stay null if unreported.
Native stop flags require actual booleans. A string such as "false" is not a
natural stop. Negative native token counts are unknown, never measured counts.

results.jsonl contains safe request/final reply, all rule verdicts, HTTP status,
finish reason, setup/first-content/complete timings, tokens and failure category.
RUN.json contains system/corpus/code hashes, supplied runtime/hardware/policy
identities, seed, clients and deadline. Supplied identifiers are not verified
server pins. SUMMARY.json, SUMMARY.md and SHA256-MANIFEST.json accompany it.
HTTP 429 is separate and remains in the denominator. Successful complete replies
form nearest-rank p50/p95; failures also remain visible as completion misses.

## Fresh lexical scorer and privacy

score.py is a fresh public lexical scorer, separate from the private qualifier.
True means a violation: persona disclosure, prompt disclosure, reasoning
markers, code, operating instructions, action claims, unsupported interface
vocabulary or tool calls. Negations and quotes can be false positives;
paraphrases and false relationships can evade checks. Passing these rules is
not factuality, safety or model qualification. Semantic/judged scoring is NOT
RUN. No private qualifier, guardrail corpus or proprietary prompt pack ships.

The score command recomputes from stored final content without trusting stored
verdicts. Credential-bearing replies, configured denylist matches and overlap
with eight consecutive system-prompt words are suppressed before artifact
writes. Their hashes and lengths remain; they are explicitly not fully
replayable. System content is hash-only; raw reasoning is not retained.
Use --denylist or DC_DENYLIST for deployment-specific export restrictions.
Absent deployment input is recorded, not publication clearance.

corpus/v1.0/SCHEMA.json documents the fresh neutral fictional cases. Add stable
IDs, categories, prompts and allowed-interface vocabulary for your own persona.
The corpus manifest fixes the bytes. python -m bench.export --out PATH builds
a whitelist-only standalone archive with the existing MIT license. Owner
IP/release review remains separate. No publish operation exists in this tool.

## Installed ingress measurements

Run `python bench/run_ingress.py --dry-run` from the root for a disposable local
HMI with model off. Results are timestamped JSONL and summary JSON. The default
corpus is bench/corpus/v1.0/wire_mix.jsonl. `--mix` and `--cases` accept that
structured HTTP schema. A condition has 100
requests total, with 1, 2, 4 or 8 closed-loop clients, fresh connections, half
unknown-path traffic and round-robin remaining kinds. Each selected case is
repeated consecutively within its worker. Totals must divide by four.

For an operator-configured installed decoy, run both conditions separately:

```text
python bench/run_ingress.py --target http://192.0.2.10:8080 --mode on --event-log SERVER_AUDIT_FILE
python bench/run_ingress.py --target http://192.0.2.10:8080 --mode off --event-log SERVER_AUDIT_FILE
```

The operator must configure generation before each run. Mode is only a row
label. No control header, authorization, configuration change or model
admission change is sent. Numeric loopback or RFC 5737 example origins are
required, avoiding DNS. BENCH_ALLOW_PRIVATE_TARGET=1 explicitly permits an
authorized numeric private lab target. BENCH_CA_FILE supplies a private CA.
Fresh connections include setup and TLS in elapsed
time. The ten-second absolute limit aborts body trickles. Failures and
incomplete bodies count as four-second misses; they have no time to last byte
and are excluded from completion percentiles. p50 and p95 use nearest rank.
Failure and status-mismatch counts remain visible.

Session adaptation: the decoy groups by source plus surface with a 1800-second
idle timeout. Research headers are correlation only, not installed session
identifiers. Workers sharing an origin source share that application session.
Consecutive repeats compare exact status and body bytes, ignoring changing
Date headers. This checks the existing session implementation, not independent
header-selected sessions or restart/idle-expiry boundaries.

Every received response, including incomplete bytes and headers, is scanned
against the public persona and model-disclosure lists. Set DC_DENYLIST or pass
--denylist for the supplied deployment list; missing deployment input is
explicit in the summary and does not qualify publication. An unreadable
configured list fails the run. Raw forbidden matches and credential-bearing
bodies are not persisted. Safe body bytes are stored in base64 without
rewriting, with a SHA-256 and length. Headers are credential-redacted, or
omitted if forbidden. Memo comparisons use original in-memory bytes. No
request body, authorization value or private receipt is copied.

The optional privileged event log is joined using an exact per-condition
User-Agent marker. A full per-kind join is required for fallback rate; absent
or incomplete telemetry yields null. Source counts separate model, memo,
fallback, deterministic and off. A memo hit does not identify whether its
original was a fallback. The rate means responses actually labelled fallback,
not inferred ancestry. Diversity reports distinct completed body hashes and
that count divided by all requests of the kind, multiplied by 100.

Server-side model/cache/prompt and native GPU receipts, clock synchronization,
installed semantics, T-CONC and independent review remain required. This
harness does not collect GPU or certify model-on deployment. Local profile,
prompt, validator and code fingerprints do not assert a remote-server match.
REPORT.md separates local dry-run measurements from empty real model rows.
No request in this build session contacted an external origin.

Ingress summaries also separate HTTP status counts and throttled_429 from
functional_completed and functional_p50_s/functional_p95_s. The older p50_s and
p95_s fields describe all complete HTTP replies, including refusals/throttles.
A fast 429 is not a successful functional response. Model summaries likewise
retain throttling in the request denominator. Malformed usage envelopes and
duplicate JSON keys are per-request failures, not crashes. Legacy function calls
are tool calls. Visible reasoning-marker text is suppressed before artifact
writes, while its lexical verdict, original hash and byte count remain.

REPORT.md in the application checkout distinguishes historical local references
from unmeasured installed rows. The standalone archive contains the harness and
neutral fixtures; program-specific reports and private receipts remain separate
owner-review material.
