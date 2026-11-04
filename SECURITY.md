# Security and limitations

## What this tool does

DecoyBench sends requests to a target you choose and records what comes back. Point it only at systems you are authorised to test.

## Built-in boundaries

- **Targets.** Only numeric loopback or RFC 5737 documentation addresses are accepted, with no DNS lookup. A numeric private lab address needs `BENCH_ALLOW_PRIVATE_TARGET=1`.
- **Nothing changes on the target.** No control header, authorisation or configuration change is sent.
- **Response handling.**
  - Every response is scanned against the persona and model-disclosure lists, plus any deployment list you supply.
  - Raw forbidden matches and credential-bearing bodies are not saved.
  - Headers are credential-redacted.
- **Results stay local.** They are written only to the folder you name.

## Treat results as sensitive

Results hold response bodies (base64) from your target. Review them before sharing.

## Known limitations

- **Fixture runs.** `--dry-run` runs measure the harness and its fixture only. They never measure or qualify a model or a deployment.
- **Lexical checks only.** Replies are not judged for meaning or safety. See `bench/README.md` for known false positives and negatives.
- **Ingress timing.** The ingress mode has a fixed ten-second absolute limit. Its built-in fixture can show about one-second connection retries at eight clients on Linux (listen backlog).
- **Server-side data.** No GPU, runtime or server identity is collected.

## Reporting a vulnerability

Report it privately through this repository's private vulnerability reporting, not in a public issue.
