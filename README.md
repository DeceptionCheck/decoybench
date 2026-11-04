# DecoyBench

> **This is the Sol implementation of DecoyBench, release R6** (repository `decoybench-sol`). Two other independent implementations share the DecoyBench name: Opus's 0.2.1 and Muse's. They are separate projects with different commands and result formats. This one runs from its source folder (`python -m bench...`) and installs nothing; keep each implementation in its own folder or virtual environment.

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

See bench/README.md for real endpoint commands, corpus schema, timing and
privacy rules, throttling and known lexical false positives/negatives.
Fixture measurements are not model qualification. License: MIT ([LICENSE](LICENSE),
[NOTICE.md](NOTICE.md)). Security and limitations: [SECURITY.md](SECURITY.md).
Example output: [examples/](examples/).
