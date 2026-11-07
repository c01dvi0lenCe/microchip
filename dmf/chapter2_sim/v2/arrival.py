"""Same coverage thresholds and the exact same EvidenceWindow for BT/BTQ/F."""
from dataclasses import asdict
import math

from dmf.experiment.evidence import EvidenceWindow


def window_trace(window,context,frame_id,t,eligible,centroid,coverage):
    reasons=[];same=context==window.context
    if not same:reasons.append('context_change')
    if same and window.last_time is not None:
        if t<=window.last_time or (window.last_frame is not None and frame_id<=window.last_frame):reasons.append('duplicate_or_reversed')
        if t-window.last_time>window.max_gap_s+1e-9:reasons.append('long_gap')
        if window.last_frame is not None and frame_id!=window.last_frame+1:reasons.append('missing_id')
    rows=list(window.samples) if same and not reasons else []
    if eligible:rows.append((t,centroid,coverage,frame_id))
    points=[r[1] for r in rows if r[1] is not None]
    values=[r[2] for r in rows if r[2] is not None]
    span=(math.hypot(max(p[0] for p in points)-min(p[0] for p in points),max(p[1] for p in points)-min(p[1] for p in points)) if points else None)
    cspan=max(values)-min(values) if values else None
    if span is not None and window.max_centroid_span_mm is not None and span>window.max_centroid_span_mm:reasons.append('centroid_span')
    if cspan is not None and window.max_coverage_span is not None and cspan>window.max_coverage_span:reasons.append('coverage_span')
    if not eligible:reasons.append('ineligible')
    confirmed=window.observe(context,frame_id,t,eligible,centroid,coverage)
    duration=window.samples[-1][0]-window.samples[0][0] if window.samples else 0.
    return dict(confirmed=confirmed,window_count=window.count,window_duration_s=duration,
        window_start_s=window.samples[0][0] if window.samples else None,window_end_s=window.samples[-1][0] if window.samples else None,
        proposed_centroid_span_pitch=span,proposed_coverage_span=cspan,rebuild_reasons=reasons,window_reason=window.last_reason,
        insufficient_count=window.count<window.min_frames,insufficient_duration=duration<window.min_duration_s-1e-9)


class ArrivalGate:
    def __init__(self,target,flags):
        self.target,self.flags=target,flags;self.contract=asdict(target)
        w=target.window
        self.window=EvidenceWindow(w.frames if flags.W else 1,w.duration_s if flags.W else 0.,w.max_gap_s,
            w.centroid_span_pitch if flags.W else None,w.coverage_span if flags.W else None)

    def reset(self):self.window.reset()

    def observe(self,context,packet,raw):
        coverage=raw['eta_target']>=self.target.coverage and raw['eta_source']<=self.target.source_release
        gates=dict(S=(not self.flags.S or raw['S']),K=(not self.flags.K or raw['K']),Q=(not self.flags.Q or raw['Q']))
        eligible=coverage and all(gates.values())
        trace=window_trace(self.window,context,packet.capture_identity,packet.timestamp_s,eligible,raw['centroid'],raw['eta_target'])
        trace.update(C0_passed=True,C0_reason='',raw=raw,enabled=asdict(self.flags),coverage_passed=coverage,
            eligible=eligible,effective_gates=gates,thresholds=self.contract,stage='target',rejection_reasons=(['coverage'] if not coverage else [])+[k for k,v in gates.items() if not v])
        return trace
