# Final BTP result tables

Regenerate every table with:

```bash
python3 src/generate_final_results.py
```

The generator reads only committed, unmodified JSON result artifacts. It does not
run experiments or use numbers from documentation or the base-paper PDF.

| Item | Outputs | Source JSON | Derived calculations | Seed information | Statistical scope |
| --- | --- | --- | --- | --- | --- |
| Module 1 metrics and ablation | `module1_key_metrics_and_ablation.md` | `results/module1_urban.json`, `results/module1_highway.json`, `results/radio_module1_urban.json`, `results/radio_module1_highway.json`, `results/radio_ablation_highway.json` | orphan fraction × 100; stored current-default ablation deltas | urban: 20; highway: 20; current-default highway ablation: 10 | Aggregate descriptive results; no reconstructed uncertainty. |
| Module 2 trust/security and free ride | `module2_trust_security_and_free_ride.md` | `results/module2_urban.json`, `results/radio_freeride_urban.json` | fractions × 100 for percentage columns | urban: 12 | Aggregate means only; no new significance test. |
| Priority bypass and DoS defence | `priority_bypass_and_dos_defence.md` | `results/priority_bypass_urban.json`, `results/priority_bypass_highway.json`, `results/priority_defence_urban.json`, `results/priority_defence_highway.json`, `results/radio_bypass_urban.json`, `results/radio_bypass_highway.json`, `results/radio_defence_urban.json`, `results/radio_defence_highway.json` | headline fraction matched from stored headline values | urban: 12; highway: 12 | Stored paired p-value only; other values are aggregate means. |
| Crypto sizes, timings and decomposition | `crypto_sizes_timings_and_transmission.md` | `results/crypto_bench.json`, `results/priority_cryptodecomp_urban.json`, `results/priority_cryptodecomp_highway.json` | None | crypto decomposition: not encoded in source JSON | Stored benchmark means and paired p-values only. |
| Radio robustness verdicts | `radio_robustness_verdict.md` | `results/radio_coverage_urban.json`, `results/radio_coverage_highway.json`, `results/radio_defence_urban.json`, `results/radio_defence_highway.json`, `results/radio_freeride_urban.json`, `results/radio_greed_urban.json`, `results/radio_greed_highway.json`, `results/radio_module1_urban.json`, `results/radio_module1_highway.json`, `results/radio_ablation_highway.json`, `results/radio_crypto.json`, `results/radio_bypass_urban.json`, `results/radio_bypass_highway.json` | verdict rules are listed in the generated table; greed damage/auth and detect≤FPR are evaluated separately; no result number is introduced outside the source artifacts | coverage: 6; defence/free ride/greed: 12; Module 1: 20; ablation: 10; crypto: analytic from benchmark assumptions | Stored statistics and direction checks only. |

## Boundaries and gaps

- All non-baseline simulation outputs shown here are aggregate/descriptive unless a stored statistic is explicitly named.
- No confidence interval is reconstructed from aggregate means.
- The crypto-decomposition JSON does not encode its seed count; the generated output leaves it unspecified.
- No formal-verification table is generated because no committed machine-readable Scyther result artifact exists.
- No Module 4 result is generated; Module 4 remains Deferred / Future Work.
- Base-paper Figures 11–15 remain separately generated in `figures/baseline/`.

`manifest.json` records source hashes, formulas, seed metadata and output hashes.
