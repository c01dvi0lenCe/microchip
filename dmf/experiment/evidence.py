"""Causal, task-scoped observation evidence; no hardware or reference labels."""
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math


@dataclass(frozen=True)
class StepContext:
    run_id: str
    step_index: int
    attempt_index: int
    epoch: int
    source_id: int
    target_id: int
    applied_receive_ns: int | None = None
    clock_domain: str = 'unknown'
    phase: str = 'transport'
    applied_timestamp_s: float | None = None
    software_barrier_ns: int | None = None
    applied_time_quality: str = 'unavailable'


@dataclass(frozen=True)
class ArrivalEvent:
    event_id: str
    context: StepContext
    first_frame_id: int
    last_frame_id: int
    evidence_start_s: float
    evidence_end_s: float
    confirmed_at_ns: int | None
    evidence_clock_domain: str = 'unknown'
    causality: str = 'causality_unknown'

    @classmethod
    def from_window(cls, context, window, confirmed_at_ns, evidence_clock_domain, causality):
        if window.last_reason != 'CONFIRMED' or not window.samples:
            raise ValueError('arrival requires a confirmed evidence window')
        if window.context not in (context,(context,'Arrived')):
            raise ValueError('evidence belongs to another task context')
        first, last = window.samples[0], window.samples[-1]
        identity = (context.run_id, context.step_index, context.attempt_index, context.epoch, first[3], last[3])
        event_id = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()[:24]
        return cls(event_id, context, first[3], last[3], first[0], last[0],
                   confirmed_at_ns, evidence_clock_domain, causality)


class ArrivalEventLedger:
    """A step can be consumed once, only while its exact task epoch is active."""
    def __init__(self):
        self.current = None
        self.consumed_steps = set()
        self.consumed_events = set()

    def activate(self, context):
        self.current = context

    def consume(self, event):
        key = (event.context.run_id, event.context.step_index)
        if (event.context != self.current or event.context.phase != 'transport' or
                key in self.consumed_steps or event.event_id in self.consumed_events):
            return False
        self.consumed_steps.add(key)
        self.consumed_events.add(event.event_id)
        return True


@dataclass(frozen=True)
class FrameAssessment:
    accepted: bool
    reason: str = ''
    causality: str = 'causality_unknown'


class FrameCausalityGuard:
    """Global identity high-water marks survive Retry/Recovery/Update.

    Receive freshness is a software barrier only. Unmapped exposure remains
    uncertain even when its receive timestamp is later than APPLIED.
    """
    def __init__(self):
        self.high_water = {}
        self.stream = None

    def check(self, packet, context, *, mode):
        timing = packet.timing
        if timing and timing.task_epoch is not None and timing.task_epoch != context.epoch:
            return FrameAssessment(False, 'TASK_EPOCH_MISMATCH')
        if self.stream is not None and packet.video_id != self.stream:
            return FrameAssessment(False, 'STREAM_CHANGED')
        self.stream = packet.video_id
        key = (packet.video_id, 'sdk' if timing and timing.capture_frame_id is not None else 'consumer')
        identity = packet.capture_identity
        if type(identity) is not int or identity < 0:
            return FrameAssessment(False, 'INVALID_FRAME_ID')
        if identity <= self.high_water.get(key, -1):
            return FrameAssessment(False, 'DUPLICATE_OR_REVERSED_FRAME')
        self.high_water[key] = identity
        if not math.isfinite(packet.timestamp_s):
            return FrameAssessment(False, 'INVALID_TIMESTAMP')
        if mode == 'simulation':
            if (context.clock_domain != 'simulation' or packet.timestamp_clock_domain != 'simulation' or
                    timing is None or timing.exposure_clock_domain != 'simulation'):
                return FrameAssessment(False, 'CLOCK_DOMAIN_MISMATCH')
            start=getattr(timing,'exposure_start_s',None)
            end=getattr(timing,'exposure_end_s',None)
            available=getattr(timing,'available_s',None)
            if (any(v is None or not math.isfinite(v) or v<0 for v in (start,end,available)) or
                    start>end or end>available or abs(end-packet.timestamp_s)>1e-9):
                return FrameAssessment(False, 'INVALID_SIMULATION_TIMING')
            if context.applied_timestamp_s is not None and start<context.applied_timestamp_s-1e-9:
                return FrameAssessment(False, 'PRE_ACTUATION_EXPOSURE','simulation_exposure_verified')
            return FrameAssessment(True,causality='simulation_exposure_verified')
        if mode == 'offline':
            if context.clock_domain!=packet.timestamp_clock_domain:
                return FrameAssessment(False, 'CLOCK_DOMAIN_MISMATCH', 'offline_replay')
            if context.applied_timestamp_s is not None and packet.timestamp_s <= context.applied_timestamp_s:
                return FrameAssessment(False, 'PRE_ACTUATION_FRAME', 'offline_replay')
            return FrameAssessment(True, causality='offline_replay')
        if timing and timing.clock_domain != 'host_monotonic':
            return FrameAssessment(False, 'CLOCK_DOMAIN_MISMATCH')
        # Legacy callers use the existing live monotonic-seconds contract, but
        # are explicitly not upgraded to exposure-verified timing.
        received = timing.receive_monotonic_ns if timing else int(packet.timestamp_s*1e9)
        if type(received) is not int or received < 0:
            return FrameAssessment(False, 'MISSING_RECEIVE_TIMESTAMP')
        mapped_exposure=(timing and timing.timing_quality=='exposure_mapped' and
                         timing.exposure_clock_domain=='host_monotonic' and timing.exposure_start_ns is not None)
        if mapped_exposure and timing.exposure_start_ns>received:
            return FrameAssessment(False, 'INVALID_EXPOSURE_TIMESTAMP')
        barrier=context.applied_receive_ns if context.applied_receive_ns is not None else context.software_barrier_ns
        if barrier is None:
            return FrameAssessment(True)
        if context.clock_domain != 'host_monotonic':
            return FrameAssessment(False, 'CLOCK_DOMAIN_MISMATCH')
        if received <= barrier:
            return FrameAssessment(False, 'PRE_ACTUATION_FRAME')
        if (timing and timing.timing_quality == 'exposure_mapped' and
                timing.exposure_clock_domain == context.clock_domain and timing.exposure_start_ns is not None):
            if timing.exposure_start_ns <= barrier:
                return FrameAssessment(False, 'PRE_ACTUATION_EXPOSURE')
            return FrameAssessment(True, causality='exposure_order_verified' if context.applied_receive_ns is not None else 'causality_unknown')
        return FrameAssessment(True)


class EvidenceWindow:
    def __init__(self, min_frames, min_duration_s, max_gap_s,
                 max_centroid_span_mm=None, max_coverage_span=None):
        if type(min_frames) is not int or min_frames < 1:
            raise ValueError('min_frames must be a positive integer')
        if not math.isfinite(min_duration_s) or min_duration_s < 0 or not math.isfinite(max_gap_s) or max_gap_s <= 0:
            raise ValueError('invalid evidence duration/gap')
        for limit in (max_centroid_span_mm, max_coverage_span):
            if limit is not None and (not math.isfinite(limit) or limit < 0):
                raise ValueError('invalid evidence stability limit')
        self.min_frames, self.min_duration_s, self.max_gap_s = min_frames, min_duration_s, max_gap_s
        self.max_centroid_span_mm, self.max_coverage_span = max_centroid_span_mm, max_coverage_span
        self.reset()

    def reset(self):
        self.context = None
        self.samples = deque()
        self.last_time = self.last_frame = None
        self.id_mode = None
        self.last_reason = 'RESET'

    @property
    def count(self):
        return len(self.samples)

    def _stable(self):
        if self.max_centroid_span_mm is not None:
            points = [row[1] for row in self.samples]
            span = math.hypot(max(p[0] for p in points)-min(p[0] for p in points),
                              max(p[1] for p in points)-min(p[1] for p in points))
            if span > self.max_centroid_span_mm:
                return False
        if self.max_coverage_span is not None:
            values = [row[2] for row in self.samples]
            if max(values)-min(values) > self.max_coverage_span:
                return False
        return True

    def observe(self, context, frame_id, timestamp_s, eligible, centroid_mm=None, eta_target=None):
        if context != self.context:
            self.reset()
            self.context = context
        if (not math.isfinite(timestamp_s) or
                (frame_id is not None and (type(frame_id) is not int or frame_id < 0))):
            self.samples.clear()
            self.last_reason = 'INVALID_TIME_OR_FRAME'
            return False
        if ((self.last_time is not None and timestamp_s <= self.last_time) or
                (frame_id is not None and self.last_frame is not None and frame_id <= self.last_frame)):
            self.samples.clear()
            self.last_reason = 'DUPLICATE_OR_REVERSED_OBSERVATION'
            return False  # Keep the high-water marks, not a new clock origin.
        gap = (self.last_time is not None and timestamp_s-self.last_time > self.max_gap_s+1e-9)
        missing_id = (frame_id is not None and self.last_frame is not None and frame_id != self.last_frame+1)
        mode_changed = self.id_mode is not None and self.id_mode != (frame_id is not None)
        if gap or missing_id or mode_changed:
            self.samples.clear()
        self.last_time = timestamp_s
        self.id_mode = frame_id is not None
        if frame_id is not None:
            self.last_frame = frame_id
        position_ok = (centroid_mm is not None and len(centroid_mm) == 2 and
                       all(math.isfinite(v) for v in centroid_mm))
        coverage_ok = eta_target is not None and math.isfinite(eta_target)
        if (not eligible or (self.max_centroid_span_mm is not None and not position_ok) or
                (self.max_coverage_span is not None and not coverage_ok)):
            self.samples.clear()
            self.last_reason = 'INELIGIBLE_OBSERVATION'
            return False
        self.samples.append((timestamp_s, centroid_mm, eta_target, frame_id))
        while len(self.samples) > 1 and not self._stable():
            self.samples.popleft()
        # Keep a bounded recent suffix sufficient for both count and duration.
        while (len(self.samples) > self.min_frames and
               timestamp_s-self.samples[1][0] >= self.min_duration_s-1e-9):
            self.samples.popleft()
        confirmed = (self.count >= self.min_frames and
                     timestamp_s-self.samples[0][0] >= self.min_duration_s-1e-9)
        self.last_reason = ('CONFIRMED' if confirmed else 'IDENTITY_MODE_REBUILT' if mode_changed else
                            'GAP_REBUILT' if gap or missing_id else 'INSUFFICIENT_EVIDENCE')
        return confirmed


class ProgressMonitor:
    """Net improvement over a historical best, plus independent safety clocks.

    The experiment supplies signed source-target progress (mm); legacy callers
    may supply negative target distance. Jitter/return travel cannot
    repeatedly reset the progress timer without beating the prior best.
    """
    def __init__(self, no_progress_s, attempt_timeout_s, min_progress_mm, quality_timeout_s):
        self.no_progress_s, self.attempt_timeout_s = no_progress_s, attempt_timeout_s
        self.min_progress_mm, self.quality_timeout_s = min_progress_mm, quality_timeout_s
        self.context = None
        self.reset(None, 0.)

    def reset(self, context, t_s):
        self.context, self.started, self.last_time = context, t_s, t_s
        self.progress_at = self.last_reliable = t_s
        self.best = None
        self.status = 'insufficient'

    def observe(self, context, t_s, progress_mm, reliable):
        if context != self.context:
            self.reset(context, t_s)
        if not math.isfinite(t_s) or t_s < self.last_time:
            self.status = 'invalid_time'
            return self.status
        self.last_time = t_s
        improved = False
        if reliable:
            self.last_reliable = t_s
            if progress_mm is not None and math.isfinite(progress_mm):
                if self.best is None:
                    self.best = progress_mm
                elif progress_mm-self.best >= self.min_progress_mm:
                    self.best, self.progress_at, improved = progress_mm, t_s, True
        if t_s-self.last_reliable >= self.quality_timeout_s:
            self.status = 'quality_timeout'
        elif t_s-self.started >= self.attempt_timeout_s:
            self.status = 'attempt_expired'
        elif t_s-self.progress_at >= self.no_progress_s:
            self.status = 'no_progress'
        else:
            self.status = 'progress' if improved else 'insufficient'
        return self.status
