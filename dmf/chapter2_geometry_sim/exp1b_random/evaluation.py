"""One mutually exclusive outcome plus separate fixed-deadline diagnostics."""
import math


def score(event, reference, horizon, pending_count=0, status='executed'):
    complete = [r for r in reference['intervals'] if r['confirmed_s'] is not None
                and r['confirmed_s'] <= horizon+1e-9]
    decision = event['decision_s'] if event is not None else None
    if decision is not None and (not isinstance(decision,(int,float)) or not math.isfinite(decision) or decision<0):
        raise ValueError('Finite nonnegative event decision time required')
    if decision is not None and decision > horizon+1e-9:
        raise ValueError('An event beyond H is not an executed by-H decision')
    support = next((r for r in complete if decision is not None
        and decision >= r['confirmed_s']-1e-9 and (decision < r['end_s']-1e-9
        or (r.get('terminal_inclusive', False) and decision <= r['end_s']+1e-9))), None)
    pending = reference['status'] in ('dwell_incomplete_at_H', 'approaching_at_H', 'no_reference_by_H')
    if status != 'executed': outcome = 'unattempted'
    elif support: outcome = 'reference_supported'
    elif decision is not None:
        if complete and any(decision < r['confirmed_s']-1e-9 for r in complete): outcome = 'before_reference'
        elif complete: outcome = 'outside_reference_support'
        elif pending: outcome = 'confirmation_reference_pending_at_H'
        else: outcome = 'no_reference_confirmation'
    elif complete: outcome = 'reference_not_confirmed'
    elif pending: outcome = 'no_confirmation_reference_pending_at_H'
    elif reference['status'] == 'permanent_stall_without_reference': outcome = 'permanent_stall_no_confirmation'
    else: outcome = 'no_reference_no_confirmation'
    attempted = status == 'executed'
    return dict(primary_outcome=outcome, primary_outcome_count=1, planned_steps=1,
        reference_status=reference['status'], reference_arrivals=len(complete),
        reference_confirmed_s=complete[0]['confirmed_s'] if complete else None,
        missed_references_by_H=len(complete)-int(support is not None),
        supported_by_H=int(support is not None) if attempted else None,
        confirmed_by_H=int(decision is not None) if attempted else None,
        not_supported_by_H=int(decision is not None and support is None) if attempted else None,
        latency_s=decision-support['confirmed_s'] if support else None,
        signed_deviation_s=decision-complete[0]['confirmed_s'] if complete and decision is not None else None,
        decision_s=decision, pending_deliveries_at_H=pending_count,
        observation_right_censored=bool(pending_count), reference_right_censored=pending,
        physical_wrong_advance=None, unattempted=not attempted)
