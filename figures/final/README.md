# Final BTP result figures

Regenerate every figure with:

```bash
python3 src/generate_final_results.py
```

The generator reads only committed, unmodified JSON result artifacts. It does not
run experiments or use numbers from documentation or the base-paper PDF.

| Item | Outputs | Source JSON | Derived calculations | Seed information | Statistical scope |
| --- | --- | --- | --- | --- | --- |
| Module 1 protocol comparison | `module1_protocol_comparison.png`, `module1_protocol_comparison.pdf` | `results/module1_urban.json`, `results/module1_highway.json`, `results/radio_module1_urban.json`, `results/radio_module1_highway.json` | orphan fraction × 100 = orphan percentage | urban: 20; highway: 20 | Aggregate means only; no uncertainty intervals. |
| Module 2 trust/security and free ride | `module2_trust_security_free_ride.png`, `module2_trust_security_free_ride.pdf` | `results/module2_urban.json`, `results/radio_freeride_urban.json` | fractions multiplied by 100 for percentage axes; reference ratio 1 denotes equal attacker and honest residual energy | urban: 12 | Aggregate means only; no uncertainty intervals or new significance tests. |
| Priority coverage/deadline | `priority_coverage_deadline.png`, `priority_coverage_deadline.pdf` | `results/priority_coverage_urban.json`, `results/priority_coverage_highway.json`, `results/radio_coverage_urban.json`, `results/radio_coverage_highway.json` | No new statistic; stored Spearman rho and p are displayed. | urban: 6; highway: 6 | Aggregate protocol means plus stored Spearman statistics; no uncertainty intervals. |
| Priority abuse/defence | `priority_abuse_defence.png`, `priority_abuse_defence.pdf` | `results/priority_defence_urban.json`, `results/priority_defence_highway.json`, `results/priority_greed_urban.json`, `results/priority_greed_highway.json`, `results/radio_defence_urban.json`, `results/radio_defence_highway.json`, `results/radio_greed_urban.json`, `results/radio_greed_highway.json` | fractions multiplied by 100 for percentage axes | urban: 12; highway: 12 | Aggregate means only; no new significance claim is made. |
| Crypto/radio robustness | `crypto_radio_robustness.png`, `crypto_radio_robustness.pdf` | `results/crypto_bench.json`, `results/priority_cryptodecomp_urban.json`, `results/priority_cryptodecomp_highway.json`, `results/radio_crypto.json`, `results/radio_expsweep_urban.json`, `results/radio_calibration.json` | cumulative percentage change from each scenario's baseline mJ/read; verification-energy estimate = measured verification time × OBU slowdown × CPU power; radio denominator uses the stored signature bit count; no compute-energy value is charged to the simulator | crypto decomposition: not encoded in source JSON; urban exponent sweep: 10; crypto benchmark and calibration: analytic/benchmark, not seed-based | Stored paired p-values only; no uncertainty reconstructed. |

## Boundaries and gaps

- All non-baseline simulation outputs shown here are aggregate/descriptive unless a stored statistic is explicitly named.
- No confidence interval is reconstructed from aggregate means.
- The crypto-decomposition JSON does not encode its seed count; the generated output leaves it unspecified.
- No formal-verification table is generated because no committed machine-readable Scyther result artifact exists.
- No Module 4 result is generated; Module 4 remains Deferred / Future Work.
- Base-paper Figures 11–15 remain separately generated in `figures/baseline/`.

`manifest.json` records source hashes, formulas, seed metadata and output hashes.
