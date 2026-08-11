"""Module 3b -- measured cost of the crypto layer: bytes, microseconds, energy.

    python3 src/crypto_bench.py
    python3 src/crypto_bench.py --seconds 5      # longer, steadier timings

Feeds two numbers into config.py, `sig_bits` and `mac_bits`, which Module 5
left at 0 with the note that its measured cost of priority was therefore a
lower bound. This closes that.

Uses only the openssl CLI and the Python standard library, so it adds no
dependency to the project. Sizes are exact and platform-independent; timings
are measured here and labelled as such.

WHAT IS AND IS NOT MEASURED
---------------------------
Sizes come from real keys and real signatures, so they are facts. Timings are
measured on whatever machine runs this, which is not an OBU -- an on-board
unit is substantially slower, and the report states the assumption rather than
hiding it inside a single number. Energy per operation is time x CPU power,
and CPU power is an assumption, so it is swept rather than asserted.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config                       # noqa: E402
from energy import tx_energy                    # noqa: E402

# ---------------------------------------------------------------- wire format
#
# IEEE 1609.2 compact encodings, not DER. DER is measured too, for contrast:
# it adds 6 bytes of framing to a P-256 signature and is not what a vehicular
# stack puts on the air.
#
# A class-2 message carries a signature plus a way to find the signer's
# certificate. 1609.2 allows either the full certificate or an 8-byte
# HashedId8 digest of it, and a real deployment sends the full certificate
# periodically and the digest the rest of the time. The digest variant is our
# default; the full-certificate variant is reported as the pessimistic case.
SIG_RAW = 64            # ECDSA P-256, r || s
CERT_DIGEST = 8         # HashedId8
MAC_TRUNC = 16          # aggregate MAC truncated to 128 bits

CERT_FIELDS = {         # our pseudonym certificate, explicit form
    "pseudonym id": 8,
    "public key (compressed point)": 33,
    "role attribute": 1,
    "validity start/end": 8,
    "issuer id": 8,
    "TA signature (ECDSA P-256)": 64,
}
CERT_TOTAL = sum(CERT_FIELDS.values())


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def measure_sizes() -> dict:
    """Generate a real key, sign a real message, measure what comes out."""
    out = {"cert_fields": CERT_FIELDS, "cert_total": CERT_TOTAL}
    if not shutil.which("openssl"):
        out["openssl"] = None
        return out
    out["openssl"] = sh("openssl version").stdout.strip()
    with tempfile.TemporaryDirectory() as d:
        k, m, s = f"{d}/k.pem", f"{d}/m.bin", f"{d}/s.der"
        sh(f"openssl ecparam -name prime256v1 -genkey -noout -out {k}")
        Path(m).write_bytes(b"emergency: ambulance approaching, lane 2")
        sh(f"openssl dgst -sha256 -sign {k} -out {s} {m}")
        out["sig_der"] = Path(s).stat().st_size
        for form, name in (("compressed", "pub_compressed_der"),
                           ("uncompressed", "pub_uncompressed_der")):
            p = f"{d}/p_{form}.der"
            sh(f"openssl ec -in {k} -pubout -conv_form {form} "
               f"-outform DER -out {p}")
            out[name] = Path(p).stat().st_size
    out["sig_raw"] = SIG_RAW
    return out


def measure_ecdsa(seconds: int) -> dict:
    """openssl speed ecdsap256 -- sign/s and verify/s."""
    if not shutil.which("openssl"):
        return {}
    r = sh(f"openssl speed -seconds {seconds} ecdsap256")
    for line in (r.stdout + r.stderr).splitlines():
        if "nistp256" in line:
            nums = re.findall(r"([\d.]+)\s*$|([\d.]+)\s+([\d.]+)\s*$", line)
            f = re.findall(r"[\d.]+", line)
            if len(f) >= 2:
                sign_s, ver_s = float(f[-2]), float(f[-1])
                return {"sign_per_s": sign_s, "verify_per_s": ver_s,
                        "sign_us": 1e6 / sign_s, "verify_us": 1e6 / ver_s}
    return {}


def measure_mac(packet_bytes: int, seconds: float) -> dict:
    key, msg = os.urandom(32), os.urandom(packet_bytes)
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        for _ in range(2000):
            hmac.new(key, msg, hashlib.sha256).digest()
        n += 2000
    dt = time.perf_counter() - t0
    return {"mac_per_s": n / dt, "mac_us": dt / n * 1e6,
            "packet_bytes": packet_bytes}


def radio_cost(cfg, bits: int, dist_m: float) -> float:
    """mJ to transmit `bits` extra bits over `dist_m`."""
    return float(tx_energy(cfg, bits, dist_m)) * 1e3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=3)
    args = ap.parse_args()
    cfg = Config()

    sizes = measure_sizes()
    ec = measure_ecdsa(args.seconds)
    mac = measure_mac(cfg.packet_bits // 8, min(args.seconds, 2))

    sig_digest_B = SIG_RAW + CERT_DIGEST
    sig_full_B = SIG_RAW + CERT_TOTAL

    print("=" * 74)
    print("1  SIZES  (exact; measured from real keys and signatures)")
    print("=" * 74)
    if sizes.get("openssl"):
        print(f"  {sizes['openssl']}")
    print(f"  ECDSA P-256 signature, raw r||s          {SIG_RAW:>5} B")
    if "sig_der" in sizes:
        print(f"  ECDSA P-256 signature, DER               {sizes['sig_der']:>5} B"
              f"   (+{sizes['sig_der']-SIG_RAW} B framing; 1609.2 uses raw)")
        print(f"  public key, compressed point (DER)       {sizes['pub_compressed_der']:>5} B"
              f"   (raw point 33 B)")
    print(f"\n  pseudonym certificate, explicit form:")
    for k, v in CERT_FIELDS.items():
        print(f"      {k:<36}{v:>5} B")
    print(f"      {'TOTAL':<36}{CERT_TOTAL:>5} B")
    print(f"\n  class-2 overhead, cert digest (default)  {sig_digest_B:>5} B"
          f"   = {sig_digest_B*8} bits")
    print(f"  class-2 overhead, full certificate       {sig_full_B:>5} B"
          f"   = {sig_full_B*8} bits")
    print(f"  aggregate MAC, truncated to 128 bits     {MAC_TRUNC:>5} B"
          f"   = {MAC_TRUNC*8} bits")

    print()
    print("=" * 74)
    print("2  TIMINGS  (this machine, not an OBU)")
    print("=" * 74)
    if ec:
        print(f"  ECDSA P-256 sign      {ec['sign_per_s']:>12,.0f} /s"
              f"   {ec['sign_us']:>8.1f} us")
        print(f"  ECDSA P-256 verify    {ec['verify_per_s']:>12,.0f} /s"
              f"   {ec['verify_us']:>8.1f} us"
              f"   <- {ec['verify_us']/ec['sign_us']:.1f}x sign")
    print(f"  HMAC-SHA256 / {mac['packet_bytes']} B  {mac['mac_per_s']:>12,.0f} /s"
          f"   {mac['mac_us']:>8.2f} us")
    print("\n  Verification is the expensive direction and it is the one CHIRP")
    print("  does most: a head verifies every class-2 assertion it admits, and")
    print("  the RSU verifies every verbatim message it receives.")

    print()
    print("=" * 74)
    print("3  RADIO COST OF THE EXTRA BITS  (the part Module 5 now charges)")
    print("=" * 74)
    print(f"  {'distance':>10}{'class-2 sig+digest':>22}{'full cert':>14}"
          f"{'aggregate MAC':>16}")
    for d in (30.0, 60.0, 90.0, 120.0, 150.0):
        print(f"  {d:>8.0f} m{radio_cost(cfg, sig_digest_B*8, d):>21.4f} mJ"
              f"{radio_cost(cfg, sig_full_B*8, d):>13.4f} mJ"
              f"{radio_cost(cfg, MAC_TRUNC*8, d):>15.4f} mJ")
    print(f"\n  d0 = {cfg.d0:.1f} m; beyond it the amplifier goes as d^4.")

    print()
    print("=" * 74)
    print("4  COMPUTATION ENERGY vs RADIO ENERGY")
    print("=" * 74)
    print("  The base paper assumes computation is free (Sect. 3.3: 'energy")
    print("  consumption is required for message transmission and reception,")
    print("  while computations and processing do not incur energy")
    print("  expenditure'). With a crypto layer that assumption needs testing.")
    print("\n  CPU power is an ASSUMPTION and is swept. OBU slowdown relative")
    print("  to this machine is also an assumption; embedded ARM cores run")
    print("  ECDSA P-256 roughly 20-50x slower than a desktop core.")
    if ec:
        radio_sig = radio_cost(cfg, sig_digest_B * 8, 90.0)
        print(f"\n  Reference: transmitting the {sig_digest_B} B class-2 overhead"
              f" at 90 m costs {radio_sig:.4f} mJ\n")
        print(f"  {'slowdown':>9}{'verify':>11}" + "".join(
            f"{f'{p} W':>12}" for p in (0.25, 0.5, 1.0, 2.0)))
        for slow in (1, 10, 25, 50):
            t_us = ec["verify_us"] * slow
            row = f"  {slow:>8}x{t_us:>9.0f} us"
            for p in (0.25, 0.5, 1.0, 2.0):
                mj = t_us * 1e-6 * p * 1e3
                row += f"{mj:>10.3f} mJ" if mj < 100 else f"{mj:>10.1f} mJ"
            print(row)
        print(f"\n  Break-even: verification costs more energy than sending its")
        print(f"  own signature once verify time exceeds")
        for p in (0.25, 0.5, 1.0, 2.0):
            t_be = radio_sig * 1e-3 / p * 1e6
            print(f"      {t_be:>8.0f} us at {p} W"
                  + ("   <- already exceeded on THIS machine"
                     if ec["verify_us"] > t_be else ""))

    print()
    print("=" * 74)
    print("5  VALUES FOR config.py")
    print("=" * 74)
    print(f"  sig_bits = {sig_digest_B*8}      # {SIG_RAW} B signature"
          f" + {CERT_DIGEST} B cert digest")
    print(f"  mac_bits = {MAC_TRUNC*8}      # {MAC_TRUNC} B truncated aggregate MAC")
    print(f"  (pessimistic variant: sig_bits = {sig_full_B*8}, full certificate)")

    out = {
        "sizes": sizes, "ecdsa": ec, "mac": mac,
        "sig_bits_digest": sig_digest_B * 8,
        "sig_bits_full_cert": sig_full_B * 8,
        "mac_bits": MAC_TRUNC * 8,
        "radio_mJ": {str(d): radio_cost(cfg, sig_digest_B * 8, d)
                     for d in (30.0, 60.0, 90.0, 120.0, 150.0)},
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/crypto_bench.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
