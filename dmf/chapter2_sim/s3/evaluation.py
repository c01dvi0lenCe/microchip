"""Three-step ledger and request/Applied scoring, never called by algorithms."""
from collections import Counter
import math
from .reference import physical_segments,support_at

TERMINALS=('infrastructure_invalid','source_preparation_failed','transport_aborted',
           'workflow_complete_without_supported_path','reference_supported_path_complete')

def terminal_class(*,invalid=False,prepared=False,workflow=False,path=False):
    return (TERMINALS[0] if invalid else TERMINALS[1] if not prepared else TERMINALS[2] if not workflow else TERMINALS[4] if path else TERMINALS[3])

def evaluate_trial(trial,geometry,spec):
    route=spec.common.environment.route;segments=physical_segments(trial.truth,geometry,spec.common.reference,spec.common.environment.dt_s)
    dt=spec.common.environment.dt_s
    times=[row['time_s'] for row in trial.truth]
    invalid=(trial.metrics.get('infrastructure_invalid',False) or not times or
             any(not all(math.isfinite(row[k]) for k in ('time_s','x','y','true_speed')) for row in trial.truth) or
             any(not 0<b-a<=dt+1e-9 for a,b in zip(times,times[1:])))
    by_request={e['request_id']:e for e in trial.events if e['event']=='Applied'}
    activations={};evaluated=[]
    for event in trial.events:
        if event['event']=='Applied' and event.get('action') in ('Start','Update'):
            activations.setdefault(event['activation_step'],event['time_s'])
    for e in trial.events:
        if e['event'] not in ('Update','Complete'):continue
        step=e['step'];target=route[step+1]
        request=support_at(segments,target,e['time_s'],not_before_s=activations.get(step))
        if step not in activations or e['time_s']<activations[step]-1e-9:
            request=dict(supported=False,label='unsupported_no_activation',reference_lower_s=None,reference_upper_s=None)
        applied=by_request.get(e['request_id']);a=(support_at(segments,target,applied['time_s'],not_before_s=activations.get(step)) if applied else None)
        if a is not None and (step not in activations or applied['time_s']<activations[step]-1e-9):
            a=dict(supported=False,label='unsupported_no_activation',reference_lower_s=None,reference_upper_s=None)
        evaluated.append(dict(step=step,target=target,request_id=e['request_id'],action=e['event'],request_s=e['time_s'],
             request_label=request['label'],supported_at_request=request['supported'],applied_s=applied['time_s'] if applied else None,
             applied_label=a['label'] if a else 'not_applicable_no_electrode_transaction',supported_at_applied=a['supported'] if a else None,
             reference_lower_s=request['reference_lower_s'],reference_upper_s=request['reference_upper_s'],
             delay_lower_s=e['time_s']-request['reference_upper_s'] if request['supported'] else None,
             delay_upper_s=e['time_s']-request['reference_lower_s'] if request['supported'] else None))
        if invalid:
            evaluated[-1].update(request_label='reference_unknown',supported_at_request=False,
                                 applied_label='reference_unknown' if applied else 'not_applicable_no_electrode_transaction',
                                 supported_at_applied=None,delay_lower_s=None,delay_upper_s=None)
    source_event=next((e for e in trial.events if e['event']=='Start'),None)
    source_support=(support_at(segments,route[0],source_event['time_s'])['supported'] if source_event else False)
    # A controlled transport diagnostic has no visual/independent source-prep
    # success; it is never pooled into an end-to-end path estimate.
    steps=[]
    for step in range(3):
        preds=[e for e in evaluated if e['step']==step]
        start=activations.get(step)
        ref=[r for r in segments if r['target']==route[step+1] and r.get('activation_target')==route[step+1] and start is not None and r['upper_s']>=start-1e-9]
        stop=preds[0]['request_s'] if preds else trial.metrics['execution_time_s']
        refs=[r for r in ref if r['upper_s']<=stop+1e-9]
        supported=not invalid and start is not None and len(preds)==1 and preds[0]['supported_at_request']
        steps.append(dict(step=step,source=route[step],target=route[step+1],attempted=start is not None,
            activation_s=start,confirmation_requested=bool(preds),reference_arrived=None if invalid else bool(refs),reference_unknown=bool(invalid),supported_confirmation=supported,
            unsupported_requests=sum(not p['supported_at_request'] and p['request_label']!='reference_unknown' for p in preds),duplicate_requests=max(0,len(preds)-1),
            missed_reference=not invalid and bool(refs) and not supported,unattempted=start is None,
            outcome='unattempted' if start is None else 'reference_unknown' if invalid else 'supported' if supported else 'unsupported_confirmation' if preds else 'attempted_unconfirmed'))
    budget=Counter(e.get('activation_step') for e in trial.events if e['event']=='Applied' and e.get('action') in ('Start','Update','Retry','Recovery'))
    invalid=invalid or any(n>7 for n in budget.values())
    strict=all(s['attempted'] and s['supported_confirmation'] for s in steps) and (source_support or trial.phase_mode=='transport_only')
    terminal=terminal_class(invalid=invalid,prepared=trial.metrics['source_prepared'],workflow=trial.metrics['transport_complete'],path=strict)
    trial.references=segments;trial.steps=steps;trial.event_evaluation=evaluated
    trial.metrics.update(terminal_outcome=terminal,path_complete=terminal==TERMINALS[-1],source_reference_supported=source_support,
        planned_steps=3,attempted_steps=sum(s['attempted'] for s in steps),unattempted_steps=sum(s['unattempted'] for s in steps),
        reference_arrived_steps=sum(s['reference_arrived'] is True for s in steps),supported_confirmations=sum(s['supported_confirmation'] for s in steps),
        unsupported_requests=sum(not e['supported_at_request'] and e['request_label']!='reference_unknown' for e in evaluated),missed_confirmations=sum(s['missed_reference'] for s in steps),
        reference_unknown_steps=3 if invalid else 0,unknown_reference_events=sum(e['request_label']=='reference_unknown' for e in evaluated),
        infrastructure_invalid=bool(invalid),censored_steps=sum(s['reference_arrived'] is True and not s['confirmation_requested'] for s in steps),
        premature_requests=sum(e['request_label']=='premature' for e in evaluated),timing_uncertain_requests=sum(e['request_label']=='timing_uncertain' for e in evaluated),
        supported_at_applied=sum(e['supported_at_applied'] is True for e in evaluated),
        budgetized_completion_s=trial.metrics['execution_time_s'] if terminal==TERMINALS[-1] else spec.common.environment.max_time_s)
    return trial
