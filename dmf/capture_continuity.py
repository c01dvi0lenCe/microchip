"""Bounded, metadata-only accounting between SDK delivery and AVI submission."""
import threading


CAPTURE_FIELDS = ('capture_index', 'sdk_frame_number', 'device_timestamp_raw',
                  'sdk_host_timestamp_raw', 'host_receive_perf_counter_ns')
GAP_FIELDS = ('scope', 'kind', 'sdk_frame_number', 'previous_sdk_frame_number',
              'missing_first', 'missing_last', 'missing_count', 'host_receive_perf_counter_ns')


class CaptureContinuity:
    def __init__(self, log):
        self.log = log
        self.lock = threading.Lock()
        self.captured = self.missing = self.local = self.ambiguous = self.gap_rows = 0
        self.preview_replaced = 0
        self.last_seen = self.first_ns = self.last_ns = None
        self.can_count_missing = False

    def _gap(self, meta, scope, kind, **extra):
        row = dict(scope=scope, kind=kind, sdk_frame_number=meta.get('sdk_frame_number'),
                   host_receive_perf_counter_ns=meta['host_receive_perf_counter_ns'], **extra)
        self.log.append('gaps', row)
        self.gap_rows += 1

    def receive(self, meta):
        with self.lock:
            row = {k: meta.get(k) for k in CAPTURE_FIELDS}
            row['capture_index'] = self.captured
            self.log.append('capture', row)
            self.captured += 1
            self.last_ns = meta['host_receive_perf_counter_ns']
            if self.first_ns is None:
                self.first_ns = self.last_ns
            try:
                number = int(meta['sdk_frame_number'])
                if number < 0:
                    raise ValueError
            except (TypeError, ValueError, KeyError):
                self._gap(meta, 'sdk_delivery', 'unknown_id', previous_sdk_frame_number=self.last_seen)
                self.ambiguous += 1
                self.last_seen = None
                self.can_count_missing = False
                return
            previous, self.last_seen = self.last_seen, number
            if previous is not None:
                delta = number - previous
                if delta > 1 and self.can_count_missing:
                    self.missing += delta - 1
                    self._gap(meta, 'sdk_delivery', 'missing_range', previous_sdk_frame_number=previous,
                              missing_first=previous+1, missing_last=number-1, missing_count=delta-1)
                elif delta <= 0:
                    self._gap(meta, 'sdk_delivery', 'duplicate' if delta == 0 else 'reversed',
                              previous_sdk_frame_number=previous)
                    self.ambiguous += 1
                    # A reset, wrap or reordered sample cannot establish a missing range.
                    if delta < 0:
                        self.can_count_missing = False
                    return
            self.can_count_missing = True

    def loss(self, meta, reason):
        with self.lock:
            self.local += 1
            self._gap(meta, 'local_recording', reason, missing_count=1,
                      missing_first=meta.get('sdk_frame_number'), missing_last=meta.get('sdk_frame_number'))

    def preview_replacement(self):
        with self.lock:
            self.preview_replaced += 1

    def accounting_error(self, written):
        if self.log.counts['capture'] != self.captured or self.log.counts['gaps'] != self.gap_rows:
            return 'capture accounting: missing audit rows'
        if (self.captured or self.local) and self.captured != written + self.local:
            return 'capture accounting: SDK received != timestamped AVI frames + local recording losses'
        return ''

    def summary(self, sealed_ok):
        duration = (self.last_ns-self.first_ns)/1e9 if self.captured > 1 else 0
        uncertain = not sealed_ok or self.captured < 2 or self.ambiguous or duration <= 0
        return dict(status='unverified' if uncertain else
                    ('gaps_observed' if self.missing or self.local else 'continuous'),
                    captured_frames=self.captured, sdk_missing_between_received=self.missing,
                    local_dropped_frames=self.local, ambiguous_sdk_events=self.ambiguous,
                    preview_replacements=self.preview_replaced,
                    capture_host_duration_s=duration,
                    capture_host_fps=(self.captured-1)/duration if duration > 0 else None,
                    scope='Between first and last SDK buffers received during this recording only')
