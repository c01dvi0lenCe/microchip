"""Truth-only independent dwell support; never called by the controller."""
import math


def exclusive_terminal(control_terminal,supported_path):
    if control_terminal=='complete':
        return 'reference_supported_path_complete' if supported_path else 'workflow_complete_without_supported_path'
    if control_terminal not in ('source_preparation_failed','transport_aborted','time_budget_exhausted'):
        raise ValueError('unrecognized terminal category')
    return control_terminal


class IndependentReference:
    def __init__(self,geometry,config):
        self.geometry,self.cfg=geometry,config;self.current=None;self.segments=[];self.marks=[]
        self.dwell_start=None;self.support=False;self.last_time=None

    def observe(self,snapshot):
        t=snapshot['time_s'];active=snapshot['active']
        if self.last_time is not None and t<self.last_time-1e-9:raise ValueError('nonmonotone reference time')
        if self.current is None or active!=self.current['active']:
            if self.current is not None:
                self.current['end_s']=t
                if self.support:self.current['intervals'][-1]['end_s']=t
            self.current=dict(active=active,reference_segment=len(self.segments),start_s=t,end_s=None,first_supported_s=None,intervals=[])
            self.segments.append(self.current);self.dwell_start=None;self.support=False
        distance=math.dist((snapshot['x_mm'],snapshot['y_mm']),self.geometry.center(active))
        eligible=distance<=self.cfg.reference_radius_mm+1e-10 and snapshot['speed_mm_s']<=self.cfg.reference_speed_mm_s+1e-10
        if eligible:
            if self.dwell_start is None:self.dwell_start=t
            now_supported=t-self.dwell_start>=self.cfg.reference_dwell_s-1e-9
            if now_supported and not self.support:
                self.current['intervals'].append(dict(start_s=t,end_s=None))
                if self.current['first_supported_s'] is None:self.current['first_supported_s']=t
            self.support=now_supported
        else:
            if self.support:self.current['intervals'][-1]['end_s']=t
            self.support=False;self.dwell_start=None
        self.last_time=t

    def supported(self,target):return bool(self.current is not None and self.current['active']==target and self.support)

    def mark(self,kind,time_s,target,step,action,request_id=None):
        mark=dict(kind=kind,time_s=time_s,target=target,step=step,action=action,
                  request_id=request_id,supported=self.supported(target))
        self.marks.append(mark);return mark

    def score(self,controller,world_rows):
        steps=[]
        for source in controller.steps:
            step=dict(source);i=step['step'];target=step['target']
            target_segments=[s for s in self.segments if s['active']==target]
            refs=[s['first_supported_s'] for s in target_segments if s['first_supported_s'] is not None]
            reference_status=('unattempted' if not step['attempted'] else
                'completed' if refs else
                'ongoing_at_horizon' if target_segments and target_segments[-1]['end_s'] is None else
                'observed_closed_noncompletion' if target_segments else 'reference_unavailable')
            marks=[m for m in self.marks if m['step']==i and m['action'] in ('Update','Complete')]
            request=next((m for m in marks if m['kind']=='request'),None)
            applied=next((m for m in marks if m['kind']=='applied'),None)
            step.update(reference_first_supported_s=min(refs) if refs else None,
                reference_completed=bool(refs),request_supported=request['supported'] if request else None,
                applied_supported=applied['supported'] if applied else None,
                departure_applied_applicable=i<2,
                reference_status=reference_status,
                reference_censored=reference_status=='ongoing_at_horizon')
            steps.append(step)
        reference_path=all(s['reference_completed'] for s in steps)
        request_path=all(s['request_supported'] is True for s in steps)
        applied_path=all(s['applied_supported'] is True for s in steps[:-1])
        path=reference_path and request_path and applied_path
        terminal=controller.terminal or 'time_budget_exhausted'
        return steps,dict(terminal=exclusive_terminal(terminal,path),transport_complete=terminal=='complete',
            final_target_reference_completed=steps[-1]['reference_completed'],sequential_reference_path=reference_path,
            request_supported_path=request_path,applied_supported_path=applied_path,reference_supported_path=path,
            unsupported_requests=sum(m['kind']=='request' and not m['supported'] for m in self.marks),
            unsupported_applied=sum(m['kind']=='applied' and not m['supported'] for m in self.marks),
            blocked_no_overlap_ticks=sum(r['world_status']=='blocked_no_overlap' for r in world_rows),
            blocked_no_overlap_times_s=[r['time_s'] for r in world_rows if r['world_status']=='blocked_no_overlap'],
            planned_steps=3,attempted_steps=sum(s['attempted'] for s in steps),
            total_step_applied=sum(s['applied_count'] for s in steps),random_draws=0,
            physical_danger_evaluated=False)
