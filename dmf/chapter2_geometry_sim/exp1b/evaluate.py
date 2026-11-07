"""Reference-interval scoring only, never used by recognition."""
import math


def score_event(event,reference,horizon):
    intervals=reference['intervals']
    refs=[r for r in intervals if r['confirmed_s'] is not None and r['confirmed_s']<=horizon+1e-9]
    t=event['decision_s'] if event else None
    if t is not None and (not math.isfinite(t) or t<0):raise ValueError('invalid event decision time')
    support=next((r for r in refs if t is not None and r['confirmed_s']-1e-9<=t<r['end_s']-1e-9),None)
    future=next((r for r in refs if t is not None and t<r['confirmed_s']-1e-9),None)
    censored=t is not None and t>horizon+1e-9
    category=('unconfirmed' if t is None else 'decision_censored' if censored else
              'supported' if support else 'premature' if future else 'unsupported')
    region=('dwell_building' if future and t>=future['start_s']-1e-9 else
            'before_dwell' if future else 'supported' if support else 'no_matching_reference')
    first=refs[0] if refs else None
    return dict(planned_steps=1,reference_arrivals=len(refs),category=category,timing_region=region,
        supported_confirmations=int(category=='supported'),premature_confirmations=int(category=='premature'),
        unsupported_confirmations=int(category=='unsupported'),missed_references=len(refs)-int(support is not None and not censored),
        decision_s=t,reference_confirmed_s=first['confirmed_s'] if first else None,
        signed_deviation_s=t-first['confirmed_s'] if t is not None and first and not censored else None,
        latency_s=t-support['confirmed_s'] if support and not censored else None,
        reference_dwell_censored=any(r['confirmed_s'] is None and r['end_s']>=horizon-1e-9 for r in intervals),
        decision_censored=censored,unattempted=False)
