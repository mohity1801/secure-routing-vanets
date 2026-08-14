# Module 2 — trust engine

Adds the defence the base paper has no equivalent of. CSGD-NET's Eq. 9 scores a
candidate head on residual energy and distance to the RSU; both are
self-reported and neither is a behavioural observation, so an attacker claiming
a full battery near an RSU wins the head role and drops whatever it likes.

## What was built

- `attacks.py` — Layer-A adversary: blackhole, greyhole, on-off, bad-mouthing,
  ballot-stuffing. Internal attackers holding valid identities.
- `trust.py` — three-layer Beta reputation.
- `network.py` — heads now forward only a fraction of what they received, and
  PDR is measured as readings delivered over readings generated.
- `chirp.py` — trust enters both as a fitness term and as a hard eligibility
  gate, so a distrusted node cannot be elected head at all.

## The three layers, and what each is for

1. **Direct trust.** Members watchdog their head; evidence accumulates as
   Beta(α, β) with Laplace smoothing so an unobserved node sits at 0.5. Catches
   blackhole and greyhole.
2. **Decay with asymmetric penalty.** A failure counts `trust_penalty = 3`
   successes and evidence ages by 0.9. Without the asymmetry an on-off attacker
   farms trust in quiet phases and spends it in active ones.
3. **Credibility-weighted recommendations.** Reports are fused at the RSU
   weighted by how far each reporter has historically deviated from consensus.
   Bad-mouthers and ballot-stuffers accumulate deviation and lose weight.

## Results — urban, 12 seeds, mixed attack

Evaluated over the network's useful lifetime (up to half-node-death).

| attacker % | protocol | PDR | att CH % | late % | detect | FPR | TTD |
|---|---|---|---|---|---|---|---|
| 10 | CSGD-NET | 0.968 | 10.0 | 10.3 | — | — | — |
| 10 | **CHIRP + trust** | **0.979** | **8.1** | **6.4** | 0.831 | 0.018 | 6.4 |
| 20 | CSGD-NET | 0.934 | 21.9 | 20.3 | — | — | — |
| 20 | **CHIRP + trust** | **0.957** | **16.9** | **14.8** | 0.815 | 0.033 | 5.8 |
| 30 | CSGD-NET | 0.887 | 32.9 | 35.0 | — | — | — |
| 30 | **CHIRP + trust** | **0.923** | **23.1** | **19.4** | 0.878 | 0.044 | 5.5 |
| 40 | CSGD-NET | 0.859 | 40.8 | 39.7 | — | — | — |
| 40 | **CHIRP + trust** | **0.904** | **33.3** | **29.5** | 0.819 | 0.035 | 5.8 |

PDR at 20 % attackers: **0.957 vs 0.934, +2.4 %, p = 0.0018**. At 40 %,
+5.2 %. Detection 0.82–0.88 at a false-positive rate of 0.018–0.044, with
attackers first flagged after 5.5–6.4 rounds.

The gap widens with attacker fraction, which is the right shape for a defence:
at 0 % attackers all four protocols deliver PDR 1.000, so the trust machinery
costs nothing when there is nothing to defend against.

Note `CHIRP (no trust)` tracks CSGD-NET closely (0.843 vs 0.859 at 40 %). The
Module 1 objective is not itself a defence, and should not be presented as one —
the entire security gain comes from the trust layer.

## Credibility ablation

The full mix dilutes the effect, since only 2 of its 5 behaviours falsify
reports. The collusion mix isolates the mechanism: bad-mouthers and
ballot-stuffers coordinating, with greyholes underneath so there is real
misbehaviour to find.

Collusion mix (bad-mouth + ballot + greyhole), 10 seeds:

| attacker % | credibility | detect | FPR |
|---|---|---|---|
| 20 | on | 0.882 | **0.036** |
| 20 | OFF | 0.913 | 0.053 |
| 30 | on | 0.767 | **0.070** |
| 30 | OFF | 0.793 | 0.091 |
| 40 | on | **0.796** | **0.092** |
| 40 | OFF | 0.710 | 0.178 |

Credibility weighting cuts the false-positive rate by 12–49 %, and by 49 % at
40 % attackers — from 17.8 % of honest nodes wrongly distrusted down to 9.2 %.
That is what the layer is for: bad-mouthers report honest heads as droppers, and
without credibility weighting those lies drag honest nodes below the gate.

Detection rate is *not* uniformly improved — at 20 % and 30 % it is slightly
better without credibility. The benefit is concentrated in false positives, and
the report should say so rather than claim a uniform win.

## Finding — the defence gives attackers an energy free ride

Mean residual energy of attackers relative to honest nodes at end of run:

| attacker % | CSGD-NET | CHIRP (no trust) | CHIRP + trust |
|---|---|---|---|
| 10 | 1.01 | 1.23 | **1.98** |
| 20 | 1.11 | 1.47 | **2.11** |
| 30 | 1.27 | 1.40 | **2.41** |
| 40 | 1.21 | 1.47 | **2.43** |

Two effects compound. Dropping already skips the forward transmit, so attacking
is cheaper than behaving even undefended (1.2–1.5x). The trust gate then
*excludes* misbehaving nodes from the head role — the most expensive job in the
network at 88 mJ/round against 11.6 for an ordinary member — so a detected
attacker is spared the very duty that drains honest nodes, and ends with 2.0–2.4x
their residual energy.

This is a real limitation of demotion-based defence and it is worth stating
plainly. Two candidate remedies are retained for Module 4, which is deferred as
future work:

1. **Revocation rather than demotion.** Remove the node from the network
   instead of merely making it ineligible to lead.
2. **Duty rebalancing.** Require distrusted nodes to carry forwarding load they
   cannot profit from skipping, so exclusion is not a reward.

Neither remedy is implemented or evaluated in the current BTP, and the results
above do not claim their effect. They remain proposed mitigations for a future
Module 4 implementation or a later supervisor-directed project phase.

It also means a security defence cannot be validated on energy metrics alone —
an attacker wins on energy by construction.

The free ride is not an artifact of the base paper's radio model — the
opposite: under log-distance path loss it grows to **2.21–3.02×**
(`docs/radio.md`), because what demotion spares the attacker is the head
role, whose cost is dominated by distance-independent receive + aggregation,
while everything honest nodes pay in radio gets cheaper.

## Reproduce

```bash
python3 src/run_module2.py --scenario urban --seeds 12
python3 src/run_module2.py --scenario urban --seeds 10 --ablate
```
