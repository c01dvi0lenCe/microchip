"""One primary outcome per planned method/step, separate from control safety."""


def truth(value):return value is True or value=='True'


def exclusive_outcome(record):
    refs=int(record.get('reference_arrivals') or 0)
    category=record.get('category','')
    decision=record.get('decision_s')
    if record.get('status')!='executed':outcome='unattempted'
    elif category=='decision_censored' or truth(record.get('decision_censored',False)):outcome='censored'
    elif decision in (None,''):
        outcome='reference_not_confirmed' if refs else 'no_reference_no_confirmation'
    elif category=='supported':outcome='reference_supported'
    elif category=='premature':outcome='before_reference'
    else:outcome='outside_reference_support' if refs else 'no_reference_confirmation'
    return dict(primary_outcome=outcome,primary_outcome_count=1,
        unmatched_reference_diagnostic=int(record.get('missed_references') or 0),
        control_safety_evaluated=False,actual_wrong_advance=None)
