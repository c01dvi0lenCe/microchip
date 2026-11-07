"""Simulation-only paired batches with seed-level, not frame-level inference.

Early updates are divided by *all* prescribed transport steps. Their interval
resamples entire seeds and recomputes the ratio; steps within a seed are not
treated as independent Bernoulli trials. Completion uses a trial-level Wilson
interval. Confirmation delays condition on observed confirmations; absent
values and unconfirmed steps are reported rather than replaced with zeros.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import csv
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping


METHODS = ("A", "B", "C")
CONTINUOUS_METRICS = ("total_time_s", "retries", "recoveries", "confirmation_delay_s")
BOOTSTRAP_SEED = 20261020


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"Not a finite JSON value: {type(value).__name__}")


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    low = int(location)
    high = math.ceil(location)
    return ordered[low] + (ordered[high] - ordered[low]) * (location - low)


def _bootstrap(items: list[Any], statistic: Callable[[list[Any]], float | None],
               repeats: int, key: str) -> tuple[float | None, float | None]:
    if repeats < 1:
        raise ValueError("bootstrap_repeats must be positive")
    if not items:
        return None, None
    # A private RNG cannot consume or perturb any physics/camera random stream.
    digest = hashlib.sha256(f"{BOOTSTRAP_SEED}:{key}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    estimates = []
    for _ in range(repeats):
        estimate = statistic([items[rng.randrange(len(items))] for _ in items])
        if estimate is not None:
            estimates.append(float(estimate))
    return _percentile(estimates, 0.025), _percentile(estimates, 0.975)


def _wilson(successes: int, count: int) -> tuple[float | None, float | None]:
    if not count:
        return None, None
    z = 1.959963984540054
    p = successes / count
    divisor = 1 + z * z / count
    midpoint = (p + z * z / (2 * count)) / divisor
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / divisor
    return max(0.0, midpoint - radius), min(1.0, midpoint + radius)


def _checked_trials(trials: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in trials]
    seen = set()
    for row in rows:
        identity = (row["scenario"], row["method"], row["seed"])
        if identity in seen:
            raise ValueError(f"Duplicate scenario/method/seed: {identity}")
        seen.add(identity)
        if row.get("simulation") is not True:
            raise ValueError("Batch statistics accept simulation=True trials only")
        if row["method"] not in METHODS:
            raise ValueError("Unknown comparison method")
    return sorted(rows, key=lambda row: (str(row["scenario"]), str(row["method"]), row["seed"]))


def _early_ratio(rows: list[Mapping[str, Any]]) -> float | None:
    denominator = sum(row["transport_steps"] for row in rows)
    return sum(row["early_updates"] for row in rows) / denominator if denominator else None


def _issued_early_ratio(rows: list[Mapping[str, Any]]) -> float | None:
    denominator = sum(row["confirmed_steps"] for row in rows)
    return sum(row["early_updates"] for row in rows) / denominator if denominator else None


def summarize_trials(trials: Iterable[Mapping[str, Any]], *,
                     bootstrap_repeats: int = 2000) -> list[dict[str, Any]]:
    """Aggregate one independent observation per scenario/method/seed."""
    if bootstrap_repeats < 1:
        raise ValueError("bootstrap_repeats must be positive")
    groups = defaultdict(list)
    for row in _checked_trials(trials):
        groups[(row["scenario"], row["method"])].append(row)
    summaries = []
    for (scenario, method), rows in sorted(groups.items()):
        key = f"{scenario}:{method}"
        count = len(rows)
        completed = sum(bool(row["path_complete"]) for row in rows)
        summary = dict(simulation=True, scenario=scenario, method=method,
                       n_trials=count, n_seeds=count, path_complete_count=completed,
                       path_complete_rate=completed / count,
                       path_complete_rate_ci_method="wilson_95",
                       early_updates=sum(row["early_updates"] for row in rows),
                       transport_steps=sum(row["transport_steps"] for row in rows),
                       early_update_rate=_early_ratio(rows),
                       early_update_rate_ci_method="seed_cluster_bootstrap_ratio",
                       issued_updates=sum(row["confirmed_steps"] for row in rows),
                       issued_updates_note="controller advances; A is timer-based, not visual confirmation",
                       early_update_rate_per_issued_update=_issued_early_ratio(rows),
                       early_update_rate_per_issued_update_ci_method="seed_cluster_bootstrap_ratio",
                       bootstrap_repeats=bootstrap_repeats)
        summary["path_complete_rate_ci_low"], summary["path_complete_rate_ci_high"] = _wilson(completed, count)
        summary["early_update_rate_ci_low"], summary["early_update_rate_ci_high"] = _bootstrap(
            rows, _early_ratio, bootstrap_repeats, key + ":early")
        summary["early_update_rate_per_issued_update_ci_low"], summary["early_update_rate_per_issued_update_ci_high"] = _bootstrap(
            rows, _issued_early_ratio, bootstrap_repeats, key + ":early_per_issued")
        for metric in CONTINUOUS_METRICS:
            values = [float(row[metric]) for row in rows if row.get(metric) is not None]
            summary[metric + "_n"] = len(values)
            summary[metric + "_mean"] = statistics.fmean(values) if values else None
            summary[metric + "_ci_low"], summary[metric + "_ci_high"] = _bootstrap(
                values, statistics.fmean, bootstrap_repeats, key + ":" + metric)
            summary[metric + "_ci_method"] = "seed_bootstrap_mean"
        summary["confirmation_delay_s_missing_trials"] = count - summary["confirmation_delay_s_n"]
        summary["confirmation_delay_s_confirmed_steps"] = sum(row["confirmed_steps"] for row in rows)
        summary["confirmation_delay_s_unconfirmed_steps"] = sum(
            max(0, row["transport_steps"] - row["confirmed_steps"]) for row in rows)
        summary["confirmation_delay_s_observed_steps"] = sum(
            row.get("delay_observed_steps", row["confirmed_steps"]) for row in rows)
        summary["confirmation_delay_s_missing_steps"] = sum(
            row.get("delay_missing_steps", max(0, row["transport_steps"] - row["confirmed_steps"]))
            for row in rows)
        # Older trial schemas do not distinguish these reasons. Leave unknown
        # rather than silently claiming that no right-censoring occurred.
        for reason in ("censored", "no_arrival", "unattempted"):
            source = "delay_" + reason + "_steps"
            summary["confirmation_delay_s_" + reason + "_steps"] = (
                sum(row[source] for row in rows) if all(source in row for row in rows) else None)
        summary["confirmation_delay_s_estimand"] = "mean_of_observed_seed_means_conditional_on_confirmation"
        summary["confirmation_delay_s_censoring_note"] = (
            "unconfirmed steps include absent arrivals and unconfirmed arrivals; not imputed")
        summaries.append(summary)
    return summaries


def paired_differences(trials: Iterable[Mapping[str, Any]], *,
                       bootstrap_repeats: int = 2000) -> list[dict[str, Any]]:
    """Mean within-seed differences, with missing pairs explicitly counted."""
    rows = _checked_trials(trials)
    groups = defaultdict(dict)
    for row in rows:
        groups[row["scenario"]][(row["seed"], row["method"])] = row
    output = []
    metrics = CONTINUOUS_METRICS + ("path_complete", "early_update_rate")
    for scenario, indexed in sorted(groups.items()):
        seeds = sorted({seed for seed, _ in indexed})
        for later, earlier in (("B", "A"), ("C", "A"), ("C", "B")):
            for metric in metrics:
                differences = []
                for seed in seeds:
                    left = indexed.get((seed, later))
                    right = indexed.get((seed, earlier))
                    if left is None or right is None:
                        continue
                    a = _early_ratio([left]) if metric == "early_update_rate" else left.get(metric)
                    b = _early_ratio([right]) if metric == "early_update_rate" else right.get(metric)
                    if a is not None and b is not None:
                        differences.append(float(a) - float(b))
                comparison = later + "-" + earlier
                low, high = _bootstrap(differences, statistics.fmean, bootstrap_repeats,
                                       f"paired:{scenario}:{comparison}:{metric}")
                output.append(dict(simulation=True, scenario=scenario,
                                   comparison=comparison, metric=metric,
                                   n_pairs=len(differences), missing_pairs=len(seeds) - len(differences),
                                   mean_difference=statistics.fmean(differences) if differences else None,
                                   ci_low=low, ci_high=high, ci_method="paired_seed_bootstrap_mean",
                                   bootstrap_repeats=bootstrap_repeats,
                                   estimand="mean_within_seed_difference"))
    return output


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_json_safe(value), ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    if not keys:
        keys = ["simulation", "scenario", "seed", "method"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            safe = _json_safe(row)
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
                             else value for key, value in safe.items()})


def _snapshot_geometry(config: Any, output: Path) -> None:
    from .config import SimConfig
    if isinstance(config, SimConfig):
        from .geometry import SimulationMap
        _write_json(output / "electrode_map_snapshot.json",
                    dict(SimulationMap(config).snapshot(), simulation=True))


def _manifest(config: Any, scenarios: list[str], seeds: list[int], output: Path,
              bootstrap_repeats: int, kind: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    files = [path for path in Path(__file__).parent.rglob("*")
             if path.is_file() and "__pycache__" not in path.parts]
    files += list(root.glob("*chapter2*sim*.py"))
    files += [root / "dmf" / "vision" / name for name in (
        "calibration.py", "config.py", "electrode_map.py")]
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(set(files))}
    try:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=5, check=False)
        git_head = git.stdout.strip() if git.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        git_head = None
    # cv2 can be provided by any of these distributions. Keep their actual
    # distribution names, recording missing metadata as null rather than 0.
    package_versions = {}
    for package in ("numpy", "opencv-python", "opencv-python-headless",
                    "opencv-contrib-python", "opencv-contrib-python-headless",
                    "matplotlib", "PyYAML"):
        try:
            package_versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            package_versions[package] = None
    return dict(simulation=True, evidence_scope="synthetic causal algorithm simulation only",
                kind=kind, created_at_utc=datetime.now(timezone.utc).isoformat(),
                config=_json_safe(config), scenarios=scenarios, seeds=seeds,
                methods=list(METHODS) if kind == "comparison" else ["C"],
                seed_count=len(seeds), recommended_min_seeds=20,
                meets_recommended_seed_count=len(seeds) >= 20,
                command=list(sys.argv), working_directory=str(Path.cwd()),
                output=str(output.resolve()), git_head=git_head, source_sha256=hashes,
                environment=dict(python=sys.version, executable=sys.executable,
                                 platform=platform.platform(), machine=platform.machine(),
                                 implementation=platform.python_implementation(),
                                 package_versions=package_versions,
                                 variables={key: os.environ[key] for key in (
                                     "PYTHONHASHSEED", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
                                     if key in os.environ}),
                bootstrap=dict(repeats=bootstrap_repeats, seed=BOOTSTRAP_SEED,
                               unit="seed", rng="private random.Random keyed by SHA256",
                               early_rate_ci="seed_cluster_bootstrap_ratio",
                               completion_ci="trial_level_wilson_95"),
                confirmation_delay_missing="retained; never replaced with zero")


def _inputs(scenarios: Iterable[str], seeds: Iterable[int]) -> tuple[list[str], list[int]]:
    scenarios = list(scenarios)
    seeds = list(seeds)
    if not scenarios or not seeds:
        raise ValueError("At least one scenario and seed are required")
    if len(set(scenarios)) != len(scenarios) or len(set(seeds)) != len(seeds):
        raise ValueError("Scenario and seed lists must be unique")
    return scenarios, seeds


def _runner(runner: Callable | None) -> Callable:
    if runner is None:
        from .runner import run_trial
        return run_trial
    return runner


def _tag_rows(rows: Iterable[Mapping[str, Any]], scenario: str, seed: int,
              method: str, **labels: Any) -> list[dict[str, Any]]:
    return [dict(row, simulation=True, scenario=scenario, seed=seed, method=method, **labels)
            for row in rows]


def run_batch(config: Any, scenarios: Iterable[str], seeds: Iterable[int], output: Path,
              *, runner: Callable | None = None,
              bootstrap_repeats: int = 2000) -> list[dict[str, Any]]:
    """Run matched A/B/C seeds and write an immutable, auditable output bundle."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite simulation output: {output}")
    if bootstrap_repeats < 1:
        raise ValueError("bootstrap_repeats must be positive")
    scenarios, seeds = _inputs(scenarios, seeds)
    execute = _runner(runner)
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "config_snapshot.json", dict(simulation=True, config=_json_safe(config)))
    _snapshot_geometry(config, output)
    trials, frames, truth, events = [], [], [], []
    for scenario in scenarios:
        for seed in seeds:
            for method in METHODS:
                result = execute(config, scenario, seed, method)
                trials.extend(_tag_rows([result.metrics], scenario, seed, method))
                frames.extend(_tag_rows(result.frames, scenario, seed, method))
                truth.extend(_tag_rows(result.truth, scenario, seed, method))
                events.extend(_tag_rows(result.events, scenario, seed, method))
    summary = summarize_trials(trials, bootstrap_repeats=bootstrap_repeats)
    for name, rows in (("trials", trials), ("frames", frames), ("truth", truth),
                       ("events", events), ("summary", summary),
                       ("paired_differences", paired_differences(trials, bootstrap_repeats=bootstrap_repeats))):
        _write_csv(output / (name + ".csv"), rows)
    _write_json(output / "summary.json", dict(simulation=True, groups=summary))
    manifest = _manifest(config, scenarios, seeds, output, bootstrap_repeats, "comparison")
    manifest["output_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(output.iterdir()) if p.is_file()}
    _write_json(output / "manifest.json", manifest)
    return summary


def run_sensitivity(config: Any, scenario: str, seeds: Iterable[int],
                    coverages: Iterable[float], durations: Iterable[float], output: Path,
                    *, runner: Callable | None = None,
                    bootstrap_repeats: int = 2000) -> list[dict[str, Any]]:
    """C-only threshold sweep; replace only the two observation-gate fields.

    The physics/ground-truth fields and matched environment seeds are unchanged.
    Closed-loop trajectories may differ because decisions legitimately differ.
    """
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite simulation output: {output}")
    if bootstrap_repeats < 1:
        raise ValueError("bootstrap_repeats must be positive")
    _, seeds = _inputs([scenario], seeds)
    coverages, durations = list(coverages), list(durations)
    if not coverages or not durations:
        raise ValueError("Sensitivity grids must not be empty")
    if len(set(coverages)) != len(coverages) or len(set(durations)) != len(durations):
        raise ValueError("Sensitivity grids must be unique")
    execute = _runner(runner)
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "config_snapshot.json", dict(simulation=True, config=_json_safe(config),
                arrival_coverages=coverages, stable_durations_s=durations))
    _snapshot_geometry(config, output)
    trials, summaries = [], []
    for coverage in coverages:
        for duration in durations:
            variant = replace(config, arrival_coverage=coverage, stable_duration_s=duration)
            group = []
            for seed in seeds:
                result = execute(variant, scenario, seed, "C")
                group.extend(_tag_rows([result.metrics], scenario, seed, "C",
                                       arrival_coverage=coverage, stable_duration_s=duration))
            trials.extend(group)
            summaries.extend(dict(row, arrival_coverage=coverage, stable_duration_s=duration)
                             for row in summarize_trials(group, bootstrap_repeats=bootstrap_repeats))
    _write_csv(output / "sensitivity_trials.csv", trials)
    _write_csv(output / "sensitivity_summary.csv", summaries)
    _write_json(output / "sensitivity_summary.json", dict(simulation=True, groups=summaries))
    manifest = _manifest(config, [scenario], seeds, output, bootstrap_repeats, "sensitivity")
    manifest.update(arrival_coverages=coverages, stable_durations_s=durations,
                    unchanged_fields="all config fields except arrival_coverage and stable_duration_s",
                    ground_truth="fixed independent physics criteria; never retuned to control thresholds")
    _write_json(output / "manifest.json", manifest)
    return summaries
