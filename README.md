# DecoyBench

**An open harness for measuring whether a language model can serve as a decoy: complete usable replies, latency against a deadline, fallback, and failure, with a deterministic row for comparison.** This is the reference implementation, release R6. Two alternate implementations built from the same specification and tests are published separately as [decoybench-alt-a](https://github.com/DeceptionCheck/decoybench-alt-a) and [decoybench-alt-b](https://github.com/DeceptionCheck/decoybench-alt-b); they have different commands and result formats, so keep each in its own folder.

Built for the Meta Global AI Developer Hackathon, November 2026, by Deception Check, Inc.

## Development attribution

Sol assisted this reference R6 implementation. Opus assisted [alternative A](https://github.com/DeceptionCheck/decoybench-alt-a). Muse / Meta Spark 1.3 assisted [alternative B](https://github.com/DeceptionCheck/decoybench-alt-b). All were developed under Deception Check’s direction. These are coding credits, not claims that fixture runs invoke these models.

## Submission links

| | |
|---|---|
| Demo video | https://youtu.be/c8zRYXETCEo |
| Hosted demo, limited-time judge access | https://meta.deceptioncheck.ai |
| Research report with the results tables and the model program | https://meta.deceptioncheck.ai/research/DecoyBench-Report.html |
| The decoy this harness was built to measure (AGPL-3.0) | https://github.com/DeceptionCheck/pump-station-zero-community |

## What it measures

- **Checks on every reply, rules first:** persona break, prompt leak, reasoning leak, code output, operational instruction, action or telemetry claim, invented interface, length.
- **Latency at a stated boundary:** first visible token, complete reply, deadline misses at four seconds, and, from a second machine, send to last byte against an installed decoy.
- **Concurrency:** 1, 2, 4, and 8 offered clients.
- **The deterministic row:** the same requests served by fixed content, measured the same way. Model-correct, accepted by the validator, and served after fallback are always three separate columns.

Fixture runs contain no inference; a green exit alone is not proof that a model answered. The report linked above has the real-model rows (raw request text against typed task, the matched head-to-head, the counterbalanced confirmation, and the installed path) with the misses beside the wins.

## Quick start

Measure complete usable model replies and a decoy's installed ingress. Python
3.11 or newer, standard library only. Start without a model:

```text
python -m bench.run_model --dry-run --clients 1,2,4,8 --require-usable-finals --out results/model
python -m bench.score --results results/model/results.jsonl --out results/rescored
python -m bench.run_ingress --dry-run --clients 1,2,4,8 --out results/ingress
python -m unittest discover -s tests -v
```

The model fixture deliberately has four lexical code findings. The strict
command requires40/40 usable finals, not lexical cleanliness. Add
--fail-on-violation to reject those intentional findings. Default exit0 alone
is not proof of successful replies.

The starter corpus in `bench/corpus/v1.0/` is a ten-prompt sample; the sanitized full corpus follows in a later release. See bench/README.md for real endpoint commands, corpus schema, timing and
privacy rules, throttling and known lexical false positives/negatives.
Fixture measurements are not model qualification. License: MIT ([LICENSE](LICENSE),
[NOTICE.md](NOTICE.md)). Security and limitations: [SECURITY.md](SECURITY.md).
