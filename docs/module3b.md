# Module 3b — measured cost of the crypto layer

```bash
python3 src/crypto_bench.py --seconds 3
```

Closes the note Module 5 left open: `sig_bits` and `mac_bits` were 0, so its
cost of priority was a lower bound. They are now measured — 576 and 128 bits —
and the Module 5 tables are re-run with them.

The result is not the one the note anticipated. **The crypto layer's
transmission cost is negligible. Its computation cost is not, and the base
paper's energy model cannot see it by construction.**

Uses only the `openssl` CLI and the Python standard library, so it adds no
dependency to the project.

## Sizes — exact, from real keys and signatures

| item | bytes |
|---|---|
| ECDSA P-256 signature, raw `r‖s` (the IEEE 1609.2 form) | 64 |
| ECDSA P-256 signature, DER | 71 (+7 framing) |
| public key, compressed point | 33 |
| **pseudonym certificate, explicit form** | **122** |
| — pseudonym id 8, pubkey 33, role 1, validity 8, issuer 8, TA sig 64 | |
| aggregate MAC, truncated to 128 bits | 16 |

A class-2 message carries a signature plus a way to find the signer's
certificate. IEEE 1609.2 allows either the full certificate or an 8-byte
HashedId8 digest, and a deployment sends the full certificate periodically and
the digest the rest of the time.

```
sig_bits = 576      # 64 B signature + 8 B certificate digest
mac_bits = 128      # 16 B truncated aggregate MAC
```

Pessimistic variant, full certificate on every class-2 message: `sig_bits =
1488`. Not the default, because it is not what a 1609.2 stack does.

## Timings — this machine, not an OBU

OpenSSL 3.6.1. Note this binary is x86-64 running under Rosetta on an arm64
host, so it understates a native build.

| operation | ops/s | µs |
|---|---|---|
| ECDSA P-256 sign | 29,901 | 33.4 |
| ECDSA P-256 verify | 10,269 | **97.4** |
| HMAC-SHA256 over an 800 B packet | 604,964 | 1.65 |

**Verification is 2.9× the cost of signing, and verification is what CHIRP does
most**: a head verifies every class-2 assertion it admits, and the RSU verifies
every verbatim message it receives. A design that optimised signing would be
optimising the wrong direction.

## The transmission cost is negligible

Decomposed, 16 seeds, CHIRP, 5 % EMS, mJ per delivered reading. Each row adds
one thing to the row above; p from a paired Wilcoxon test across seeds — paired
because each seed gives the same mobility trace in both arms.

```bash
python3 src/run_priority.py --scenario urban   --seeds 16 --crypto-decomp
python3 src/run_priority.py --scenario highway --seeds 16 --crypto-decomp
```

**Urban**

| configuration | mJ/reading | delta | cumulative | p |
|---|---|---|---|---|
| no crypto, no bypass | 1.3168 | — | — | — |
| + aggregate MAC | 1.3146 | −0.17 % | −0.17 % | 0.63 |
| + bypass, no signature | 1.3288 | +1.08 % | +0.91 % | 0.083 |
| + per-message signature | 1.3383 | +0.71 % | **+1.63 %** | 0.058 |

**Highway**

| configuration | mJ/reading | delta | cumulative | p |
|---|---|---|---|---|
| no crypto, no bypass | 0.7269 | — | — | — |
| + aggregate MAC | 0.7288 | +0.26 % | +0.26 % | **0.004** |
| + bypass, no signature | 0.7326 | +0.52 % | +0.77 % | **0.002** |
| + per-message signature | 0.7325 | −0.00 % | **+0.77 %** | 0.94 |

Three things to read off these.

**Everything together costs under 1.7 % of network energy.** The whole crypto
layer plus the priority bypass is a rounding error against the radio budget.

**The per-message signature is statistically undetectable on the highway**
(p = 0.94) and only marginal in urban (p = 0.058). 576 extra bits ride on a
transmission already carrying a 6400-bit payload plus a fixed electronics term,
and class-2 traffic is only 0.84 % of all readings at the defaults. Adding a
signature to every emergency message costs essentially nothing.

**The aggregate MAC is at the edge of measurability, and which side of the edge
depends on the scenario.** Highway shows +0.26 % at p = 0.004; urban shows
−0.17 % at p = 0.63, i.e. noise. Urban networks die at round ~9.6 against the
highway's ~23, so there is far less averaging and the variance swamps a
sub-percent effect. Reporting the urban figure as a *reduction* would be
reading noise as signal.

## The computation cost is not negligible, and the base paper cannot see it

The base paper states its assumption plainly (Sect. 3.3): energy is consumed by
transmission and reception, *"while computations and processing do not incur
energy expenditure"*. For a protocol with no cryptography that is defensible.
With a crypto layer it needs testing.

Transmitting the 72 B class-2 overhead at 90 m costs **0.078 mJ**. Against
that, ECDSA verification costs time × CPU power. CPU power is an assumption, so
it is swept rather than asserted; the slowdown factor for OBU-class hardware
relative to this machine is also an assumption, and embedded ARM cores run
ECDSA P-256 roughly 20–50× slower than a desktop core.

| OBU slowdown | verify | 0.25 W | 0.5 W | 1.0 W | 2.0 W |
|---|---|---|---|---|---|
| 1× (this machine) | 97 µs | 0.024 | 0.049 | 0.097 | 0.195 mJ |
| 10× | 974 µs | 0.243 | 0.487 | 0.974 | 1.948 mJ |
| 25× | 2435 µs | 0.609 | **1.217** | 2.435 | 4.869 mJ |
| 50× | 4869 µs | 1.217 | 2.435 | 4.869 | 9.738 mJ |

The assumption-light way to state it is a break-even. Verification costs more
energy than transmitting its own signature once verify time exceeds:

| CPU power | break-even verify time | |
|---|---|---|
| 0.25 W | 312 µs | |
| 0.5 W | 156 µs | |
| 1.0 W | 78 µs | **already exceeded on this laptop** |
| 2.0 W | 39 µs | **already exceeded on this laptop** |

At a plausible 25× slowdown and 0.5 W, verification costs **1.22 mJ against
0.078 mJ to transmit what it verifies — about 15×.** On this laptop at 1 W it
is already past break-even.

**So the cost of the crypto layer is dominated by computation, and the base
paper's model is structurally incapable of showing that**, because it charges
only radio. Module 5's "cost of priority" figures remain a lower bound — not
because `sig_bits` was 0, which is now fixed, but because the simulator charges
no computation at all.

## What this does not do

**Computation energy is measured and reported here; it is not charged in the
simulator.** Adding it would touch every protocol and every result — all nodes
sign and verify, not just emergency vehicles — and would change the Module 1
and Module 2 baselines that the whole comparison rests on. That is a deliberate
scope boundary, not an oversight. The expected effect is stated above so the
decision can be made on evidence: at 25× and 0.5 W, one verification per
class-2 message is ~1.2 mJ against a cluster head's ~88 mJ per round.

**Timings are from an x86-64 OpenSSL under Rosetta**, not a native arm64 build
and certainly not an OBU. They are labelled as measured-here throughout, and
every OBU number in this document is an explicit extrapolation with the
assumption named.

**No hardware acceleration is modelled.** Automotive HSMs with ECDSA engines
change the computation picture substantially and would move the break-even.

## Effect on the Module 5 tables

`docs/priority.md` findings 2, 3 and 5 were produced with `sig_bits = mac_bits
= 0` and have been re-run with the measured values. The qualitative results are
unchanged — deadline-miss goes to zero under the bypass, authorisation
eliminates the false-priority attack, trust does not — and the energy figures
move by under a percentage point.
