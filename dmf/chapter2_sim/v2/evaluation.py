"""Mutually exclusive execution terminals, with independent error/action labels."""
from collections import Counter
import statistics


TERMINALS=('source_not_prepared','source_prepared','transport_complete','transport_stopped','time_limit','infrastructure_error')
STEP_OUTCOMES=('unattempted','attempted_unconfirmed','confirmed')


def evaluate_trial(trial,predictions=None):
    predictions=([e for e in trial.events if e['event'] in ('Update','Complete')] if predictions is None else predictions)
    planned=len(trial.route)-1
    refs={r['step']:r for r in trial.references}
    events=[];by_step={i:[] for i in range(planned)};delays=[];wrong=duplicate=uncertain=unsupported=0
    for p in predictions:
        step=p.get('step');time=p.get('time_s')
        if step not in by_step or p.get('target')!=trial.route[step+1]:wrong+=1;continue
        if by_step[step]:duplicate+=1
        r=refs.get(step)
        label=('unsupported_no_reference' if r is None else 'early' if time<r['lower_s']-1e-9 else
               'uncertain_interval' if time<r['upper_s']-1e-9 else 'supported')
        unsupported+=int(label in ('unsupported_no_reference','early'));uncertain+=int(label=='uncertain_interval')
        event=dict(step=step,target=p['target'],confirmation_s=time,label=label,
            delay_lower_s=time-r['upper_s'] if r and label=='supported' else None,
            delay_upper_s=time-r['lower_s'] if r and label=='supported' else None)
        events.append(event);by_step[step].append(event)
        if label=='supported' and len(by_step[step])==1:delays.append(time-r['upper_s'])
    attempted={e['step'] for e in trial.events if (e['event']=='Applied' and e.get('action') in ('Start','Update','Retry'))}
    steps=[];correct=missed=0
    for step in range(planned):
        pred=by_step[step];supported=bool(pred and pred[0]['label']=='supported')
        missed+=int(step in refs and not supported);correct+=int(supported)
        steps.append(dict(step=step,source=trial.route[step],target=trial.route[step+1],
            execution_outcome='confirmed' if pred else 'attempted_unconfirmed' if step in attempted else 'unattempted',
            reference_support='arrived' if step in refs else 'not_arrived_within_observed_trial' if trial.truth else 'unknown_no_trajectory',
            correct_confirmation=supported,unsupported_events=sum(e['label'] in ('early','unsupported_no_reference') for e in pred),
            uncertain_events=sum(e['label']=='uncertain_interval' for e in pred),
            missed_reference=step in refs and not supported,right_censored=step in refs and not pred,
            reference_lower_s=refs[step]['lower_s'] if step in refs else None,reference_upper_s=refs[step]['upper_s'] if step in refs else None))
    path_complete=(trial.metrics.get('terminal_outcome')=='transport_complete' and correct==planned and unsupported==0 and wrong==0 and duplicate==0 and uncertain==0)
    return dict(planned_steps=planned,attempted_steps=len(attempted),unattempted_steps=planned-len(attempted),
        confirmed_steps=sum(bool(v) for v in by_step.values()),issued_confirmation_events=len(predictions),
        reference_arrived_steps=len(refs),correct_confirmed_steps=correct,missed_reference_events=missed,
        unsupported_events=unsupported,wrong_events=wrong,duplicate_events=duplicate,uncertain_events=uncertain,
        confirmation_delay_mean_s=statistics.mean(delays) if delays else None,delay_observed_steps=len(delays),
        unsupported_per_planned_step=unsupported/planned,unsupported_per_issued_event=unsupported/len(predictions) if predictions else None,
        arrival_recall=correct/len(refs) if refs else None,path_complete=path_complete,
        right_censored_steps=sum(s['right_censored'] for s in steps),reference_unknown_steps=sum(s['reference_support']=='unknown_no_trajectory' for s in steps),steps=steps,event_evaluation=events)


def summarize_phases(trials):
    trials=list(trials)
    if not trials:raise ValueError('explicit planned trials required')
    modes={r.phase_mode for r in trials}
    if len(modes)!=1:raise ValueError('phase views must be summarized separately')
    identities=[r.trial_id for r in trials]
    if len(set(identities))!=len(identities):raise ValueError('duplicate trial identity')
    terminals=Counter(r.metrics['terminal_outcome'] for r in trials)
    if any(t not in TERMINALS for t in terminals):raise ValueError('unknown terminal')
    steps=Counter(s['execution_outcome'] for r in trials for s in r.steps)
    if any(t not in STEP_OUTCOMES for t in steps):raise ValueError('unknown step outcome')
    planned=len(trials);prepared=sum(r.metrics['prepared'] for r in trials);complete=sum(r.metrics['path_complete'] for r in trials)
    planned_steps=sum(r.metrics['planned_steps'] for r in trials)
    if sum(terminals.values())!=planned or sum(steps.values())!=planned_steps:raise ValueError('planned support lost')
    return dict(simulation=True,purpose='development_smoke_not_formal_performance',phase_mode=next(iter(modes)),planned_trials=planned,
        prepared=prepared,not_prepared=planned-prepared,planned_steps=planned_steps,terminal_counts=dict(terminals),step_execution_counts=dict(steps),
        path_complete=complete,prepared_rate=prepared/planned,path_complete_rate=complete/planned if next(iter(modes))!='source_only' else None,
        conditional_transport_path_rate=complete/prepared if prepared and next(iter(modes))!='source_only' else None,
        retries=sum(r.metrics.get('retries',0) for r in trials),recoveries=sum(r.metrics.get('recoveries',0) for r in trials),
        unsupported_events=sum(r.metrics.get('unsupported_events',0) for r in trials),
        unknown_frames=sum(r.metrics.get('unknown_frames',0) for r in trials),missing_mask_frames=sum(r.metrics.get('missing_mask_frames',0) for r in trials))
