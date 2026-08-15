"""Generate the final BTP figures and tables from committed result artifacts.

This is a presentation-only runner.  It refuses untracked or locally modified
source artifacts, reads no values from the project documentation, and does not
invoke any simulator or experiment runner.

    python3 src/generate_final_results.py

Outputs:
    figures/final/   five figures in PNG and PDF plus README/manifest
    tables/final/    five Markdown tables plus README/manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "chirp-matplotlib")
)
os.environ.setdefault(
    "XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "chirp-cache")
)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
import numpy as np  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
DEFAULT_FIGURE_DIR = ROOT / "figures" / "final"
DEFAULT_TABLE_DIR = ROOT / "tables" / "final"
GENERATOR_COMMAND = "python3 src/generate_final_results.py"

SOURCE_PATHS = {
    "crypto_bench": RESULTS / "crypto_bench.json",
    "module1_highway": RESULTS / "module1_highway.json",
    "module1_urban": RESULTS / "module1_urban.json",
    "module2_urban": RESULTS / "module2_urban.json",
    "priority_bypass_highway": RESULTS / "priority_bypass_highway.json",
    "priority_bypass_urban": RESULTS / "priority_bypass_urban.json",
    "priority_coverage_highway": RESULTS / "priority_coverage_highway.json",
    "priority_coverage_urban": RESULTS / "priority_coverage_urban.json",
    "priority_cryptodecomp_highway": RESULTS / "priority_cryptodecomp_highway.json",
    "priority_cryptodecomp_urban": RESULTS / "priority_cryptodecomp_urban.json",
    "priority_defence_highway": RESULTS / "priority_defence_highway.json",
    "priority_defence_urban": RESULTS / "priority_defence_urban.json",
    "priority_greed_highway": RESULTS / "priority_greed_highway.json",
    "priority_greed_urban": RESULTS / "priority_greed_urban.json",
    "radio_ablation_highway": RESULTS / "radio_ablation_highway.json",
    "radio_bypass_highway": RESULTS / "radio_bypass_highway.json",
    "radio_bypass_urban": RESULTS / "radio_bypass_urban.json",
    "radio_calibration": RESULTS / "radio_calibration.json",
    "radio_coverage_highway": RESULTS / "radio_coverage_highway.json",
    "radio_coverage_urban": RESULTS / "radio_coverage_urban.json",
    "radio_crypto": RESULTS / "radio_crypto.json",
    "radio_defence_highway": RESULTS / "radio_defence_highway.json",
    "radio_defence_urban": RESULTS / "radio_defence_urban.json",
    "radio_expsweep_urban": RESULTS / "radio_expsweep_urban.json",
    "radio_freeride_urban": RESULTS / "radio_freeride_urban.json",
    "radio_greed_highway": RESULTS / "radio_greed_highway.json",
    "radio_greed_urban": RESULTS / "radio_greed_urban.json",
    "radio_module1_highway": RESULTS / "radio_module1_highway.json",
    "radio_module1_urban": RESULTS / "radio_module1_urban.json",
}

SCENARIOS = ("urban", "highway")
PROTOCOLS = ("LEACH", "LEACH-C", "HEED", "PSO", "GA", "CSGD-NET", "CHIRP")
MODULE2_PROTOCOLS = (
    "CSGD-NET",
    "LEACH-C",
    "CHIRP (no trust)",
    "CHIRP + trust",
)
DEFENCES = ("none", "trust", "auth")

PROTOCOL_COLORS = {
    "LEACH": "#0072B2",
    "LEACH-C": "#E69F00",
    "HEED": "#009E73",
    "PSO": "#D55E00",
    "GA": "#CC79A7",
    "CSGD-NET": "#222222",
    "CHIRP": "#6F4E9C",
    "CHIRP (no trust)": "#8C6BB1",
    "CHIRP + trust": "#54278F",
}
PROTOCOL_MARKERS = {
    "LEACH": "o",
    "LEACH-C": "s",
    "HEED": "^",
    "PSO": "D",
    "GA": "v",
    "CSGD-NET": "P",
    "CHIRP": "X",
    "CHIRP (no trust)": "d",
    "CHIRP + trust": "X",
}
DEFENCE_LABELS = {
    "none": "None (no admission defence)",
    "trust": "Trust gate",
    "auth": "Authorisation",
}
DEFENCE_STYLES = {
    "none": {"color": "#B2182B", "marker": "o", "linestyle": "-"},
    "trust": {"color": "#E69F00", "marker": "s", "linestyle": "--"},
    "auth": {"color": "#009E73", "marker": "^", "linestyle": "-."},
}
RADIO_LABELS = {
    "heinzelman": "Heinzelman",
    "logdistance": "Log-distance",
}

plt.rcParams.update(
    {
        "font.size": 9.5,
        "axes.titlesize": 10.5,
        "axes.labelsize": 9.5,
        "legend.fontsize": 8.0,
        "figure.titlesize": 13.0,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": "#b0b0b0",
        "grid.alpha": 0.30,
        "grid.linewidth": 0.6,
    }
)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(ROOT), *args),
        check=check,
        capture_output=True,
        text=True,
    )


def _assert_committed_sources(paths: Iterable[Path]) -> None:
    """Reject missing, untracked, staged, or unstaged numerical sources."""

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"required result artifact not found: {path}")
        rel = _relative(path)
        tracked = _run_git("ls-files", "--error-unmatch", "--", rel, check=False)
        if tracked.returncode != 0:
            raise RuntimeError(f"result source is not committed to Git: {rel}")
        if _run_git("diff", "--quiet", "--", rel, check=False).returncode != 0:
            raise RuntimeError(f"result source has unstaged modifications: {rel}")
        if _run_git("diff", "--cached", "--quiet", "--", rel, check=False).returncode != 0:
            raise RuntimeError(f"result source has staged modifications: {rel}")


def _load_sources() -> dict[str, dict[str, Any]]:
    _assert_committed_sources(SOURCE_PATHS.values())
    return {
        name: json.loads(path.read_text())
        for name, path in SOURCE_PATHS.items()
    }


def _public_records(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not key.startswith("_")}


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, float) and isinstance(right, float):
            if math.isnan(left) and math.isnan(right):
                return True
        return left == right
    return left == right


def _require_equal(left: Any, right: Any, label: str) -> None:
    if not _equal(left, right):
        raise ValueError(f"committed mirror check failed while presenting {label}")


def _validate_sources(data: dict[str, dict[str, Any]]) -> None:
    """Check that files combined in one visual really describe the same runs."""

    for scenario in SCENARIOS:
        module1 = data[f"module1_{scenario}"]
        radio = data[f"radio_module1_{scenario}"]
        if tuple(module1) != PROTOCOLS:
            raise ValueError(f"module1_{scenario} protocol order changed")
        if radio.get("_check", {}).get("status") != "OK":
            raise ValueError(f"radio_module1_{scenario} committed mirror is not OK")
        _require_equal(module1, _public_records(radio["heinzelman"]), f"Module 1 {scenario}")

        coverage = data[f"priority_coverage_{scenario}"]
        radio_coverage = data[f"radio_coverage_{scenario}"]
        if tuple(coverage) != PROTOCOLS:
            raise ValueError(f"priority_coverage_{scenario} protocol order changed")
        _require_equal(
            coverage,
            _public_records(radio_coverage["heinzelman"]),
            f"priority coverage {scenario}",
        )

        for experiment in ("defence", "greed", "bypass"):
            committed = data[f"priority_{experiment}_{scenario}"]
            mirror = data[f"radio_{experiment}_{scenario}"]
            if mirror.get("_check", {}).get("status") != "OK":
                raise ValueError(f"radio_{experiment}_{scenario} committed mirror is not OK")
            # The robustness runner intentionally samples only the headline
            # attack/greed points.  Validate every mirrored record against the
            # fuller committed sweep without requiring identical key sets.
            for key, record in _public_records(mirror["heinzelman"]).items():
                if key not in committed:
                    raise ValueError(
                        f"radio_{experiment}_{scenario} contains unknown key {key}"
                    )
                _require_equal(
                    committed[key],
                    record,
                    f"priority {experiment} {scenario} {key}",
                )

    module2 = data["module2_urban"]
    freeride = data["radio_freeride_urban"]
    if freeride.get("_check", {}).get("status") != "OK":
        raise ValueError("radio_freeride_urban committed mirror is not OK")
    for key, record in _public_records(freeride["heinzelman"]).items():
        _require_equal(module2[key], record, f"Module 2 free ride {key}")

    crypto = data["crypto_bench"]
    radio_crypto = data["radio_crypto"]
    _require_equal(
        crypto["ecdsa"]["verify_us"],
        radio_crypto["assumptions"]["verify_us_measured"],
        "crypto verification timing",
    )
    _require_equal(
        crypto["sig_bits_digest"],
        radio_crypto["assumptions"]["sig_bits"],
        "crypto signature size",
    )
    if data["radio_calibration"].get("agree_at_d0") is not True:
        raise ValueError("radio calibration does not record agreement at d0")


def _parse_composite(data: dict[str, Any]) -> list[tuple[float, str, dict[str, Any]]]:
    rows = []
    for key, record in data.items():
        if key.startswith("_"):
            continue
        number, category = key.split("|", 1)
        rows.append((float(number), category, record))
    return rows


def _series(
    rows: Sequence[tuple[float, str, dict[str, Any]]],
    category: str,
    metric: str,
) -> tuple[np.ndarray, np.ndarray]:
    selected = sorted(
        (number, record[metric])
        for number, name, record in rows
        if name == category
    )
    return (
        np.asarray([number for number, _ in selected], dtype=float),
        np.asarray([value for _, value in selected], dtype=float),
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _fmt(value: Any, digits: int = 3) -> str:
    if not _finite(value):
        return "—"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: Any, digits: int = 1) -> str:
    if not _finite(value):
        return "—"
    return f"{float(value):.{digits}f}%"


def _fmt_fraction_pct(value: Any, digits: int = 1) -> str:
    if not _finite(value):
        return "—"
    return _fmt_pct(float(value) * 100.0, digits)


def _fmt_p(value: Any) -> str:
    if not _finite(value):
        return "—"
    value = float(value)
    if value == 0.0:
        return "0"
    if abs(value) < 0.001:
        return f"{value:.2e}"
    return f"{value:.4f}"


def _fmt_seed_info(seed_map: dict[str, Any]) -> str:
    return "; ".join(f"{label}: {value}" for label, value in seed_map.items())


def _source_names(keys: Iterable[str]) -> list[str]:
    return [_relative(SOURCE_PATHS[key]) for key in keys]


def _radio_label(name: str) -> str:
    """Format a radio-model label, preserving exponents read from JSON keys."""

    if name in RADIO_LABELS:
        return RADIO_LABELS[name]
    if "g=" in name:
        gamma = name.split("g=", 1)[1].split(" ", 1)[0]
        return f"Log-distance γ={gamma}"
    return name


def _save_figure(
    fig: plt.Figure,
    stem: Path,
    *,
    title: str,
    source_keys: Sequence[str],
    derivations: Sequence[str],
) -> list[str]:
    stem.parent.mkdir(parents=True, exist_ok=True)
    sources = _source_names(source_keys)
    description = (
        f"Generated by {GENERATOR_COMMAND}. Sources: {', '.join(sources)}. "
        f"Derived calculations: {'; '.join(derivations) if derivations else 'none'}."
    )
    outputs = []
    for suffix in (".png", ".pdf"):
        path = stem.with_suffix(suffix)
        if suffix == ".png":
            metadata = {
                "Title": title,
                "Author": "CHIRP project",
                "Description": description,
                "Software": "src/generate_final_results.py",
            }
        else:
            metadata = {
                "Title": title,
                "Author": "CHIRP project",
                "Subject": description,
                "Creator": "src/generate_final_results.py",
                "CreationDate": None,
                "ModDate": None,
            }
        fig.savefig(path, dpi=300, metadata=metadata, bbox_inches="tight")
        outputs.append(path.name)
    plt.close(fig)
    return outputs


def _panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.12,
        1.04,
        label,
        transform=ax.transAxes,
        fontsize=10,
        fontweight="bold",
        va="bottom",
    )


def _plot_line(
    ax: plt.Axes,
    x: np.ndarray,
    y: np.ndarray,
    *,
    label: str,
    color: str,
    marker: str,
    linestyle: str = "-",
) -> None:
    ax.plot(
        x,
        y,
        label=label,
        color=color,
        marker=marker,
        linestyle=linestyle,
        linewidth=1.8,
        markersize=4.5,
    )


def _figure_module1(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "module1_urban",
        "module1_highway",
        "radio_module1_urban",
        "radio_module1_highway",
    )
    fig, axes = plt.subplots(2, 3, figsize=(13.0, 7.7), constrained_layout=True)
    panel = iter("abcdef")
    for row, scenario in enumerate(SCENARIOS):
        records = data[f"module1_{scenario}"]
        positions = np.arange(len(PROTOCOLS))
        colors = [PROTOCOL_COLORS[name] for name in PROTOCOLS]

        ax = axes[row, 0]
        fnd = np.asarray([records[name]["fnd"] for name in PROTOCOLS], dtype=float)
        hnd = np.asarray([records[name]["hnd"] for name in PROTOCOLS], dtype=float)
        for pos, first, half, color in zip(positions, fnd, hnd, colors):
            ax.plot((first, half), (pos, pos), color=color, linewidth=2.2, alpha=0.65)
            ax.scatter(first, pos, color=color, marker="o", s=28, zorder=3)
            ax.scatter(half, pos, color=color, marker="s", s=28, zorder=3)
        ax.set_yticks(positions, PROTOCOLS)
        ax.invert_yaxis()
        ax.set_xlabel("Node-death milestone (round)")
        ax.set_title(f"{scenario.title()}: lifetime")
        ax.grid(True, axis="x")
        ax.legend(
            handles=(
                Line2D([], [], color="#555555", marker="o", linestyle="", label="FND"),
                Line2D([], [], color="#555555", marker="s", linestyle="", label="HND"),
            ),
            frameon=False,
            loc="best",
        )
        _panel_label(ax, f"({next(panel)})")

        ax = axes[row, 1]
        energy = np.asarray(
            [records[name]["mj_per_reading"] for name in PROTOCOLS], dtype=float
        )
        ax.barh(positions, energy, color=colors, alpha=0.86)
        ax.set_yticks(positions, ())
        ax.invert_yaxis()
        ax.set_xlabel("Energy per delivered reading (mJ)")
        ax.set_title(f"{scenario.title()}: energy")
        ax.grid(True, axis="x")
        _panel_label(ax, f"({next(panel)})")

        ax = axes[row, 2]
        orphan_pct = np.asarray(
            [records[name]["orphan"] for name in PROTOCOLS], dtype=float
        ) * 100.0
        ax.barh(positions, orphan_pct, color=colors, alpha=0.86)
        ax.set_yticks(positions, ())
        ax.invert_yaxis()
        ax.set_xlabel("Orphan nodes (%)")
        ax.set_title(f"{scenario.title()}: coverage loss")
        ax.grid(True, axis="x")
        _panel_label(ax, f"({next(panel)})")

    seeds = {
        scenario: data[f"radio_module1_{scenario}"]["_meta"]["seeds"]
        for scenario in SCENARIOS
    }
    fig.suptitle("Module 1 protocol comparison")
    fig.text(
        0.5,
        -0.015,
        f"Aggregate means ({_fmt_seed_info(seeds)} seeds); no per-seed uncertainty is available.",
        ha="center",
        fontsize=8.5,
    )
    files = _save_figure(
        fig,
        output_dir / "module1_protocol_comparison",
        title="Module 1 protocol comparison",
        source_keys=source_keys,
        derivations=("orphan fraction × 100 = orphan percentage",),
    )
    return {
        "files": files,
        "sources": _source_names(source_keys),
        "derived_metrics": ["orphan fraction × 100 = orphan percentage"],
        "seed_information": seeds,
        "statistics": "Aggregate means only; no uncertainty intervals.",
    }


def _figure_module2(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = ("module2_urban", "radio_freeride_urban")
    rows = _parse_composite(data["module2_urban"])
    radio = data["radio_freeride_urban"]
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.0), constrained_layout=True)

    ax = axes[0, 0]
    for protocol in MODULE2_PROTOCOLS:
        x, y = _series(rows, protocol, "pdr")
        _plot_line(
            ax,
            x * 100.0,
            y,
            label=protocol,
            color=PROTOCOL_COLORS[protocol],
            marker=PROTOCOL_MARKERS[protocol],
        )
    ax.set(title="Delivery under mixed attack", xlabel="Attacker nodes (%)", ylabel="PDR")
    ax.grid(True)
    ax.legend(frameon=False, ncol=2)
    _panel_label(ax, "(a)")

    ax = axes[0, 1]
    for protocol in MODULE2_PROTOCOLS:
        x, y = _series(rows, protocol, "att_ch_share")
        _plot_line(
            ax,
            x * 100.0,
            y * 100.0,
            label=protocol,
            color=PROTOCOL_COLORS[protocol],
            marker=PROTOCOL_MARKERS[protocol],
        )
    fractions = np.asarray(sorted({fraction for fraction, _, _ in rows}), dtype=float)
    ax.plot(
        fractions * 100.0,
        fractions * 100.0,
        color="#777777",
        linestyle=":",
        linewidth=1.2,
        label="Attacker population share",
    )
    ax.set(
        title="Attacker cluster-head share",
        xlabel="Attacker nodes (%)",
        ylabel="Attacker share of CH assignments (%)",
    )
    ax.grid(True)
    ax.legend(frameon=False, ncol=2)
    _panel_label(ax, "(b)")

    ax = axes[1, 0]
    x, detection = _series(rows, "CHIRP + trust", "detect")
    _, fpr = _series(rows, "CHIRP + trust", "fpr")
    attack_present = x > 0.0
    _plot_line(
        ax,
        x[attack_present] * 100.0,
        detection[attack_present] * 100.0,
        label="Detection rate",
        color="#54278F",
        marker="o",
    )
    _plot_line(
        ax,
        x[attack_present] * 100.0,
        fpr[attack_present] * 100.0,
        label="False-positive rate",
        color="#B2182B",
        marker="s",
        linestyle="--",
    )
    ax.set(
        title="CHIRP trust classification",
        xlabel="Attacker nodes (%)",
        ylabel="Rate (%)",
    )
    ax.grid(True)
    ax.legend(frameon=False)
    _panel_label(ax, "(c)")

    ax = axes[1, 1]
    for arm, style in (
        ("heinzelman", {"color": "#222222", "marker": "o", "linestyle": "-"}),
        ("logdistance", {"color": "#0072B2", "marker": "s", "linestyle": "--"}),
    ):
        arm_rows = _parse_composite(radio[arm])
        x, y = _series(arm_rows, "CHIRP + trust", "e_adv")
        _plot_line(
            ax,
            x * 100.0,
            y,
            label=_radio_label(arm),
            **style,
        )
    ax.axhline(1.0, color="#777777", linestyle=":", linewidth=1.2, label="Equal residual energy")
    ax.set(
        title="Attacker energy free ride",
        xlabel="Attacker nodes (%)",
        ylabel="Attacker / honest mean residual energy",
    )
    ax.grid(True)
    ax.legend(frameon=False)
    _panel_label(ax, "(d)")

    seeds = radio["_meta"]["seeds"]
    fig.suptitle("Module 2 trust, security and attacker free ride")
    fig.text(
        0.5,
        -0.012,
        f"Aggregate means ({seeds} seeds); no confidence intervals are reconstructed from aggregate data.",
        ha="center",
        fontsize=8.5,
    )
    files = _save_figure(
        fig,
        output_dir / "module2_trust_security_free_ride",
        title="Module 2 trust, security and attacker free ride",
        source_keys=source_keys,
        derivations=(
            "attacker fraction × 100 = attacker percentage",
            "attacker CH share × 100 = percentage",
            "detection and false-positive fractions × 100 = percentages",
        ),
    )
    return {
        "files": files,
        "sources": _source_names(source_keys),
        "derived_metrics": [
            "fractions multiplied by 100 for percentage axes",
            "reference ratio 1 denotes equal attacker and honest residual energy",
        ],
        "seed_information": {"urban": seeds},
        "statistics": "Aggregate means only; no uncertainty intervals or new significance tests.",
    }


def _figure_priority_coverage(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "priority_coverage_urban",
        "priority_coverage_highway",
        "radio_coverage_urban",
        "radio_coverage_highway",
    )
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.2), constrained_layout=False)
    for panel, (ax, scenario) in enumerate(zip(axes, SCENARIOS)):
        records = data[f"priority_coverage_{scenario}"]
        radio = data[f"radio_coverage_{scenario}"]
        spearman = radio["heinzelman"]["_spearman"]
        for protocol in PROTOCOLS:
            record = records[protocol]
            ax.scatter(
                record["orphan_pct"],
                record["ems_miss"],
                color=PROTOCOL_COLORS[protocol],
                marker=PROTOCOL_MARKERS[protocol],
                s=54,
                label=protocol,
            )
        ax.set(
            title=(
                f"{scenario.title()} — stored Spearman ρ={_fmt(spearman['rho'], 3)}, "
                f"p={_fmt_p(spearman['p'])}"
            ),
            xlabel="Orphan nodes (%) — lower means better coverage",
            ylabel="Emergency deadline-miss fraction",
        )
        ax.grid(True)
        _panel_label(ax, f"({chr(ord('a') + panel)})")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        frameon=False,
        ncol=len(PROTOCOLS),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.90),
    )
    seed_info = {
        scenario: data[f"radio_coverage_{scenario}"]["_meta"]["seeds"]
        for scenario in SCENARIOS
    }
    fig.suptitle("Priority coverage–deadline relationship", y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.77, bottom=0.20, wspace=0.27)
    fig.text(
        0.5,
        0.045,
        f"Aggregate means ({_fmt_seed_info(seed_info)} seeds); Spearman statistics are read from committed radio mirrors.",
        ha="center",
        fontsize=8.5,
    )
    files = _save_figure(
        fig,
        output_dir / "priority_coverage_deadline",
        title="Priority coverage–deadline relationship",
        source_keys=source_keys,
        derivations=(),
    )
    return {
        "files": files,
        "sources": _source_names(source_keys),
        "derived_metrics": ["No new statistic; stored Spearman rho and p are displayed."],
        "seed_information": seed_info,
        "statistics": "Aggregate protocol means plus stored Spearman statistics; no uncertainty intervals.",
    }


def _figure_priority_abuse(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "priority_defence_urban",
        "priority_defence_highway",
        "priority_greed_urban",
        "priority_greed_highway",
        "radio_defence_urban",
        "radio_defence_highway",
        "radio_greed_urban",
        "radio_greed_highway",
    )
    fig, axes = plt.subplots(2, 3, figsize=(14.2, 7.8), constrained_layout=True)
    panel = iter("abcdef")
    for row, scenario in enumerate(SCENARIOS):
        defence_rows = _parse_composite(data[f"priority_defence_{scenario}"])
        greed_rows = _parse_composite(data[f"priority_greed_{scenario}"])

        ax = axes[row, 0]
        for defence in DEFENCES:
            x, y = _series(defence_rows, defence, "ems_miss")
            _plot_line(
                ax,
                x * 100.0,
                y,
                label=DEFENCE_LABELS[defence],
                **DEFENCE_STYLES[defence],
            )
        ax.set(
            title=f"{scenario.title()}: attacker population",
            xlabel="Attacker nodes (%)",
            ylabel="Emergency deadline-miss fraction",
        )
        ax.grid(True)
        ax.legend(frameon=False)
        _panel_label(ax, f"({next(panel)})")

        ax = axes[row, 1]
        for defence in DEFENCES:
            x, y = _series(greed_rows, defence, "ems_miss")
            _plot_line(
                ax,
                x * 100.0,
                y,
                label=DEFENCE_LABELS[defence],
                **DEFENCE_STYLES[defence],
            )
        ax.set(
            title=f"{scenario.title()}: false-priority assertion rate",
            xlabel="False-priority assertion rate (%)",
            ylabel="Emergency deadline-miss fraction",
        )
        ax.grid(True)
        ax.legend(frameon=False)
        _panel_label(ax, f"({next(panel)})")

        ax = axes[row, 2]
        for defence in ("trust", "auth"):
            x, detection = _series(greed_rows, defence, "detect")
            _, fpr = _series(greed_rows, defence, "fpr")
            style = DEFENCE_STYLES[defence]
            _plot_line(
                ax,
                x * 100.0,
                detection * 100.0,
                label=f"{DEFENCE_LABELS[defence]} detection",
                color=style["color"],
                marker=style["marker"],
                linestyle="-",
            )
            _plot_line(
                ax,
                x * 100.0,
                fpr * 100.0,
                label=f"{DEFENCE_LABELS[defence]} FPR",
                color=style["color"],
                marker=style["marker"],
                linestyle=":",
            )
        ax.set(
            title=f"{scenario.title()}: behavioural visibility",
            xlabel="False-priority assertion rate (%)",
            ylabel="Detection / false-positive rate (%)",
        )
        ax.grid(True)
        ax.legend(frameon=False, ncol=2)
        _panel_label(ax, f"({next(panel)})")

    seed_info = {
        scenario: data[f"radio_defence_{scenario}"]["_meta"]["seeds"]
        for scenario in SCENARIOS
    }
    fig.suptitle("Priority abuse, behavioural trust and authorisation")
    fig.text(
        0.5,
        -0.014,
        f"The zero-attacker points are baselines; all curves are aggregate means ({_fmt_seed_info(seed_info)} seeds).",
        ha="center",
        fontsize=8.5,
    )
    files = _save_figure(
        fig,
        output_dir / "priority_abuse_defence",
        title="Priority abuse, behavioural trust and authorisation",
        source_keys=source_keys,
        derivations=("fractions × 100 = percentages",),
    )
    return {
        "files": files,
        "sources": _source_names(source_keys),
        "derived_metrics": ["fractions multiplied by 100 for percentage axes"],
        "seed_information": seed_info,
        "statistics": "Aggregate means only; no new significance claim is made.",
    }


def _figure_crypto_radio(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "crypto_bench",
        "priority_cryptodecomp_urban",
        "priority_cryptodecomp_highway",
        "radio_crypto",
        "radio_expsweep_urban",
        "radio_calibration",
    )
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.5), constrained_layout=True)

    ax = axes[0, 0]
    stage_names = list(data["priority_cryptodecomp_urban"])
    stage_labels = {
        "no crypto, no bypass": "Baseline",
        "+ aggregate MAC": "+ aggregate\nMAC",
        "+ bypass, no signature": "+ priority\nbypass",
        "+ per-message signature": "+ message\nsignature",
    }
    positions = np.arange(len(stage_names))
    for scenario, style in (
        ("urban", {"color": "#D55E00", "marker": "o"}),
        ("highway", {"color": "#0072B2", "marker": "s"}),
    ):
        records = data[f"priority_cryptodecomp_{scenario}"]
        base = records[stage_names[0]]["mJ_per_reading"]
        cumulative = np.asarray(
            [
                (records[stage]["mJ_per_reading"] / base - 1.0) * 100.0
                for stage in stage_names
            ]
        )
        for stage, derived in zip(stage_names[1:], cumulative[1:]):
            stored = records[stage]["cumulative_pct"]
            if not np.isclose(derived, stored):
                raise ValueError(f"crypto cumulative percentage mismatch: {scenario} {stage}")
        _plot_line(
            ax,
            positions,
            cumulative,
            label=scenario.title(),
            linestyle="-",
            **style,
        )
    ax.axhline(0.0, color="#777777", linewidth=1.0)
    ax.set_xticks(positions, [stage_labels[name] for name in stage_names])
    ax.set(
        title="Cumulative transmission-energy change",
        ylabel="Change from no-crypto/no-bypass baseline (%)",
    )
    ax.grid(True, axis="y")
    ax.legend(frameon=False)
    _panel_label(ax, "(a)")

    ax = axes[0, 1]
    radio_crypto = data["radio_crypto"]
    model_keys = [
        key
        for key, value in radio_crypto.items()
        if isinstance(value, dict) and "ratios" in value
    ]
    model_styles = (
        {"color": "#222222", "marker": "o", "linestyle": "-"},
        {"color": "#0072B2", "marker": "s", "linestyle": "--"},
        {"color": "#D55E00", "marker": "^", "linestyle": "-."},
    )
    for model, style in zip(model_keys, model_styles):
        ratios = radio_crypto[model]["ratios"]
        distances = np.asarray(sorted(float(key) for key in ratios), dtype=float)
        values = np.asarray([ratios[str(int(distance))]["ratio"] for distance in distances])
        break_even = radio_crypto[model]["break_even_m"]
        _plot_line(
            ax,
            distances,
            values,
            label=f"{_radio_label(model)}; break-even {_fmt(break_even, 0)} m",
            **style,
        )
    ax.axhline(1.0, color="#777777", linestyle=":", linewidth=1.2)
    ax.set_yscale("log")
    assumptions = radio_crypto["assumptions"]
    ax.set(
        title=(
            "Verification energy / signature-radio energy\n"
            f"Estimate: {_fmt(assumptions['verify_us_measured'], 1)} µs × "
            f"{_fmt(assumptions['obu_slowdown'], 0)} OBU slowdown factor × "
            f"{_fmt(assumptions['cpu_w'], 1)} W; "
            f"{_fmt(assumptions['sig_bits'], 0)}-bit radio denominator"
        ),
        xlabel="Transmission distance (m)",
        ylabel="Energy ratio (×, log scale)",
    )
    ax.grid(True, which="both")
    ax.legend(frameon=False)
    _panel_label(ax, "(b)")

    ax = axes[1, 0]
    sweep = data["radio_expsweep_urban"]
    sweep_rows = sorted(
        (float(key.split("=", 1)[1]), value)
        for key, value in sweep.items()
        if key.startswith("gamma=")
    )
    gamma = np.asarray([value for value, _ in sweep_rows], dtype=float)
    metric_labels = {
        "fnd": "FND",
        "hnd": "HND",
        "mj_per_reading": "Energy / reading",
        "orphan": "Orphan rate",
        "intra": "Intra-cluster distance",
    }
    for index, (metric, label) in enumerate(metric_labels.items()):
        values = np.asarray([record[metric] for _, record in sweep_rows], dtype=float)
        color = list(PROTOCOL_COLORS.values())[index]
        _plot_line(
            ax,
            gamma,
            values,
            label=label,
            color=color,
            marker=("o", "s", "^", "D", "v")[index],
        )
    ax.axhline(0.0, color="#777777", linewidth=1.0)
    ax.set(
        title="Urban path-loss exponent sensitivity",
        xlabel="Log-distance path-loss exponent γ",
        ylabel="CHIRP vs CSGD-NET change (%)",
    )
    ax.grid(True)
    ax.legend(frameon=False, ncol=2)
    _panel_label(ax, "(c)")

    ax = axes[1, 1]
    calibration = data["radio_calibration"]
    distances = np.asarray(sorted(float(key) for key in calibration["rows"]), dtype=float)
    calibration_models = list(next(iter(calibration["rows"].values())))
    for model, style in zip(calibration_models, model_styles):
        values = np.asarray(
            [calibration["rows"][format(distance, "g")][model]["mJ"] for distance in distances]
        )
        _plot_line(
            ax,
            distances,
            values,
            label=_radio_label(model),
            **style,
        )
    ax.set_yscale("log")
    ax.set(
        title=f"Radio calibration ({calibration['packet_bits']} bits)",
        xlabel="Transmission distance (m)",
        ylabel="Transmit energy (mJ, log scale)",
    )
    ax.grid(True, which="both")
    ax.legend(frameon=False)
    _panel_label(ax, "(d)")

    fig.suptitle("Cryptographic overhead and radio-model robustness")
    fig.text(
        0.5,
        -0.012,
        "Crypto decomposition is aggregate and carries only stored paired p-values; compute energy is an estimate under JSON-recorded assumptions.",
        ha="center",
        fontsize=8.5,
    )
    files = _save_figure(
        fig,
        output_dir / "crypto_radio_robustness",
        title="Cryptographic overhead and radio-model robustness",
        source_keys=source_keys,
        derivations=(
            "cumulative energy change = (stage mJ/read ÷ baseline mJ/read − 1) × 100",
            "gamma parsed from experiment keys",
            "verification energy estimate = measured verification time × OBU slowdown × CPU power; radio denominator uses the stored signature bit count",
            "all compute/radio ratios and break-even distances are stored in radio_crypto.json",
        ),
    )
    return {
        "files": files,
        "sources": _source_names(source_keys),
        "derived_metrics": [
            "cumulative percentage change from each scenario's baseline mJ/read",
            "verification-energy estimate = measured verification time × OBU slowdown × CPU power; radio denominator uses the stored signature bit count",
            "no compute-energy value is charged to the simulator",
        ],
        "seed_information": {
            "crypto decomposition": "not encoded in source JSON",
            "urban exponent sweep": sweep["_meta"]["seeds"],
            "crypto benchmark and calibration": "analytic/benchmark, not seed-based",
        },
        "statistics": "Stored paired p-values only; no uncertainty reconstructed.",
    }


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(_escape_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_escape_cell(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _write_table_document(
    path: Path,
    *,
    title: str,
    source_keys: Sequence[str],
    seed_information: str,
    statistics: str,
    derivations: Sequence[str],
    sections: Sequence[tuple[str, Sequence[str], Sequence[Sequence[Any]]]],
) -> None:
    lines = [
        f"# {title}",
        "",
        f"Generated by `{GENERATOR_COMMAND}` from committed JSON artifacts.",
        "",
        "**Sources:** " + ", ".join(f"`{name}`" for name in _source_names(source_keys)),
        "",
        f"**Seed information:** {seed_information}",
        "",
        f"**Statistics:** {statistics}",
        "",
        "**Derived calculations:** "
        + ("; ".join(derivations) if derivations else "none"),
        "",
    ]
    for heading, headers, rows in sections:
        lines.extend((f"## {heading}", "", _markdown_table(headers, rows), ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n")


def _table_module1(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "module1_urban",
        "module1_highway",
        "radio_module1_urban",
        "radio_module1_highway",
        "radio_ablation_highway",
    )
    metric_rows = []
    for scenario in SCENARIOS:
        for protocol in PROTOCOLS:
            record = data[f"module1_{scenario}"][protocol]
            metric_rows.append(
                (
                    scenario.title(),
                    protocol,
                    _fmt(record["fnd"], 2),
                    _fmt(record["hnd"], 2),
                    _fmt(record["lnd"], 2),
                    _fmt(record["mj_per_reading"], 4),
                    _fmt_fraction_pct(record["orphan"], 2),
                    _fmt(record["intra"], 2),
                )
            )

    ablation = data["radio_ablation_highway"]
    ablation_rows = []
    drop_labels = {
        "w_energy": "Energy",
        "w_rsu": "RSU transmit cost",
        "w_intra": "Intra-cluster distance",
        "w_let": "Link expiration time",
        "w_balance": "Cluster balance",
    }
    for arm in ("heinzelman", "logdistance"):
        for dropped, record in ablation[arm]["_deltas"].items():
            ablation_rows.append(
                (
                    _radio_label(arm),
                    drop_labels[dropped],
                    _fmt_pct(record["fnd_pct"], 2),
                    _fmt_pct(record["mj_pct"], 2),
                    _fmt_pct(record["intra_pct"], 2),
                )
            )

    seed_map = {
        scenario: data[f"radio_module1_{scenario}"]["_meta"]["seeds"]
        for scenario in SCENARIOS
    }
    seed_map["current-default highway ablation"] = ablation["_meta"]["seeds"]
    filename = "module1_key_metrics_and_ablation.md"
    _write_table_document(
        output_dir / filename,
        title="Module 1 key metrics and current-default ablation",
        source_keys=source_keys,
        seed_information=_fmt_seed_info(seed_map),
        statistics=(
            "Aggregate means and descriptive ablation deltas. The table does not "
            "reconstruct confidence intervals or significance from aggregate values. "
            "The ablation is the current-default radio run; its historical-reference "
            "mismatch is expected and is not used as source data here."
        ),
        derivations=(
            "orphan fraction × 100 = orphan percentage",
            "ablation deltas are read from the committed radio artifact",
        ),
        sections=(
            (
                "Protocol comparison",
                (
                    "Scenario",
                    "Protocol",
                    "FND (round)",
                    "HND (round)",
                    "LND (round)",
                    "Energy / reading (mJ)",
                    "Orphan nodes",
                    "Intra-cluster distance (m)",
                ),
                metric_rows,
            ),
            (
                "Highway current-default ablation: change from full objective",
                ("Radio model", "Dropped term", "FND Δ", "Energy/read Δ", "Intra-distance Δ"),
                ablation_rows,
            ),
        ),
    )
    return {
        "files": [filename],
        "sources": _source_names(source_keys),
        "derived_metrics": ["orphan fraction × 100", "stored current-default ablation deltas"],
        "seed_information": seed_map,
        "statistics": "Aggregate descriptive results; no reconstructed uncertainty.",
    }


def _table_module2(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = ("module2_urban", "radio_freeride_urban")
    rows = sorted(_parse_composite(data["module2_urban"]), key=lambda item: (item[0], MODULE2_PROTOCOLS.index(item[1])))
    security_rows = []
    for fraction, protocol, record in rows:
        trust_enabled = protocol == "CHIRP + trust"
        attack_present = fraction > 0.0
        security_rows.append(
            (
                _fmt_pct(fraction * 100.0, 0),
                protocol,
                _fmt(record["pdr"], 3),
                _fmt_fraction_pct(record["att_ch_share"], 1),
                _fmt_fraction_pct(record["att_ch_late"], 1),
                _fmt(record["detect"], 3) if trust_enabled and attack_present else "—",
                _fmt(record["fpr"], 3) if trust_enabled else "—",
                _fmt(record["ttd"], 2) if trust_enabled and attack_present else "—",
                _fmt(record["e_adv"], 2) if attack_present else "—",
            )
        )

    radio = data["radio_freeride_urban"]
    sensitivity_rows = []
    arm_rows = {arm: _parse_composite(radio[arm]) for arm in ("heinzelman", "logdistance")}
    fractions = sorted(
        fraction
        for fraction, protocol, _ in arm_rows["heinzelman"]
        if protocol == "CHIRP + trust"
    )
    for fraction in fractions:
        values = {}
        for arm in arm_rows:
            values[arm] = next(
                record["e_adv"]
                for value, protocol, record in arm_rows[arm]
                if value == fraction and protocol == "CHIRP + trust"
            )
        sensitivity_rows.append(
            (
                _fmt_pct(fraction * 100.0, 0),
                _fmt(values["heinzelman"], 2),
                _fmt(values["logdistance"], 2),
            )
        )

    seeds = radio["_meta"]["seeds"]
    filename = "module2_trust_security_and_free_ride.md"
    _write_table_document(
        output_dir / filename,
        title="Module 2 trust/security metrics and attacker energy free ride",
        source_keys=source_keys,
        seed_information=f"urban: {seeds}",
        statistics="Aggregate means only; em dash denotes unavailable/not applicable, not zero.",
        derivations=(
            "attacker and CH-share fractions × 100 = percentages",
            "energy ratio is stored attacker mean residual energy / honest mean residual energy",
        ),
        sections=(
            (
                "Mixed Layer-A attack",
                (
                    "Attacker nodes",
                    "Protocol",
                    "PDR",
                    "Attacker CH share",
                    "Attacker late share",
                    "Detection",
                    "FPR",
                    "TTD (rounds)",
                    "Attacker / honest residual energy",
                ),
                security_rows,
            ),
            (
                "CHIRP + trust free ride under both radio models",
                ("Attacker nodes", "Heinzelman ratio", "Log-distance ratio"),
                sensitivity_rows,
            ),
        ),
    )
    return {
        "files": [filename],
        "sources": _source_names(source_keys),
        "derived_metrics": ["fractions × 100 for percentage columns"],
        "seed_information": {"urban": seeds},
        "statistics": "Aggregate means only; no new significance test.",
    }


def _headline_fraction(radio: dict[str, Any], arm: str) -> float:
    headline = radio[arm]["_headline"]
    matches = []
    rows = _parse_composite(radio[arm])
    for fraction in sorted({value for value, _, _ in rows}):
        records = {
            category: record
            for value, category, record in rows
            if value == fraction
        }
        if (
            records["none"]["ems_miss"] == headline["none_miss"]
            and records["auth"]["ems_miss"] == headline["auth_miss"]
        ):
            matches.append(fraction)
    if len(matches) != 1:
        raise ValueError(f"could not identify unique headline attack fraction for {arm}")
    return matches[0]


def _table_priority(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "priority_bypass_urban",
        "priority_bypass_highway",
        "priority_defence_urban",
        "priority_defence_highway",
        "radio_bypass_urban",
        "radio_bypass_highway",
        "radio_defence_urban",
        "radio_defence_highway",
    )
    bypass_rows = []
    for scenario in SCENARIOS:
        records = data[f"priority_bypass_{scenario}"]
        for key, record in records.items():
            protocol, bypass = key.split("|", 1)
            bypass_rows.append(
                (
                    scenario.title(),
                    protocol,
                    bypass,
                    _fmt(record["mJ_per_reading"], 4),
                    _fmt(record["ems_delay"], 2),
                    _fmt(record["ems_p95"], 2),
                    _fmt(record["ems_miss"], 3),
                )
            )

    headline_rows = []
    for scenario in SCENARIOS:
        radio = data[f"radio_defence_{scenario}"]
        fraction = _headline_fraction(radio, "heinzelman")
        records = {
            category: record
            for value, category, record in _parse_composite(data[f"priority_defence_{scenario}"])
            if value == fraction
        }
        headline = radio["heinzelman"]["_headline"]
        for defence in DEFENCES:
            record = records[defence]
            headline_rows.append(
                (
                    scenario.title(),
                    _fmt_pct(fraction * 100.0, 0),
                    DEFENCE_LABELS[defence],
                    _fmt(record["ems_miss"], 3),
                    _fmt_pct(record["drain_pct"], 2),
                    _fmt(record["detect"], 3),
                    _fmt(record["fpr"], 3),
                    headline["auth_zero_seeds"] if defence == "auth" else "—",
                    _fmt_p(headline["p"]) if defence == "auth" else "—",
                )
            )

    seed_map = {
        scenario: data[f"radio_defence_{scenario}"]["_meta"]["seeds"]
        for scenario in SCENARIOS
    }
    filename = "priority_bypass_and_dos_defence.md"
    _write_table_document(
        output_dir / filename,
        title="Priority bypass and DoS-defence headline results",
        source_keys=source_keys,
        seed_information=_fmt_seed_info(seed_map),
        statistics=(
            "Aggregate means. The paired p-value and all-zero seed count are read from "
            "the committed radio headline; no new test is computed."
        ),
        derivations=(
            "headline attacker fraction is located by matching stored none/auth headline values",
        ),
        sections=(
            (
                "Priority bypass without attackers",
                (
                    "Scenario",
                    "Protocol",
                    "Bypass",
                    "Energy / reading (mJ)",
                    "EMS delay (slots)",
                    "EMS p95 (slots)",
                    "Deadline-miss fraction",
                ),
                bypass_rows,
            ),
            (
                "False-priority DoS headline",
                (
                    "Scenario",
                    "Attacker nodes",
                    "Admission defence",
                    "Deadline miss",
                    "False-priority drain",
                    "Detection",
                    "FPR",
                    "Auth zero-miss seeds",
                    "Stored none-vs-auth p",
                ),
                headline_rows,
            ),
        ),
    )
    return {
        "files": [filename],
        "sources": _source_names(source_keys),
        "derived_metrics": ["headline fraction matched from stored headline values"],
        "seed_information": seed_map,
        "statistics": "Stored paired p-value only; other values are aggregate means.",
    }


def _table_crypto(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "crypto_bench",
        "priority_cryptodecomp_urban",
        "priority_cryptodecomp_highway",
    )
    crypto = data["crypto_bench"]
    size_rows = (
        ("Pseudonym certificate", _fmt(crypto["sizes"]["cert_total"], 0), "bytes", "serialized size"),
        ("ECDSA raw signature", _fmt(crypto["sizes"]["sig_raw"], 0), "bytes", "serialized size"),
        ("ECDSA DER signature", _fmt(crypto["sizes"]["sig_der"], 0), "bytes", "serialized size"),
        ("Compressed public key DER", _fmt(crypto["sizes"]["pub_compressed_der"], 0), "bytes", "serialized size"),
        ("Signature + certificate digest", _fmt(crypto["sig_bits_digest"], 0), "bits", "simulator overhead"),
        ("Signature + full certificate", _fmt(crypto["sig_bits_full_cert"], 0), "bits", "alternative overhead"),
        ("Aggregate MAC", _fmt(crypto["mac_bits"], 0), "bits", "simulator overhead"),
        ("ECDSA sign", _fmt(crypto["ecdsa"]["sign_us"], 2), "µs", "measured benchmark mean"),
        ("ECDSA verify", _fmt(crypto["ecdsa"]["verify_us"], 2), "µs", "measured benchmark mean"),
        (
            f"MAC over {crypto['mac']['packet_bytes']} bytes",
            _fmt(crypto["mac"]["mac_us"], 3),
            "µs",
            "measured benchmark mean",
        ),
    )

    decomp_rows = []
    for scenario in SCENARIOS:
        records = data[f"priority_cryptodecomp_{scenario}"]
        for stage, record in records.items():
            decomp_rows.append(
                (
                    scenario.title(),
                    stage,
                    _fmt(record["mJ_per_reading"], 4),
                    _fmt_pct(record.get("delta_pct"), 3),
                    _fmt_pct(record.get("cumulative_pct"), 3),
                    _fmt_p(record.get("p")),
                    _fmt(record["sig_bits"], 0),
                    _fmt(record["mac_bits"], 0),
                    _fmt(record["emergency_slots"], 0),
                )
            )

    filename = "crypto_sizes_timings_and_transmission.md"
    _write_table_document(
        output_dir / filename,
        title="Crypto sizes, timings and transmission decomposition",
        source_keys=source_keys,
        seed_information=(
            "benchmark is not seed-based; crypto-decomposition seed count is not encoded "
            "in its committed JSON, so none is added here"
        ),
        statistics=(
            "Benchmark point estimates and aggregate decomposition means. Decomposition "
            "p-values are stored in the source artifacts."
        ),
        derivations=(),
        sections=(
            ("Measured sizes and timings", ("Item", "Value", "Unit", "Interpretation"), size_rows),
            (
                "Transmission-energy decomposition",
                (
                    "Scenario",
                    "Cumulative stage",
                    "Energy / reading (mJ)",
                    "Step Δ",
                    "Cumulative Δ",
                    "Stored p",
                    "Signature bits",
                    "MAC bits",
                    "Emergency slots",
                ),
                decomp_rows,
            ),
        ),
    )
    return {
        "files": [filename],
        "sources": _source_names(source_keys),
        "derived_metrics": [],
        "seed_information": {"crypto decomposition": "not encoded in source JSON"},
        "statistics": "Stored benchmark means and paired p-values only.",
    }


def _sign(value: float) -> int:
    return (value > 0.0) - (value < 0.0)


def _pair_order_changes(left: Sequence[str], right: Sequence[str]) -> int:
    """Count protocol pairs whose relative energy ordering changes."""

    left_position = {name: index for index, name in enumerate(left)}
    right_position = {name: index for index, name in enumerate(right)}
    changes = 0
    for index, first in enumerate(left):
        for second in left[index + 1 :]:
            left_direction = left_position[first] - left_position[second]
            right_direction = right_position[first] - right_position[second]
            changes += int(left_direction * right_direction < 0)
    return changes


def _table_radio_verdict(
    data: dict[str, dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
    source_keys = (
        "radio_coverage_urban",
        "radio_coverage_highway",
        "radio_defence_urban",
        "radio_defence_highway",
        "radio_freeride_urban",
        "radio_greed_urban",
        "radio_greed_highway",
        "radio_module1_urban",
        "radio_module1_highway",
        "radio_ablation_highway",
        "radio_crypto",
        "radio_bypass_urban",
        "radio_bypass_highway",
    )
    verdict_rows = []

    coverage_values = {
        arm: {
            scenario: data[f"radio_coverage_{scenario}"][arm]["_spearman"]
            for scenario in SCENARIOS
        }
        for arm in ("heinzelman", "logdistance")
    }
    coverage_held = all(
        result["rho"] < 0.0
        for arm in coverage_values.values()
        for result in arm.values()
    )
    verdict_rows.append(
        (
            "1. Coverage vs deadline",
            "; ".join(
                f"{scenario}: ρ={_fmt(coverage_values['heinzelman'][scenario]['rho'], 3)}, "
                f"p={_fmt_p(coverage_values['heinzelman'][scenario]['p'])}"
                for scenario in SCENARIOS
            ),
            "; ".join(
                f"{scenario}: ρ={_fmt(coverage_values['logdistance'][scenario]['rho'], 3)}, "
                f"p={_fmt_p(coverage_values['logdistance'][scenario]['p'])}"
                for scenario in SCENARIOS
            ),
            "Held" if coverage_held else "Moved",
        )
    )

    defence_values = {
        arm: {
            scenario: data[f"radio_defence_{scenario}"][arm]["_headline"]
            for scenario in SCENARIOS
        }
        for arm in ("heinzelman", "logdistance")
    }
    defence_held = all(
        result["auth_miss"] == 0.0 and result["none_miss"] > result["auth_miss"]
        for arm in defence_values.values()
        for result in arm.values()
    )
    verdict_rows.append(
        (
            "2. Priority DoS and authorisation",
            "; ".join(
                f"{scenario}: {_fmt(defence_values['heinzelman'][scenario]['none_miss'])} → "
                f"{_fmt(defence_values['heinzelman'][scenario]['auth_miss'])}"
                for scenario in SCENARIOS
            ),
            "; ".join(
                f"{scenario}: {_fmt(defence_values['logdistance'][scenario]['none_miss'])} → "
                f"{_fmt(defence_values['logdistance'][scenario]['auth_miss'])}"
                for scenario in SCENARIOS
            ),
            "Held" if defence_held else "Moved",
        )
    )

    freeride = data["radio_freeride_urban"]
    free_values = {
        arm: freeride[arm]["_headline"] for arm in ("heinzelman", "logdistance")
    }
    free_held = all(value["e_adv_min"] > 1.0 for value in free_values.values())
    free_stronger = (
        free_values["logdistance"]["e_adv_min"] > free_values["heinzelman"]["e_adv_min"]
        and free_values["logdistance"]["e_adv_max"] > free_values["heinzelman"]["e_adv_max"]
    )
    verdict_rows.append(
        (
            "3. Trust-demotion free ride",
            f"ratio range {_fmt(free_values['heinzelman']['e_adv_min'], 2)}–{_fmt(free_values['heinzelman']['e_adv_max'], 2)}",
            f"ratio range {_fmt(free_values['logdistance']['e_adv_min'], 2)}–{_fmt(free_values['logdistance']['e_adv_max'], 2)}",
            "Held; stronger" if free_held and free_stronger else ("Held" if free_held else "Moved"),
        )
    )

    greed_values = {
        arm: {
            scenario: data[f"radio_greed_{scenario}"][arm]["_headline"]
            for scenario in SCENARIOS
        }
        for arm in ("heinzelman", "logdistance")
    }
    greed_damage_auth_held = all(
        value["auth_miss_at_stealth"] == 0.0 and value["stealth_damage_frac"] > 0.0
        for arm in greed_values.values()
        for value in arm.values()
    )
    greed_detect_at_or_below_fpr = all(
        value["stealth_detect"] <= value["stealth_fpr"]
        for arm in greed_values.values()
        for value in arm.values()
    )
    if greed_damage_auth_held and greed_detect_at_or_below_fpr:
        greed_verdict = "Held"
    elif greed_damage_auth_held:
        greed_verdict = "Damage/auth held; detect≤FPR not universal"
    else:
        greed_verdict = "Moved"
    verdict_rows.append(
        (
            "4. Greed/stealth",
            "; ".join(
                f"{scenario}: damage={_fmt_fraction_pct(greed_values['heinzelman'][scenario]['stealth_damage_frac'])}, "
                f"detect/FPR={_fmt(greed_values['heinzelman'][scenario]['stealth_detect'], 3)}/"
                f"{_fmt(greed_values['heinzelman'][scenario]['stealth_fpr'], 3)}"
                for scenario in SCENARIOS
            ),
            "; ".join(
                f"{scenario}: damage={_fmt_fraction_pct(greed_values['logdistance'][scenario]['stealth_damage_frac'])}, "
                f"detect/FPR={_fmt(greed_values['logdistance'][scenario]['stealth_detect'], 3)}/"
                f"{_fmt(greed_values['logdistance'][scenario]['stealth_fpr'], 3)}"
                for scenario in SCENARIOS
            ),
            greed_verdict,
        )
    )

    module1_metrics = ("hnd", "mj_per_reading", "orphan", "intra")
    module1_values = {
        arm: {
            scenario: data[f"radio_module1_{scenario}"][arm]["_chirp_vs_csgd"]
            for scenario in SCENARIOS
        }
        for arm in ("heinzelman", "logdistance")
    }
    module1_held = all(
        _sign(module1_values["heinzelman"][scenario][metric]["delta_pct"])
        == _sign(module1_values["logdistance"][scenario][metric]["delta_pct"])
        for scenario in SCENARIOS
        for metric in module1_metrics
    )
    energy_orders = {
        arm: {
            scenario: tuple(
                sorted(
                    PROTOCOLS,
                    key=lambda protocol: data[f"radio_module1_{scenario}"][arm][protocol][
                        "mj_per_reading"
                    ],
                )
            )
            for scenario in SCENARIOS
        }
        for arm in ("heinzelman", "logdistance")
    }
    order_changes = {
        scenario: _pair_order_changes(
            energy_orders["heinzelman"][scenario],
            energy_orders["logdistance"][scenario],
        )
        for scenario in SCENARIOS
    }
    all_orders_identical = all(value == 0 for value in order_changes.values())
    if module1_held and all_orders_identical:
        module1_verdict = "Held"
    elif module1_held:
        module1_verdict = "Headline held; full ordering moved"
    else:
        module1_verdict = "Moved"
    verdict_rows.append(
        (
            "5a. Module 1 protocol comparison",
            "; ".join(
                f"{scenario}: HND {_fmt_pct(module1_values['heinzelman'][scenario]['hnd']['delta_pct'], 1)}, "
                f"energy {_fmt_pct(module1_values['heinzelman'][scenario]['mj_per_reading']['delta_pct'], 1)}"
                for scenario in SCENARIOS
            ),
            "; ".join(
                f"{scenario}: HND {_fmt_pct(module1_values['logdistance'][scenario]['hnd']['delta_pct'], 1)}, "
                f"energy {_fmt_pct(module1_values['logdistance'][scenario]['mj_per_reading']['delta_pct'], 1)}, "
                f"energy-order pair changes {order_changes[scenario]}"
                for scenario in SCENARIOS
            ),
            module1_verdict,
        )
    )

    ablation = data["radio_ablation_highway"]
    ablation_values = {
        arm: ablation[arm]["_deltas"] for arm in ("heinzelman", "logdistance")
    }
    ablation_held = all(
        (
            values["w_energy"]["fnd_pct"] < 0.0
            and values["w_intra"]["mj_pct"] > 0.0
            and values["w_intra"]["intra_pct"] > 0.0
        )
        for values in ablation_values.values()
    )
    verdict_rows.append(
        (
            "5b. Current-default ablation",
            f"drop energy FND {_fmt_pct(ablation_values['heinzelman']['w_energy']['fnd_pct'], 1)}; "
            f"drop intra energy/intra {_fmt_pct(ablation_values['heinzelman']['w_intra']['mj_pct'], 1)}/"
            f"{_fmt_pct(ablation_values['heinzelman']['w_intra']['intra_pct'], 1)}",
            f"drop energy FND {_fmt_pct(ablation_values['logdistance']['w_energy']['fnd_pct'], 1)}; "
            f"drop intra energy/intra {_fmt_pct(ablation_values['logdistance']['w_intra']['mj_pct'], 1)}/"
            f"{_fmt_pct(ablation_values['logdistance']['w_intra']['intra_pct'], 1)}",
            "Held" if ablation_held else "Moved",
        )
    )

    crypto = data["radio_crypto"]
    hein_break = crypto["heinzelman"]["break_even_m"]
    log_models = [key for key in crypto if key.startswith("logdistance")]
    log_breaks = [crypto[key]["break_even_m"] for key in log_models]
    crypto_held = all(value > hein_break for value in log_breaks)
    verdict_rows.append(
        (
            "6. Crypto compute vs radio",
            f"break-even {_fmt(hein_break, 1)} m",
            "; ".join(
                f"{_radio_label(model)} {_fmt(crypto[model]['break_even_m'], 1)} m"
                for model in log_models
            ),
            "Held; stronger" if crypto_held else "Moved",
        )
    )

    bypass_values = {
        arm: {
            scenario: {
                protocol: data[f"radio_bypass_{scenario}"][arm][f"_cost_{protocol}"]
                for protocol in ("CSGD-NET", "CHIRP")
            }
            for scenario in SCENARIOS
        }
        for arm in ("heinzelman", "logdistance")
    }
    premium_shrinks = all(
        abs(
            bypass_values["logdistance"]["urban"][protocol]
            - bypass_values["logdistance"]["highway"][protocol]
        )
        < abs(
            bypass_values["heinzelman"]["urban"][protocol]
            - bypass_values["heinzelman"]["highway"][protocol]
        )
        for protocol in ("CSGD-NET", "CHIRP")
    )
    verdict_rows.append(
        (
            "Moved explanation: urban bypass premium",
            "; ".join(
                f"{protocol}: urban/highway {_fmt_pct(bypass_values['heinzelman']['urban'][protocol], 2)}/"
                f"{_fmt_pct(bypass_values['heinzelman']['highway'][protocol], 2)}"
                for protocol in ("CSGD-NET", "CHIRP")
            ),
            "; ".join(
                f"{protocol}: urban/highway {_fmt_pct(bypass_values['logdistance']['urban'][protocol], 2)}/"
                f"{_fmt_pct(bypass_values['logdistance']['highway'][protocol], 2)}"
                for protocol in ("CSGD-NET", "CHIRP")
            ),
            "Explanation moved; conclusion held" if premium_shrinks else "Review required",
        )
    )

    seed_map = {
        "coverage": data["radio_coverage_urban"]["_meta"]["seeds"],
        "defence/free ride/greed": data["radio_defence_urban"]["_meta"]["seeds"],
        "Module 1": data["radio_module1_urban"]["_meta"]["seeds"],
        "ablation": data["radio_ablation_highway"]["_meta"]["seeds"],
        "crypto": "analytic from benchmark assumptions",
    }
    filename = "radio_robustness_verdict.md"
    _write_table_document(
        output_dir / filename,
        title="Radio-robustness verdicts",
        source_keys=source_keys,
        seed_information=_fmt_seed_info(seed_map),
        statistics=(
            "Stored correlations, p-values, headlines and deltas are reported. Verdicts are "
            "derived from direction/zero-crossing checks documented below, not new tests."
        ),
        derivations=(
            "coverage held when stored rho is negative in every scenario/model",
            "DoS held when authorisation miss is zero and below no-defence miss",
            "free ride held when attacker/honest energy ratio remains above one",
            "greed damage/auth held when stealth damage remains positive and authorisation miss remains zero; detect≤FPR is checked separately and without an inferential claim",
            "Module 1 headline held when HND, energy, orphan and intra deltas keep direction; full energy ordering is separately compared pairwise",
            "ablation held when energy-drop FND remains negative and intra-drop energy/intra deltas remain positive",
            "crypto stronger when each log-distance break-even exceeds Heinzelman",
            "urban-premium explanation moved when the urban/highway bypass-cost gap shrinks for both protocols",
        ),
        sections=(
            (
                "Six findings and the moved explanation",
                ("Finding", "Heinzelman evidence", "Log-distance evidence", "Derived verdict"),
                verdict_rows,
            ),
        ),
    )
    return {
        "files": [filename],
        "sources": _source_names(source_keys),
        "derived_metrics": [
            "verdict rules are listed in the generated table; greed damage/auth and detect≤FPR are evaluated separately",
            "no result number is introduced outside the source artifacts",
        ],
        "seed_information": seed_map,
        "statistics": "Stored statistics and direction checks only.",
    }


def _write_readme(
    path: Path,
    *,
    title: str,
    entries: dict[str, dict[str, Any]],
    output_kind: str,
) -> None:
    rows = []
    for name, entry in entries.items():
        rows.append(
            (
                name,
                ", ".join(f"`{value}`" for value in entry["files"]),
                ", ".join(f"`{value}`" for value in entry["sources"]),
                "; ".join(entry["derived_metrics"]) or "None",
                _fmt_seed_info(entry["seed_information"]),
                entry["statistics"],
            )
        )
    lines = [
        f"# {title}",
        "",
        f"Regenerate every {output_kind} with:",
        "",
        "```bash",
        GENERATOR_COMMAND,
        "```",
        "",
        "The generator reads only committed, unmodified JSON result artifacts. It does not",
        "run experiments or use numbers from documentation or the base-paper PDF.",
        "",
        _markdown_table(
            ("Item", "Outputs", "Source JSON", "Derived calculations", "Seed information", "Statistical scope"),
            rows,
        ),
        "",
        "## Boundaries and gaps",
        "",
        "- All non-baseline simulation outputs shown here are aggregate/descriptive unless a stored statistic is explicitly named.",
        "- No confidence interval is reconstructed from aggregate means.",
        "- The crypto-decomposition JSON does not encode its seed count; the generated output leaves it unspecified.",
        "- No formal-verification table is generated because no committed machine-readable Scyther result artifact exists.",
        "- No Module 4 result is generated; Module 4 remains Deferred / Future Work.",
        "- Base-paper Figures 11–15 remain separately generated in `figures/baseline/`.",
        "",
        "`manifest.json` records source hashes, formulas, seed metadata and output hashes.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _write_manifest(
    path: Path,
    *,
    kind: str,
    entries: dict[str, dict[str, Any]],
) -> None:
    source_names = sorted({source for entry in entries.values() for source in entry["sources"]})
    output_names = sorted(
        {name for entry in entries.values() for name in entry["files"]} | {"README.md"}
    )
    manifest = {
        "generated_by": GENERATOR_COMMAND,
        "source_policy": (
            "Every numerical value is read from a committed, unmodified JSON result "
            "artifact or mathematically derived from such values."
        ),
        "sources": {
            name: _sha256(ROOT / name)
            for name in source_names
        },
        kind: entries,
        "outputs": {
            name: _sha256(path.parent / name)
            for name in output_names
        },
        "excluded": {
            "formal_verification_table": (
                "not generated: no committed machine-readable Scyther result artifact"
            ),
            "module4": "not generated: Deferred / Future Work",
            "baseline_figures_11_15": "unchanged; generated separately in figures/baseline",
        },
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate final BTP presentation outputs from committed JSON artifacts."
    )
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURE_DIR)
    parser.add_argument("--table-dir", type=Path, default=DEFAULT_TABLE_DIR)
    args = parser.parse_args()

    data = _load_sources()
    _validate_sources(data)
    args.figure_dir.mkdir(parents=True, exist_ok=True)
    args.table_dir.mkdir(parents=True, exist_ok=True)

    figures = {
        "Module 1 protocol comparison": _figure_module1(data, args.figure_dir),
        "Module 2 trust/security and free ride": _figure_module2(data, args.figure_dir),
        "Priority coverage/deadline": _figure_priority_coverage(data, args.figure_dir),
        "Priority abuse/defence": _figure_priority_abuse(data, args.figure_dir),
        "Crypto/radio robustness": _figure_crypto_radio(data, args.figure_dir),
    }
    tables = {
        "Module 1 metrics and ablation": _table_module1(data, args.table_dir),
        "Module 2 trust/security and free ride": _table_module2(data, args.table_dir),
        "Priority bypass and DoS defence": _table_priority(data, args.table_dir),
        "Crypto sizes, timings and decomposition": _table_crypto(data, args.table_dir),
        "Radio robustness verdicts": _table_radio_verdict(data, args.table_dir),
    }

    _write_readme(
        args.figure_dir / "README.md",
        title="Final BTP result figures",
        entries=figures,
        output_kind="figure",
    )
    _write_readme(
        args.table_dir / "README.md",
        title="Final BTP result tables",
        entries=tables,
        output_kind="table",
    )
    _write_manifest(
        args.figure_dir / "manifest.json",
        kind="figures",
        entries=figures,
    )
    _write_manifest(
        args.table_dir / "manifest.json",
        kind="tables",
        entries=tables,
    )

    print("Presentation-only generation complete; no experiment runner was invoked.")
    for title, entry in figures.items():
        print(f"figure: {title}: {', '.join(entry['files'])}")
    for title, entry in tables.items():
        print(f"table: {title}: {', '.join(entry['files'])}")
    print(f"figure manifest: {args.figure_dir / 'manifest.json'}")
    print(f"table manifest: {args.table_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
