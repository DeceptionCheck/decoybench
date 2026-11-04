# DecoyBench

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
Fixture measurements are not model qualification. This is a private release
candidate; owner IP, corpus and publication approval remain separate.
