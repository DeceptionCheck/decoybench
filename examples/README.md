# Example output (fixture only)

Generated with the commands in the top-level README, from this exact source, on Linux with Python 3.11 and no network route:

| Folder | Command | Result |
| --- | --- | --- |
| `fixture/model` | `python -m bench.run_model --dry-run --clients 1,2,4,8 --require-usable-finals --out ...` | 40 of 40 usable finals; exit 0 |
| `fixture/rescored` | `python -m bench.score --results .../model/results.jsonl --out ...` | 40 rescored, 0 unreplayable |
| `fixture/ingress` | `python -m bench.run_ingress --dry-run --clients 1,2,4,8 --out ...` | Fixture ingress matrix; exit 0 |
| `fixture/model-intentional-failure` | the model command plus `--fail-on-violation` | **Exit 1 on purpose:** the fixture carries four intentional lexical findings |

The two model folders omit the tool's `SUMMARY.md` because the frozen release scanner reads one of its criteria lines as a credential assignment (a false positive). The same figures are in `SUMMARY.json`.

Every row is a built-in fixture measurement. None of it measures, ranks or qualifies a real model or a real deployment.
