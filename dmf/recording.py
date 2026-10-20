"""Host-receive timing and acknowledged electrode state, independent of Tk/SDK."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading
import time

FRAME_FIELDS = ('video_frame_index', 'sdk_frame_number', 'device_timestamp_raw',
    'sdk_host_timestamp_raw', 'host_receive_monotonic_ns', 'host_receive_perf_counter_ns', 'host_utc_ns',
    'host_time_utc', 'host_time_local', 'receive_relative_s',
    'timestamp_source', 'input_completed_monotonic_ns', 'width', 'height', 'pixel_type')
EVENT_FIELDS = ('event', 'host_monotonic_ns', 'host_perf_counter_ns', 'host_utc_ns', 'request_id', 'sequence',
    'host_time_utc', 'host_time_local',
    'attempt', 'line', 'sent', 'changes', 'error', 'state_known', 'active_ids',
    'pending_request_ids')


def clock_stamp():
    return dict(host_monotonic_ns=time.monotonic_ns(), host_perf_counter_ns=time.perf_counter_ns(),
        host_utc_ns=time.time_ns())


def readable_clock(utc_ns):
    moment = datetime.fromtimestamp(utc_ns // 1000000000, timezone.utc).replace(
        microsecond=(utc_ns % 1000000000) // 1000)
    return dict(host_time_utc=moment.isoformat(), host_time_local=moment.astimezone().isoformat())


def sidecar_paths(video):
    path = Path(video)
    return {name: path.with_suffix(suffix) for name, suffix in (
        ('timestamps', '.timestamps.csv'), ('electrodes', '.electrodes.csv'),
        ('manifest', '.recording.json'), ('alignment', '.frame_electrodes.csv'))}


class AsyncCsvLog:
    """Bounded non-blocking producers; overflow is an explicit audit failure."""
    def __init__(self, tables, capacity=8192):
        self.queue = queue.Queue(maxsize=capacity)
        self.lock = threading.Lock()
        self.error = ''
        self.closed = False
        self.handles = {}
        self.writers = {}
        self.counts = {name: 0 for name in tables}
        try:
            for name, (path, fields) in tables.items():
                handle = Path(path).open('x', encoding='utf-8', newline='')
                self.handles[name] = handle
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                handle.flush()
                self.writers[name] = writer
        except Exception:
            for handle in self.handles.values():
                handle.close()
            raise
        self.worker = threading.Thread(target=self._write, name='capture-audit-writer', daemon=True)
        self.worker.start()

    def append(self, table, row):
        with self.lock:
            if self.closed:
                return
            if self.error:
                return
            try:
                self.queue.put_nowait((table, dict(row)))
            except queue.Full:
                self.error = 'capture audit queue overflow; recording is incomplete'

    def _write(self):
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break
                table, row = item
                self.writers[table].writerow(row)
                self.counts[table] += 1
                self.handles[table].flush()
        except Exception as exc:
            self.error = f'capture audit write failed: {exc}'
        finally:
            for handle in self.handles.values():
                handle.close()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        while self.worker.is_alive():
            try:
                self.queue.put(None, timeout=.05)
                break
            except queue.Full:
                continue
        self.worker.join()


def event_row(event):
    row = {key: event.get(key, '') for key in EVENT_FIELDS}
    for key in ('changes', 'active_ids', 'pending_request_ids'):
        if row[key] != '':
            row[key] = json.dumps(row[key], sort_keys=True, separators=(',', ':'))
    if row['host_utc_ns'] != '':
        row.update(readable_clock(int(row['host_utc_ns'])))
    return row


class ElectrodeEventStream:
    """Last confirmed full state; unknown until ALL_OFF is acknowledged."""
    def __init__(self):
        self.lock = threading.Lock()
        self.known = False
        self.active = set()
        self.pending = set()
        self.listeners = []

    def emit(self, event):
        with self.lock:
            kind = event['event']
            request = event.get('request_id', '')
            if kind in ('transaction_requested', 'all_off_requested'):
                self.pending.add(request)
            elif kind == 'applied':
                for electrode, state in event['changes'].items():
                    if state:
                        self.active.add(int(electrode))
                    else:
                        self.active.discard(int(electrode))
                self.pending.discard(request)
            elif kind == 'all_off_confirmed':
                self.active.clear()
                self.pending.discard(request)
                self.known = True
            elif kind in ('transaction_failed', 'all_off_failed', 'state_unknown'):
                self.pending.discard(request)
                self.known = False
            for listener in self.listeners:
                listener(event)

    def subscribe(self, listener):
        with self.lock:
            listener(dict(event='initial_state', **clock_stamp(), state_known=self.known,
                active_ids=sorted(self.active) if self.known else [],
                pending_request_ids=sorted(self.pending)))
            self.listeners.append(listener)

    def unsubscribe(self, listener):
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)


def align_electrodes(paths):
    """Replay acknowledgement history on the PC receive clock, not exposure time."""
    with paths['electrodes'].open(encoding='utf-8', newline='') as handle:
        events = list(csv.DictReader(handle))
    events.sort(key=lambda row: int(row['host_perf_counter_ns']))
    known, active, pending, cursor = False, set(), set(), 0
    fields = ('video_frame_index', 'host_receive_monotonic_ns', 'host_receive_perf_counter_ns', 'state_status',
        'confirmed_active_ids', 'pending_request_ids', 'last_event')
    last_event = ''
    with paths['timestamps'].open(encoding='utf-8', newline='') as source, \
            paths['alignment'].open('x', encoding='utf-8', newline='') as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for frame in csv.DictReader(source):
            stamp = int(frame['host_receive_perf_counter_ns'])
            while cursor < len(events) and int(events[cursor]['host_perf_counter_ns']) <= stamp:
                event = events[cursor]
                cursor += 1
                kind, request = event['event'], event['request_id']
                last_event = kind
                if kind == 'initial_state':
                    known = event['state_known'] == 'True'
                    active = set(json.loads(event['active_ids']))
                    pending = set(json.loads(event['pending_request_ids']))
                elif kind in ('transaction_requested', 'all_off_requested'):
                    pending.add(request)
                elif kind == 'applied':
                    for electrode, state in json.loads(event['changes']).items():
                        if state:
                            active.add(int(electrode))
                        else:
                            active.discard(int(electrode))
                    pending.discard(request)
                elif kind == 'all_off_confirmed':
                    active.clear()
                    known = True
                    pending.discard(request)
                elif kind in ('transaction_failed', 'all_off_failed', 'state_unknown'):
                    known = False
                    pending.discard(request)
            writer.writerow(dict(video_frame_index=frame['video_frame_index'],
                host_receive_monotonic_ns=frame['host_receive_monotonic_ns'],
                host_receive_perf_counter_ns=stamp,
                state_status='pending' if pending else 'confirmed' if known else 'unknown',
                confirmed_active_ids=json.dumps(sorted(active)) if known else '',
                pending_request_ids=json.dumps(sorted(pending)), last_event=last_event))


class RecordingJournal:
    def __init__(self, video, nominal_fps, stream=None):
        self.video = Path(video)
        self.paths = sidecar_paths(video)
        self.nominal_fps = nominal_fps
        self.stream = stream
        self.log = AsyncCsvLog({
            'frames': (self.paths['timestamps'], FRAME_FIELDS),
            'events': (self.paths['electrodes'], EVENT_FIELDS)})
        self.frame_count = 0
        self.closed = False
        self.first_ns = self.last_ns = None
        self.callback = lambda event: self.log.append('events', event_row(event))
        if stream is not None:
            stream.subscribe(self.callback)
        else:
            self.callback(dict(event='initial_state', **clock_stamp(), state_known=False,
                active_ids=[], pending_request_ids=[]))
        try:
            self._manifest('recording', '')
        except Exception:
            if stream is not None:
                stream.unsubscribe(self.callback)
            self.log.close()
            raise

    def _manifest(self, status, error, encoded_count=None):
        duration = (self.last_ns - self.first_ns) / 1e9 if self.frame_count > 1 else 0
        payload = dict(schema_version=1, video=str(self.video), status=status, error=error,
            recorded_frames=self.frame_count, written_timestamp_rows=self.log.counts['frames'],
            encoded_frame_count=encoded_count, nominal_playback_fps=self.nominal_fps,
            host_receive_duration_s=duration,
            host_receive_fps=(self.frame_count - 1) / duration if duration > 0 else None,
            timestamp_source='host_receive_perf_counter', device_timestamp_unit='unknown_raw_ticks',
            host_counter_implementation=time.get_clock_info('perf_counter').implementation,
            host_counter_resolution_s=time.get_clock_info('perf_counter').resolution,
            legacy_monotonic_resolution_s=time.get_clock_info('monotonic').resolution,
            sdk_host_timestamp_unit='unknown_raw',
            timing_note='PC buffer receive time, not sensor exposure time; APPLIED is electrical acknowledgement, not droplet arrival.',
            files={key: str(value) for key, value in self.paths.items()})
        self.paths['manifest'].write_text(json.dumps(payload, indent=2), encoding='utf-8')

    def add_frame(self, metadata):
        if self.log.error:
            raise OSError(self.log.error)
        stamp = metadata['host_receive_perf_counter_ns']
        if self.last_ns is not None and stamp <= self.last_ns:
            self.log.error = 'non-monotonic host receive timestamp'
            raise ValueError(self.log.error)
        self.log.append('frames', dict(metadata, video_frame_index=self.frame_count,
            receive_relative_s=(stamp - (self.first_ns if self.first_ns is not None else stamp)) / 1e9,
            **readable_clock(metadata['host_utc_ns'])))
        self.frame_count += 1
        self.first_ns = stamp if self.first_ns is None else self.first_ns
        self.last_ns = stamp
        if self.log.error:
            raise OSError(self.log.error)

    def close(self, error=''):
        if self.closed:
            return
        self.closed = True
        if self.stream is not None:
            self.stream.unsubscribe(self.callback)
        self.log.close()
        error = error or self.log.error
        count = None
        if self.video.is_file():
            import cv2
            capture = cv2.VideoCapture(str(self.video))
            try:
                if capture.isOpened():
                    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            finally:
                capture.release()
            if count != self.frame_count:
                error = error or f'AVI frame count mismatch: {count} vs {self.frame_count} timestamps'
        else:
            error = error or 'AVI file was not created by the SDK'
        if not self.frame_count:
            error = error or 'recording contains no accepted frames'
        if not error:
            try:
                align_electrodes(self.paths)
            except Exception as exc:
                error = str(exc)
        status = 'incomplete' if error else 'complete'
        self._manifest(status, error, count)
        if error:
            raise OSError(error)


def load_recorded_timestamps(video, explicit=None):
    paths = sidecar_paths(video)
    path = Path(explicit) if explicit else paths['timestamps']
    if not path.exists():
        if explicit:
            raise FileNotFoundError(path)
        if paths['manifest'].exists():
            raise ValueError('recording timestamp sidecar is missing')
        return None
    if not explicit:
        if not paths['manifest'].exists():
            raise ValueError('recording manifest is missing')
        manifest = json.loads(paths['manifest'].read_text(encoding='utf-8'))
        if manifest['status'] != 'complete':
            raise ValueError('recording audit is incomplete or unverified')
    stamps = []
    with path.open(encoding='utf-8', newline='') as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            stamp = int(row['host_receive_perf_counter_ns'])
            if int(row['video_frame_index']) != index or stamp <= 0 or (stamps and stamp <= stamps[-1]):
                raise ValueError('recording timestamps must be contiguous and strictly increasing')
            stamps.append(stamp)
    if not stamps:
        raise ValueError('recording contains no timestamp rows')
    return [(stamp - stamps[0]) / 1e9 for stamp in stamps]
