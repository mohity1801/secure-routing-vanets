# Module 5 — priority traffic, and priority as an attack surface

The base paper contains no notion of message criticality. The words "priority",
"emergency" and "deadline" do not occur in it, and every metric it reports is
energy. That is not a missing feature to be bolted on — it is a structural
conflict with the mechanism the paper exists to optimise.

**CSGD-NET's entire energy saving comes from a cluster head fusing its members'
readings into one packet.** Fusion means the head cannot transmit until every
member's TDMA slot has passed. So a reading's delay is the length of the whole
frame, regardless of its own position in it. An ambulance's message cannot wait
for the frame and cannot be averaged into a fused packet with ten telemetry
readings.

## What was built

- `traffic.py` — two classes (telemetry, emergency), EMS vehicle designation,
  priority assertion with a token bucket.
- `network.py` — `_priority_phase`: reservation arbitration, aggregation
  bypass, per-class delay and PDR accounting, energy attribution.
- `attacks.py` — `falsepriority`, a sixth adversary behaviour.
- `trust.py` — `observe_priority`, assertion-rate evidence.
- `metrics.py` — weighted percentiles, deadline-miss.

## Units: slots, not milliseconds

Delay is reported in **TDMA slots** throughout, and that is deliberate. This
simulator has no channel and no time below the round, so a millisecond figure
would be invented. A TDMA schedule, though, is a real finite resource in the
base paper's own model and the delay it imposes is exactly computable:

    aggregated  = cluster size + 1    member slots, then the head's forward
    bypassed    = 2                   reserved slot, then an immediate forward
    orphan      = 1                   direct to the RSU, nothing to wait for

Nothing here claims an end-to-end latency in seconds. Any such number would
require a MAC and queueing model this simulator does not have.

## Finding 1 — coverage and latency are in direct opposition

6 seeds, 5 % EMS, reservation disabled (`emergency_slots = 0`), so every reading
is aggregated and class-2 traffic gets no special treatment.

| | **urban** | | | **highway** | | |
|---|---|---|---|---|---|---|
| protocol | orphan % | delay | dl-miss | orphan % | delay | dl-miss |
| HEED | 47.6 | 4.27 | **0.278** | 48.1 | 5.24 | **0.372** |
| LEACH | 39.3 | 6.90 | 0.597 | 30.8 | 8.15 | 0.606 |
| CSGD-NET | 21.4 | 7.44 | 0.647 | 10.6 | 10.13 | 0.831 |
| GA | 9.1 | 8.59 | 0.759 | 1.1 | 10.42 | 0.889 |
| PSO | 5.3 | 9.06 | 0.847 | 0.3 | 10.46 | 0.934 |
| LEACH-C | 5.8 | 9.18 | 0.859 | 1.1 | 10.56 | 0.943 |
| **CHIRP** | **3.3** | **9.69** | 0.881 | **0.2** | 10.26 | **0.957** |

> **Numbers refreshed when this experiment was promoted to a committed runner**
> (`--coverage-latency`). The first version of this table was produced by an
> inline script *before* Module 3b measured the crypto overhead, so it ran with
> `mac_bits = 0`. The aggregate MAC is now charged on every fused packet, which
> drains heads marginally faster, shifts when nodes die, and therefore moves
> orphan rates and cluster sizes by a point or two — CSGD-NET's urban orphan
> rate 19.3 → 21.4 is the largest single move. **The relationship is unchanged**
> and no conclusion depends on the difference.

Deadline-miss tracks orphan rate almost perfectly inversely, in both scenarios
and across seven protocols. Orphans skip fusion entirely, so they are the
*lowest-delay* path in the network — and a protocol that is good at coverage has
few of them. HEED, which strands nearly half the network, has the best emergency
latency in the comparison precisely because it is the worst at clustering.

**Module 1's headline win is a latency loss.** CHIRP strands the fewest nodes of
any protocol here — 3.3 % urban, 0.2 % highway — and it has the worst or
near-worst deadline-miss in both. This is the fourth negative result in the project and it
is worth stating plainly: the entire clustering literature optimises coverage
without measuring what coverage costs deadline-bound traffic, because none of it
models a traffic class that has a deadline.

The effect is sharper on the highway (0.957 vs urban's 0.881) because highway
CHIRP orphans almost nothing at all — there is no accidental fast path left.

## Finding 2 — the energy price of priority

Emergency readings are forwarded verbatim instead of being fused: the head
refunds the aggregation and pays an individual authenticated transmit for each.
12 seeds, 5 % EMS, no attackers.

Values below include the **measured** crypto overhead from Module 3b:
`sig_bits = 576` (64 B ECDSA P-256 signature + 8 B certificate digest) and
`mac_bits = 128` (truncated aggregate MAC). Both were 0 in the first version of
this document; see `docs/module3b.md`.

**Urban** — 600 m grid, 9 RSUs, tx_range 150 m.

| protocol | bypass | mJ/reading | EMS delay | EMS p95 | deadline-miss |
|---|---|---|---|---|---|
| CSGD-NET | off | 1.4974 | 7.67 | 16.2 | 0.668 |
| CSGD-NET | **on** | 1.5148 (**+1.2 %**) | **1.75** | **2.0** | **0.000** |
| CHIRP | off | 1.3164 | 9.99 | 15.8 | 0.913 |
| CHIRP | **on** | 1.3408 (**+1.8 %**) | **1.95** | **2.0** | **0.000** |

**Highway** — 1 km 6-lane, 5 RSUs, tx_range 100 m.

| protocol | bypass | mJ/reading | EMS delay | EMS p95 | deadline-miss |
|---|---|---|---|---|---|
| CSGD-NET | off | 0.7655 | 10.58 | 20.7 | 0.856 |
| CSGD-NET | **on** | 0.7645 (−0.1 %, noise) | **1.91** | **2.0** | **0.000** |
| CHIRP | off | 0.7285 | 10.57 | 15.7 | 0.988 |
| CHIRP | **on** | 0.7323 (**+0.5 %**) | **2.00** | **2.0** | **0.000** |

Deadline misses go to zero in both scenarios for under 2 % of network energy,
crypto included.

**Read these ratios with care — the aggregate MAC is charged in both arms.**
Turning the bypass off does not turn the crypto layer off, so these percentages
mix two effects. Module 3b decomposes them properly with paired tests over 16
seeds, and the honest summary is: the whole crypto layer plus the bypass costs
**+1.63 % urban and +0.77 % highway**, of which the per-message signature is
statistically undetectable (p = 0.94 highway, 0.058 urban). The CSGD-NET
highway figure of −0.1 % is noise, not a saving.

**The cost of priority is set by RSU density, not by traffic mix.** The highway
places 5 RSUs along 1 km, so heads are almost always inside the free-space knee
at d0 = 87.7 m and an individual forward costs d². The 600 m urban grid pushes
many heads past the knee into the d⁴ regime, where each verbatim forward is
disproportionately expensive. A deployment that wants cheap priority handling
should buy RSUs, not bandwidth.

> **Re-scoped by the radio robustness check** (`docs/radio.md`): this
> explanation is specific to the Heinzelman model, and the model is what makes
> it true. Under log-distance path loss with no knee the urban premium
> vanishes — the bypass costs under 1 % in both scenarios (CHIRP +0.90 %
> urban, +0.96 % highway) and deadline-miss is still 0.000 everywhere. The
> claim that survives every model is the cheaper one: priority costs a small
> single-digit percentage at any RSU density tested.

**Correction.** The first version of this document reported CHIRP paying *less
than half* what CSGD-NET pays in urban, and attributed it to Module 1's
energy-scored RSU term. With crypto charged the urban ordering reverses —
CHIRP +1.8 % against CSGD-NET +1.2 % — because the aggregate MAC is a fixed
cost measured against CHIRP's lower baseline (1.3164 vs 1.4974 mJ/reading), and
because CHIRP orphans almost nothing so more traffic goes through clusters and
needs bypassing. The earlier claim was an artefact of charging no crypto and is
withdrawn.

CHIRP's undefended deadline-miss on the highway is **0.986**, essentially total,
against urban's 0.916. Highway CHIRP orphans only 0.2 % of nodes, so almost
nothing escapes fusion — Finding 1 is stronger here than in the city.

The reservation is never saturated by genuine ambulances alone, in either
scenario. It takes an attacker.

## Finding 3 — priority is a denial-of-service surface

A `falsepriority` attacker drops nothing. It attacks a *resource*: emergency
slots are reserved and finite, a head with no way to authenticate a claim must
share them proportionally, and the attacker asserts on all 22 of its readings
while a genuine ambulance asserts on 4.

12 seeds, CHIRP, 5 % EMS, attackers assert at rate 1.00.

**Urban**

| att % | defence | EMS deadline-miss | EMS delay | priority mJ | false % | net drain % | detect | FPR |
|---|---|---|---|---|---|---|---|---|
| 0 | none | 0.000 | 1.95 | 560 | 0 | 0.00 | — | — |
| 0 | trust | 0.002 | 1.96 | 562 | 0 | 0.00 | — | — |
| 0 | auth | 0.000 | 1.94 | 563 | 0 | 0.00 | — | — |
| 5 | none | 0.110 | 3.07 | 2848 | 83 | 5.05 | — | — |
| 5 | trust | 0.042 | 2.26 | 972 | 37 | 0.89 | 0.983 | 0.023 |
| 5 | **auth** | **0.000** | **1.96** | 573 | 0 | **0.00** | 0.950 | 0.016 |
| 10 | none | 0.205 | 3.97 | 4061 | 90 | 7.78 | — | — |
| 10 | trust | 0.145 | 3.15 | 1090 | 52 | 1.34 | 0.967 | 0.022 |
| 10 | **auth** | **0.000** | **1.94** | 572 | 0 | **0.00** | 0.958 | 0.022 |
| 20 | none | 0.437 | 6.19 | 5521 | 95 | 11.26 | — | — |
| 20 | trust | 0.234 | 4.18 | 1650 | 72 | 2.75 | 0.942 | 0.015 |
| 20 | **auth** | **0.000** | **1.94** | 549 | 0 | **0.00** | 0.937 | 0.015 |
| 30 | none | 0.546 | 7.13 | 6028 | 97 | 12.42 | — | — |
| 30 | trust | 0.268 | 4.28 | 1743 | 75 | 3.02 | 0.953 | 0.014 |
| 30 | **auth** | **0.000** | **1.94** | 571 | 0 | **0.00** | 0.953 | 0.020 |
| 40 | none | 0.642 | 7.97 | 6342 | 97 | 13.25 | — | — |
| 40 | trust | 0.392 | 5.53 | 1921 | 84 | 3.71 | 0.948 | 0.026 |
| 40 | **auth** | **0.000** | **1.92** | 533 | 0 | **0.00** | 0.950 | 0.026 |

**Highway**

| att % | defence | EMS deadline-miss | EMS delay | priority mJ | false % | net drain % | detect | FPR |
|---|---|---|---|---|---|---|---|---|
| 0 | none | 0.000 | 2.00 | 328 | 0 | 0.00 | — | — |
| 0 | trust | 0.000 | 2.00 | 324 | 0 | 0.00 | — | — |
| 0 | auth | 0.000 | 2.00 | 324 | 0 | 0.00 | — | — |
| 5 | none | 0.118 | 3.14 | 1575 | 82 | 2.67 | — | — |
| 5 | trust | 0.026 | 2.23 | 438 | 26 | 0.26 | **1.000** | 0.008 |
| 5 | **auth** | **0.000** | **2.00** | 315 | 0 | **0.00** | 1.000 | 0.010 |
| 10 | none | 0.245 | 4.32 | 2316 | 90 | 4.30 | — | — |
| 10 | trust | 0.131 | 3.11 | 436 | 34 | 0.36 | 0.992 | 0.009 |
| 10 | **auth** | **0.000** | **2.00** | 309 | 0 | **0.00** | 1.000 | 0.011 |
| 20 | none | 0.472 | 6.43 | 3073 | 95 | 6.01 | — | — |
| 20 | trust | 0.260 | 4.27 | 497 | 55 | 0.65 | **1.000** | 0.014 |
| 20 | **auth** | **0.000** | **2.00** | 296 | 0 | **0.00** | 1.000 | 0.007 |
| 30 | none | 0.595 | 7.50 | 3402 | 96 | 6.74 | — | — |
| 30 | trust | 0.281 | 4.45 | 785 | 72 | 1.38 | 0.975 | 0.012 |
| 30 | **auth** | **0.000** | **2.00** | 283 | 0 | **0.00** | 0.986 | 0.010 |
| 40 | none | 0.705 | 8.43 | 3432 | 97 | 6.89 | — | — |
| 40 | trust | 0.446 | 5.83 | 895 | 83 | 1.87 | 0.962 | 0.007 |
| 40 | **auth** | **0.000** | **1.99** | 274 | 0 | **0.00** | 0.960 | 0.011 |

EMS deadline-miss at 20 % attackers: **auth 0.000 vs undefended 0.437 (urban)
and 0.472 (highway), p = 5.1e-06 in both**.

**Crypto makes the attack more expensive for its victims, not less.** Charging
the measured `sig_bits` raised the net drain at 20 % attackers from 10.41 % to
11.26 % urban and 5.52 % to 6.01 % highway, because every falsely-urgent message
now carries a signature the honest head must forward verbatim. The attacker pays
nothing extra for that; the head does. Authentication removes the whole cost by
refusing the claim before the forward ever happens.

Four things to read off these tables.

**At 5 % attackers, 83 % of the reservation's energy already serves liars** — in
both scenarios, identically. Five attackers assert 110 messages a round against
five ambulances' 20. The asymmetry is not in the number of attackers, it is in
how hard each one pushes, and it is a property of the traffic model rather than
of the road.

**Up to 12 % of the entire network's energy budget** goes to forwarding
falsely-urgent messages verbatim. This is the Module 2 free ride inverted: there
the attacker *banked* energy by skipping forwards it owed, here it spends
nothing extra and *imposes* the cost on honest heads. What it buys is not
battery — it is an ambulance's deadline.

**The drain is half as bad on the highway** (5.5 % vs 10.4 % at 20 % attackers)
for the same reason priority is cheaper there: heads sit inside the free-space
knee, so each falsely-urgent forward costs d² rather than d⁴. RSU density is a
mitigation for this attack as well as a cost reduction for the feature.

**Detection is perfect on the highway and merely good in the city** (1.000 vs
0.954 at 20 %, at a third the false-positive rate). Highway networks live about
twice as long — first-node-death 23 rounds against urban's 9.6 — so the trust
engine gets roughly twice the rounds to accumulate assertion-rate evidence
before the evaluation window closes. Detection quality here is bounded by
network lifetime, not by the detector.

## Finding 4 — detection is not mitigation

The first version of the trust defence detected false-priority attackers at
0.93–0.96 and **changed the outcome not at all** (deadline-miss 0.452 undefended
vs 0.463 with trust at 20 % attackers).

The reason is that the trust gate's only lever is *cluster-head eligibility*,
and asserting priority does not require being a head. A detector wired to an
enforcement path that the attack does not traverse is decorative.

The fix is `priority_trust_gate`: heads refuse reserved slots to nodes the
network distrusts. That is what the table above measures, and it halves the
damage. The general lesson is worth keeping in the report — a detection rate is
not a security result unless the enforcement path is named.

## Finding 5 — trust bounds the attack, only the certificate stops it

Sweeping how greedily the attacker asserts. 20 % attackers, 12 seeds. A genuine
EMS vehicle asserts at 0.18; the behavioural detector flags above 0.50.

| | | **urban** | | | **highway** | | |
|---|---|---|---|---|---|---|---|
| greed | defence | dl-miss | drain % | detect | dl-miss | drain % | detect |
| 0.18 | none | 0.013 | 4.48 | — | 0.011 | 2.41 | — |
| 0.18 | trust | 0.011 | 4.26 | **0.025** | 0.021 | 2.44 | **0.004** |
| 0.18 | auth | **0.000** | **0.00** | 0.013 | **0.000** | **0.00** | 0.021 |
| 0.30 | none | 0.067 | 6.76 | — | 0.072 | 3.79 | — |
| 0.30 | trust | 0.074 | 6.69 | **0.021** | 0.077 | 3.73 | **0.000** |
| 0.50 | none | 0.206 | 9.08 | — | 0.227 | 4.98 | — |
| 0.50 | trust | 0.207 | 9.09 | **0.025** | 0.231 | 4.97 | **0.008** |
| 0.50 | auth | **0.000** | **0.00** | 0.013 | **0.000** | **0.00** | 0.021 |
| 0.75 | none | 0.348 | 10.45 | — | 0.372 | 5.58 | — |
| 0.75 | trust | 0.207 | 2.54 | 0.892 | 0.248 | 0.85 | 0.950 |
| 1.00 | none | 0.437 | 11.26 | — | 0.472 | 6.01 | — |
| 1.00 | trust | 0.234 | 2.75 | 0.942 | 0.260 | 0.65 | 1.000 |
| 1.00 | auth | **0.000** | **0.00** | 0.937 | **0.000** | **0.00** | 1.000 |

**At greed 0.50 the attacker is behaviourally invisible and still does most of
the damage.** Detection is 0.025 urban and 0.008 highway — at or below the
false-positive rate, meaning the detector is contributing nothing — while the
attacker takes 47 % of the maximum deadline damage in the city and 48 % on the
highway, at 81 % and 83 % of the maximum energy drain respectively. Trust makes
the outcome marginally *worse* at this point, not better, in both scenarios.

The detector is a step function and the attacker simply sits under the step.
Detection goes from 0.008 to 0.950 between greed 0.50 and 0.75 on the highway.
Lowering the threshold is not a fix: at greed 0.18 the attacker's per-node
behaviour is *identical* to a real ambulance's, so no rate-based test can
separate them at any threshold. Yet 20 attackers asserting 4 messages each still
outnumber 5 ambulances asserting 4 each by four to one, and 2–4 % of network
energy still drains.

**The distinguishing fact is not behavioural at all — it is whether the vehicle
holds the role.**

Read the `auth` rows against their own detect column: authorisation delivers
0.000 deadline-miss at greed 0.50 *while its behavioural detector is blind*
(0.008). It is not detecting the attack and does not need to. That is the
difference between a statistical defence and a cryptographic one, and it is the
argument for the Module 3 certificate in a single row of a table.

**This is what makes the Module 3 certificate load-bearing rather than
box-ticking.** The property to verify formally is not a generic handshake but:
*an honest head grants a reserved slot only to a vehicle holding a TA-issued
EMS role attribute, and not to a replay of one.* That is injective agreement on
an authorisation claim, and it is the reason the crypto is in the design.

## Costs and limitations, stated

**Trust gating has a false-positive cost, but it is small and noisy.** At 0 %
attackers the urban trust defence shows a non-zero EMS deadline-miss where
authorisation shows exactly 0.000 — ambulances wrongly distrusted lose their
reserved slot. The magnitude moved between runs (0.015 before the crypto
re-run, 0.002 after) which is seed noise at 12 seeds, not an effect of crypto,
so the honest claim is directional rather than quantitative: **a statistical
gate on a safety path occasionally charges honest traffic; a cryptographic one
structurally cannot.** The highway does not show it at all, its longer lifetime
letting the trust engine resolve honest nodes before the evaluation window
closes. Pinning the magnitude down would need many more seeds than the
conclusion warrants.

**Emergency traffic is only 0.84 % of all readings** at the defaults (5 % EMS ×
4 of 22 messages). The energy costs above are therefore small in absolute terms
and would scale with heavier emergency load.

**Both scenarios are synthetic.** Highway and urban mobility come from
`mobility.py`, not from replayed SUMO traces. Every result here holds across two
quite different road geometries, RSU densities and speed regimes, which is
better than one — but it is not the same as real traces, and the RSU-density
explanation for the urban/highway cost gap in particular deserves a check
against a real deployment layout.

**No channel, no contention, no milliseconds.** Slot exhaustion is a real finite
resource and is modelled honestly; channel-level flooding is not modelled at all
and no result here should be read as one.

**Class 1 (per-vehicle safety events) is not modelled.** Two classes are enough
to show the mechanism; a third would add parameters without adding an argument.

**`sig_bits` and `mac_bits` are now measured** (576 and 128 bits, Module 3b)
and every table above includes them. The figures remain a lower bound, but for
a different reason than originally stated: the simulator charges radio energy
only, and Module 3b measures that ECDSA *verification* costs roughly 15× the
energy of transmitting the signature it checks, at a plausible OBU slowdown and
CPU power. Computation energy is measured and reported there; it is not charged
here, because doing so would move every Module 1 and Module 2 baseline.

## Reproduce

```bash
for s in urban highway; do
  python3 src/run_priority.py --scenario $s --seeds 6  --rounds 40 --coverage-latency  # finding 1
  python3 src/run_priority.py --scenario $s --seeds 12 --bypass-cost                   # finding 2
  python3 src/run_priority.py --scenario $s --seeds 12                                 # findings 3, 4
  python3 src/run_priority.py --scenario $s --seeds 12 --sweep-greed                    # finding 5
done
```

Every table in this document is now produced by a committed runner. Outputs land
in `results/priority_{coverage,bypass,defence,greed}_{scenario}.json`.

Every result above holds `ems_frac = 0` as a regression invariant: with no EMS
vehicles and zero crypto overhead, all Module 1 and Module 2 results are
bit-identical to their pre-Module-5 values, verified across 55 configurations
covering three scenarios, seven protocols and the trust engine under attack:

```bash
python3 src/regression_gate.py /tmp/now.json
python3 src/regression_gate.py --diff results/regression_reference.json /tmp/now.json
```
