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

6 seeds, 5 % EMS, before any bypass exists. Every reading is aggregated.

| | **urban** | | | **highway** | | |
|---|---|---|---|---|---|---|
| protocol | orphan % | delay | dl-miss | orphan % | delay | dl-miss |
| HEED | 46.8 | 4.22 | **0.273** | 48.0 | 5.24 | **0.387** |
| LEACH | 38.5 | 6.91 | 0.602 | 31.2 | 8.15 | 0.609 |
| CSGD-NET | 19.3 | 7.70 | 0.687 | 10.1 | 10.14 | 0.820 |
| GA | 9.2 | 8.64 | 0.782 | 1.1 | 10.44 | 0.898 |
| PSO | 6.0 | 9.08 | 0.813 | 0.2 | 10.43 | 0.924 |
| LEACH-C | 5.9 | 9.16 | 0.888 | 1.1 | 10.59 | 0.953 |
| **CHIRP** | **3.1** | **9.68** | 0.874 | **0.1** | 10.23 | **0.958** |

Deadline-miss tracks orphan rate almost perfectly inversely, in both scenarios
and across seven protocols. Orphans skip fusion entirely, so they are the
*lowest-delay* path in the network — and a protocol that is good at coverage has
few of them. HEED, which strands nearly half the network, has the best emergency
latency in the comparison precisely because it is the worst at clustering.

**Module 1's headline win is a latency loss.** CHIRP cut the urban orphan rate
by 82.7 % and the highway rate to 0.1 %, and it has the worst or near-worst
deadline-miss in both. This is the fourth negative result in the project and it
is worth stating plainly: the entire clustering literature optimises coverage
without measuring what coverage costs deadline-bound traffic, because none of it
models a traffic class that has a deadline.

The effect is sharper on the highway (0.958 vs urban's 0.874) because highway
CHIRP orphans almost nothing at all — there is no accidental fast path left.

## Finding 2 — the energy price of priority

Emergency readings are forwarded verbatim instead of being fused: the head
refunds the aggregation and pays an individual authenticated transmit for each.
12 seeds, 5 % EMS, no attackers.

**Urban** — 600 m grid, 9 RSUs, tx_range 150 m.

| protocol | bypass | mJ/reading | EMS delay | EMS p95 | deadline-miss |
|---|---|---|---|---|---|
| CSGD-NET | off | 1.4976 | 7.99 | 15.8 | 0.704 |
| CSGD-NET | **on** | 1.5297 (**+2.1 %**) | **1.74** | **2.0** | **0.000** |
| CHIRP | off | 1.3159 | 10.04 | 16.0 | 0.916 |
| CHIRP | **on** | 1.3282 (**+0.9 %**) | **1.95** | **2.0** | **0.000** |

**Highway** — 1 km 6-lane, 5 RSUs, tx_range 100 m.

| protocol | bypass | mJ/reading | EMS delay | EMS p95 | deadline-miss |
|---|---|---|---|---|---|
| CSGD-NET | off | 0.7643 | 10.65 | 20.4 | 0.859 |
| CSGD-NET | **on** | 0.7675 (**+0.4 %**) | **1.92** | **2.0** | **0.000** |
| CHIRP | off | 0.7266 | 10.58 | 15.6 | 0.986 |
| CHIRP | **on** | 0.7308 (**+0.6 %**) | **2.00** | **2.0** | **0.000** |

Deadline misses go to zero in both scenarios, for under 1 % of network energy on
the highway and 1–2 % in the city.

**The cost of priority is set by RSU density, not by traffic mix.** The highway
places 5 RSUs along 1 km, so heads are almost always inside the free-space knee
at d0 = 87.7 m and an individual forward costs d². The 600 m urban grid pushes
many heads past the knee into the d⁴ regime, where each verbatim forward is
disproportionately expensive — roughly three times the relative cost. A
deployment that wants cheap priority handling should buy RSUs, not bandwidth.

Within urban, CHIRP pays *less than half* what CSGD-NET pays. Its RSU term is
scored in transmit energy rather than distance, so its heads sit where forwards
are cheap. Module 1's objective incidentally reduces the cost of priority — not
designed, not anticipated. On the highway, where nearly every head is already
inside the knee, there is nothing left for that term to buy and the two
protocols pay the same.

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
| 0 | none | 0.000 | 1.95 | 545 | 0 | 0.00 | — | — |
| 0 | trust | 0.015 | 2.04 | 513 | 0 | 0.00 | — | — |
| 0 | auth | 0.000 | 1.95 | 521 | 0 | 0.00 | — | — |
| 5 | none | 0.115 | 3.16 | 2668 | 83 | 4.71 | — | — |
| 5 | trust | 0.041 | 2.29 | 881 | 37 | 0.79 | 0.983 | 0.017 |
| 5 | **auth** | **0.000** | **1.96** | 525 | 0 | **0.00** | 0.933 | 0.018 |
| 20 | none | 0.441 | 6.09 | 5120 | 95 | 10.41 | — | — |
| 20 | trust | 0.239 | 4.08 | 1476 | 72 | 2.42 | 0.954 | 0.019 |
| 20 | **auth** | **0.000** | **1.95** | 524 | 0 | **0.00** | 0.950 | 0.012 |
| 40 | none | 0.657 | 8.03 | 5864 | 98 | 12.22 | — | — |
| 40 | trust | 0.390 | 5.45 | 1709 | 84 | 3.25 | 0.952 | 0.019 |
| 40 | **auth** | **0.000** | **1.92** | 501 | 0 | **0.00** | 0.954 | 0.018 |

**Highway**

| att % | defence | EMS deadline-miss | EMS delay | priority mJ | false % | net drain % | detect | FPR |
|---|---|---|---|---|---|---|---|---|
| 0 | none | 0.000 | 2.00 | 301 | 0 | 0.00 | — | — |
| 0 | trust | 0.000 | 2.00 | 301 | 0 | 0.00 | — | — |
| 0 | auth | 0.000 | 2.00 | 301 | 0 | 0.00 | — | — |
| 5 | none | 0.116 | 3.16 | 1477 | 83 | 2.53 | — | — |
| 5 | trust | 0.036 | 2.33 | 402 | 27 | 0.25 | **1.000** | 0.011 |
| 5 | **auth** | **0.000** | **2.00** | 294 | 0 | **0.00** | 1.000 | 0.015 |
| 20 | none | 0.467 | 6.38 | 2819 | 95 | 5.52 | — | — |
| 20 | trust | 0.256 | 4.19 | 484 | 55 | 0.63 | **1.000** | 0.007 |
| 20 | **auth** | **0.000** | **2.00** | 278 | 0 | **0.00** | 0.996 | 0.009 |
| 40 | none | 0.705 | 8.31 | 3173 | 97 | 6.38 | — | — |
| 40 | trust | 0.444 | 5.86 | 817 | 82 | 1.69 | 0.967 | 0.011 |
| 40 | **auth** | **0.000** | **1.99** | 250 | 0 | **0.00** | 0.967 | 0.014 |

EMS deadline-miss at 20 % attackers: **auth 0.000 vs undefended 0.441 (urban)
and 0.467 (highway), p = 5.1e-06 in both**.

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
| 0.18 | none | 0.014 | 4.20 | — | 0.012 | 2.22 | — |
| 0.18 | trust | 0.022 | 3.97 | **0.038** | 0.011 | 2.23 | **0.004** |
| 0.18 | auth | **0.000** | **0.00** | 0.017 | **0.000** | **0.00** | 0.008 |
| 0.30 | none | 0.066 | 6.34 | — | 0.072 | 3.46 | — |
| 0.30 | trust | 0.084 | 6.08 | **0.037** | 0.069 | 3.45 | **0.004** |
| 0.50 | none | 0.203 | 8.42 | — | 0.223 | 4.66 | — |
| 0.50 | trust | 0.212 | 8.33 | **0.025** | 0.229 | 4.67 | **0.008** |
| 0.50 | auth | **0.000** | **0.00** | 0.017 | **0.000** | **0.00** | 0.008 |
| 0.75 | none | 0.344 | 9.80 | — | 0.369 | 5.15 | — |
| 0.75 | trust | 0.215 | 2.26 | 0.896 | 0.250 | 0.74 | 0.962 |
| 1.00 | none | 0.441 | 10.41 | — | 0.467 | 5.52 | — |
| 1.00 | trust | 0.239 | 2.42 | 0.954 | 0.256 | 0.63 | 1.000 |
| 1.00 | auth | **0.000** | **0.00** | 0.950 | **0.000** | **0.00** | 0.996 |

**At greed 0.50 the attacker is behaviourally invisible and still does most of
the damage.** Detection is 0.025 urban and 0.008 highway — at or below the
false-positive rate, meaning the detector is contributing nothing — while the
attacker takes 46 % of the maximum deadline damage in the city and 48 % on the
highway, at 81 % and 84 % of the maximum energy drain respectively. Trust makes
the outcome marginally *worse* at this point, not better, in both scenarios.

The detector is a step function and the attacker simply sits under the step.
Detection goes from 0.008 to 0.962 between greed 0.50 and 0.75 on the highway.
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

**Trust gating has a false-positive cost.** At 0 % attackers the urban trust
defence still shows deadline-miss 0.015 — ambulances wrongly distrusted lose
their reserved slot. Authorisation shows 0.000. A statistical gate on a safety
path charges honest traffic for the privilege; a cryptographic one does not.
The highway does not show this cost (0.000 at 0 % attackers), because its longer
lifetime lets the trust engine resolve honest nodes before the window closes —
so the penalty is real but scenario-dependent, and worst exactly where networks
are short-lived.

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

**`sig_bits` and `mac_bits` are 0.** Per-message authentication overhead is
parameterised and awaits Module 3b's measurements. Filling them in will *raise*
the cost of the bypass, since bypassed messages cannot be covered by the
aggregate MAC — so Finding 2's +0.9 %/+2.1 % is a lower bound.

## Reproduce

```bash
for s in urban highway; do
  python3 src/run_priority.py --scenario $s --seeds 12 --bypass-cost
  python3 src/run_priority.py --scenario $s --seeds 12
  python3 src/run_priority.py --scenario $s --seeds 12 --sweep-greed
done
```

Every result above holds `ems_frac = 0` as a regression invariant: with no EMS
vehicles and zero crypto overhead, all Module 1 and Module 2 results are
bit-identical to their pre-Module-5 values, verified across 55 configurations
covering three scenarios, seven protocols and the trust engine under attack:

```bash
python3 src/regression_gate.py /tmp/now.json
python3 src/regression_gate.py --diff results/regression_reference.json /tmp/now.json
```
