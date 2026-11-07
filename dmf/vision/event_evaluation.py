"""Independent, external human-reference event scoring (no control thresholds).

``evaluate_events(predictions, references, trial_manifest)`` accepts sequences of
mapping rows, not experiment CSVs. This is a strict, explicit adapter boundary:

* Manifest: ``trial_id``, ``task_id``, ``clock_domain`` (nonempty strings),
  ``eligible`` (bool), and ``step_ids`` (nonempty ordered list of unique int or
  string identifiers). The manifest MUST list all trials and all planned steps,
  including failed runs. Its completeness is the caller's audit responsibility.
* Reference: those three identity/clock fields, ``step_id``, ``status`` in
  arrived/not_arrived/uncertain/occluded/right_censored, nonnegative finite
  ``observation_start_s`` and ``observation_end_s``, ``annotation_source='human'``,
  ``reviewed=True`` (bool), and nonempty ``provenance`` (reviewer/source record).
  Arrived additionally requires finite ``arrival_lower_s <= arrival_upper_s``
  inside the observation window. Other statuses MUST leave these bounds empty.
  ``not_arrived`` explicitly asserts complete, interpretable observation of the
  entire step window; use occluded/uncertain/right_censored otherwise.
* Prediction: those identity/clock fields, ``step_id``, ``action`` in
  Update/Complete/Hold/Retry/Recovery/Start/Stop and finite nonnegative
  ``timestamp_s``. Only Update/Complete are arrival confirmations. Times must
  already be expressed in that trial's manifest clock; no conversion is guessed.

Every row must match a manifest trial, task, step and clock, even for excluded
trials. Multiple clocks across independent trials are fine; mixed clocks within
a trial are rejected. Predictions outside a reference observation window are
reported as unassessable (not invented negatives). No-event arrived references
are misses. Missing references retain the manifest denominator and uncertainty.

For human interval [L,U], t<L is definitely early, L<=t<=U is ambiguous when
L<U, and t>U is definitely after arrival with delay interval [t-U,t-L]. A point
interval allows exact zero delay. Duplicates are counted and flagged; the first
chronological confirmation is scored once and cannot be repaired by a later
event. Duplicate steps cannot complete a path. Completion requires every
planned step definitely confirmed after its known arrival, no missing/early/
ambiguous/duplicate event and no uncertain reference. Path completion rate uses
ALL eligible trials; a separate conditional rate labels its smaller denominator.
Confirmations must also be nondecreasing in manifest step order; a reversed
sequence is a failed recognition path even if individual steps look correct.

This module never generates formal GT, verifies reviewer identity, or supplies
physical evidence. Automated tests use synthetic software fixtures only.
"""
from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping, Sequence


REFERENCE_STATUSES = frozenset({"arrived", "not_arrived", "uncertain", "occluded", "right_censored"})
ACTIONS = frozenset({"Update", "Complete", "Hold", "Retry", "Recovery", "Start", "Stop"})


def _text(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an explicit nonempty string")
    return value


def _time(row, field):
    value = row.get(field)
    if isinstance(value, bool) or value is None or str(value).strip() == "":
        raise ValueError(f"{field} must be a finite nonnegative time")
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite nonnegative time")
    return value


def _step_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "":
        raise ValueError("step_id must be an explicit integer or nonempty string")
    return value


def _row_key(row, manifest):
    trial_id = _text(row, "trial_id")
    trial = manifest.get(trial_id)
    if trial is None:
        raise ValueError(f"unknown trial_id: {trial_id}")
    if _text(row, "task_id") != trial["task_id"]:
        raise ValueError(f"mismatched task_id for {trial_id}")
    if _text(row, "clock_domain") != trial["clock_domain"]:
        raise ValueError(f"mixed clock domains for {trial_id}; supply an explicit clock adapter")
    step = _step_id(row.get("step_id"))
    if step not in trial["step_ids"]:
        raise ValueError(f"unplanned step_id for {trial_id}: {step}")
    return trial_id, step


def evaluate_events(
    predictions: Sequence[Mapping[str, object]],
    references: Sequence[Mapping[str, object]],
    trial_manifest: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return JSON-compatible absolute counts, explicit denominators and rows."""
    return _evaluate_events(predictions, references, trial_manifest, reference_origin='human')


def evaluate_simulation_events(predictions, references, trial_manifest):
    """Score independent physical simulation intervals, never relabelled human.

    The counting/interval rules match the human evaluator. The independent
    world generator, not this function or any recognition threshold, supplies
    these references. Simulation and real clocks cannot be mixed.
    """
    if any(row.get('clock_domain') != 'simulation' for row in trial_manifest):
        raise ValueError('simulation references require an explicit simulation clock')
    result = _evaluate_events(predictions, references, trial_manifest, reference_origin='simulation_physics')
    return dict(result, simulation=True, reference_origin='simulation_physics')


def _evaluate_events(predictions, references, trial_manifest, *, reference_origin):
    manifest = {}
    for row in trial_manifest:
        trial_id = _text(row, "trial_id")
        if trial_id in manifest:
            raise ValueError(f"duplicate manifest trial_id: {trial_id}")
        _text(row, "task_id")
        _text(row, "clock_domain")
        if type(row.get("eligible")) is not bool:
            raise ValueError("manifest eligible must be an explicit bool")
        steps = row.get("step_ids")
        if not isinstance(steps, (list, tuple)) or not steps:
            raise ValueError("manifest step_ids must include every planned step")
        steps = [_step_id(step) for step in steps]
        if len(set(steps)) != len(steps):
            raise ValueError("duplicate manifest step_id")
        manifest[trial_id] = dict(row, step_ids=steps)

    truth_by_key = {}
    for row in references:
        key = _row_key(row, manifest)
        if key in truth_by_key:
            raise ValueError(f"duplicate reference: {key}")
        if reference_origin == 'human':
            if row.get("annotation_source") != "human" or row.get("reviewed") is not True or row.get('simulation') is True:
                raise ValueError("reference requires explicit human annotation_source and reviewed=True, not simulation")
        elif row.get('annotation_source') != 'simulation_physics' or row.get('simulation') is not True:
            raise ValueError('simulation reference requires simulation_physics origin and simulation=True')
        _text(row, "provenance")
        status = row.get("status")
        if status not in REFERENCE_STATUSES:
            raise ValueError(f"invalid human reference status: {status}")
        start, end = _time(row, "observation_start_s"), _time(row, "observation_end_s")
        if end < start:
            raise ValueError("observation interval is reversed")
        normalized = dict(row, observation_start_s=start, observation_end_s=end)
        if status == "arrived":
            lower, upper = _time(row, "arrival_lower_s"), _time(row, "arrival_upper_s")
            if not start <= lower <= upper <= end:
                raise ValueError("arrival interval must be ordered and inside the observation window")
            normalized.update(arrival_lower_s=lower, arrival_upper_s=upper)
        elif any(row.get(field) not in (None, "") for field in ("arrival_lower_s", "arrival_upper_s")):
            raise ValueError("non-arrival/uncertain reference must not fabricate an arrival interval")
        truth_by_key[key] = normalized

    events = defaultdict(list)
    ignored_actions = excluded_events = 0
    for row in predictions:
        key = _row_key(row, manifest)
        timestamp = _time(row, "timestamp_s")
        if row.get("action") not in ACTIONS:
            raise ValueError(f"invalid prediction action: {row.get('action')}")
        if row["action"] not in {"Update", "Complete"}:
            ignored_actions += 1
            continue
        if not manifest[key[0]]["eligible"]:
            excluded_events += 1
        events[key].append(timestamp)

    counts = {name: 0 for name in (
        "confirmed_arrivals", "early_events", "ambiguous_timing_events", "false_events",
        "missing_arrival_events", "missing_prediction_steps", "duplicate_events",
        "duplicate_event_steps", "missing_reference_steps", "right_censored_reference_steps",
        "occluded_reference_steps", "uncertain_reference_steps", "unassessable_events",
        "completed_paths", "failed_paths", "uncertain_paths", "paths_with_uncertain_reference",
        "out_of_order_paths",
        "excluded_trials", "excluded_steps", "excluded_reference_rows", "excluded_events",
        "ignored_nonarrival_actions", "arrival_events", "predicted_steps")}
    counts["ignored_nonarrival_actions"] = ignored_actions
    counts["excluded_events"] = excluded_events
    counts["excluded_reference_rows"] = sum(not manifest[key[0]]["eligible"] for key in truth_by_key)
    denominators = {name: 0 for name in ("eligible_trials", "eligible_steps", "known_arrival_steps",
                                         "observed_nonarrival_steps", "assessable_event_steps",
                                         "conditionally_assessable_paths", "delay_interval_steps")}
    per_step, per_trial = [], []
    for trial_id, trial in manifest.items():
        if not trial["eligible"]:
            counts["excluded_trials"] += 1
            counts["excluded_steps"] += len(trial["step_ids"])
            continue
        denominators["eligible_trials"] += 1
        trial_rows = []
        for step in trial["step_ids"]:
            denominators["eligible_steps"] += 1
            key = trial_id, step
            reference = truth_by_key.get(key)
            step_events = sorted(events.get(key, []))
            status = reference["status"] if reference is not None else "missing"
            duplicate_count = max(len(step_events) - 1, 0)
            counts["duplicate_events"] += duplicate_count
            counts["duplicate_event_steps"] += int(duplicate_count > 0)
            counts["arrival_events"] += len(step_events)
            counts["predicted_steps"] += int(bool(step_events))
            counts["missing_prediction_steps"] += int(not step_events)
            result = dict(trial_id=trial_id, task_id=trial["task_id"], step_id=step,
                          clock_domain=trial["clock_domain"], reference_status=status,
                          event_count=len(step_events), duplicate_event_count=duplicate_count,
                          confirmation_time_s=step_events[0] if step_events else None,
                          delay_lower_s=None, delay_upper_s=None)
            if status == "arrived":
                denominators["known_arrival_steps"] += 1
            elif status == "not_arrived":
                denominators["observed_nonarrival_steps"] += 1
            else:
                counts[status + "_reference_steps"] += 1
            if not step_events:
                outcome = "missing_arrival_event" if status == "arrived" else "no_event"
                counts["missing_arrival_events"] += int(status == "arrived")
            elif status not in {"arrived", "not_arrived"}:
                outcome = "unassessable"
                counts["unassessable_events"] += 1
            else:
                timestamp = step_events[0]
                if not reference["observation_start_s"] <= timestamp <= reference["observation_end_s"]:
                    outcome = "unassessable"
                    counts["unassessable_events"] += 1
                else:
                    denominators["assessable_event_steps"] += 1
                    if status == "not_arrived":
                        outcome = "false_event"
                        counts["false_events"] += 1
                    else:
                        lower, upper = reference["arrival_lower_s"], reference["arrival_upper_s"]
                        result.update(delay_lower_s=timestamp - upper, delay_upper_s=timestamp - lower)
                        denominators["delay_interval_steps"] += 1
                        if timestamp < lower:
                            outcome = "early"
                            counts["early_events"] += 1
                        elif lower < upper and timestamp <= upper:
                            outcome = "ambiguous_timing"
                            counts["ambiguous_timing_events"] += 1
                        else:
                            outcome = "confirmed_after_arrival"
                            counts["confirmed_arrivals"] += 1
            result["outcome"] = outcome
            trial_rows.append(result)
            per_step.append(result)

        uncertain_reference = any(row["reference_status"] not in {"arrived", "not_arrived"} for row in trial_rows)
        counts["paths_with_uncertain_reference"] += int(uncertain_reference)
        times = [row["confirmation_time_s"] for row in trial_rows if row["confirmation_time_s"] is not None]
        out_of_order = any(following < current for current, following in zip(times, times[1:]))
        counts["out_of_order_paths"] += int(out_of_order)
        definite_failure = out_of_order or any(row["outcome"] in {"early", "false_event", "missing_arrival_event"}
                               or row["reference_status"] == "not_arrived"
                               or row["duplicate_event_count"] for row in trial_rows)
        if definite_failure:
            path_status = "failed"
        elif uncertain_reference or any(row["outcome"] != "confirmed_after_arrival" for row in trial_rows):
            path_status = "uncertain"
        else:
            path_status = "completed"
        counts[path_status + "_paths"] += 1
        per_trial.append(dict(trial_id=trial_id, task_id=trial["task_id"], status=path_status,
                              planned_steps=len(trial_rows), uncertain_reference=uncertain_reference,
                              out_of_order=out_of_order))

    denominators["conditionally_assessable_paths"] = counts["completed_paths"] + counts["failed_paths"]
    def rate(numerator, denominator):
        return numerator / denominator if denominator else None

    return {
        "counts": counts,
        "denominators": denominators,
        "rates": {
            "path_completion_rate": rate(counts["completed_paths"], denominators["eligible_trials"]),
            "conditional_path_completion_rate": rate(counts["completed_paths"], denominators["conditionally_assessable_paths"]),
            "arrival_confirmation_recall": rate(counts["confirmed_arrivals"], denominators["known_arrival_steps"]),
            "early_event_rate": rate(counts["early_events"], denominators["assessable_event_steps"]),
            "false_event_rate": rate(counts["false_events"], denominators["observed_nonarrival_steps"]),
            "missing_prediction_step_rate": rate(counts["missing_prediction_steps"], denominators["eligible_steps"]),
        },
        "rate_denominators": {
            "path_completion_rate": "eligible_trials",
            "conditional_path_completion_rate": "conditionally_assessable_paths",
            "arrival_confirmation_recall": "known_arrival_steps",
            "early_event_rate": "assessable_event_steps",
            "false_event_rate": "observed_nonarrival_steps",
            "missing_prediction_step_rate": "eligible_steps",
        },
        "per_step": per_step, "per_trial": per_trial,
    }
