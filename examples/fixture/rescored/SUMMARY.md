# DecoyBench results

Fixture run, no model inference.

Requests: 40. Usable final replies: 40. Failures: 0. 429: 0.
Complete response p50/p95 seconds: 0.004257925999979761 / 0.01658481300000858.
First visible content p50/p95 seconds: 0.003811063999989983 / 0.016506541000012476.
Failures remain in the denominator. Quantiles above use successful complete replies only.

| Category | Requests | Usable final | Lexical violations |
| --- | --- | --- | --- |
| action_claim_probe | 4 | 4 | {} |
| code_probe | 4 | 4 | {"code": 4} |
| identity_request | 4 | 4 | {} |
| interface_probe | 4 | 4 | {} |
| missing_resource | 4 | 4 | {} |
| normal_request | 4 | 4 | {} |
| prompt_probe | 4 | 4 | {} |
| reasoning_probe | 4 | 4 | {} |
| rejected_form | 4 | 4 | {} |
| unsupported_method | 4 | 4 | {} |

Rules are lexical. Negations and quotes can be false positives; paraphrases can evade them.
Reasoning token counts are null when the endpoint does not report them. Missing data is not zero.
Suppressed reply exports: 0. These rows cannot be fully rescored from stored text.
No private qualification policy, guardrail corpus or proprietary prompt pack is included.
