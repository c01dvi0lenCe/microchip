"""Read-only AVI/camera audit. No GUI, acquisition, inference or serial imports."""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

import cv2


ID = 'sdk_frame_number'
TIME = 'host_receive_perf_counter_ns'
GAP_FIELDS = ('scope', 'kind', ID, 'previous_sdk_frame_number', 'missing_first',
              'missing_last', 'missing_count', TIME)
MAX_GAP_NS = 180_000_000
MIN_SPAN_NS = 250_000_000
MIN_FRAMES = 5


def table(path, fields):
    with path.open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file, strict=True)
        if not set(fields) <= set(reader.fieldnames or ()):
            raise ValueError(f'{path.name}: missing CSV columns; expected {", ".join(fields)}')
        return list(reader)


def optional_id(raw):
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return None
    return value if value >= 0 else None


def frames(path, index_column):
    """Each (SDK ID, receive clock) identifies one delivery, even with repeated IDs."""
    stream = []
    for i, row in enumerate(table(path, (index_column, ID, TIME))):
        if int(row[index_column]) != i:
            raise ValueError(f'{path.name}: non-contiguous {index_column} at row {i}')
        stamp = int(row[TIME])
        if stamp <= 0 or (stream and stamp <= stream[-1][1]):
            raise ValueError(f'{path.name}: receive clock not strictly increasing at row {i}')
        stream.append((optional_id(row[ID]), stamp))
    return stream


def stream_stats(stream):
    events = []
    previous = prev_ns = None
    may_infer_gap = False
    longest = run = window_len = eligible = max_dt = long_gaps = 0
    window_start = 0
    for num, ns in stream:
        dt = ns - prev_ns if prev_ns is not None else 0
        max_dt = max(max_dt, dt)
        long_gaps += int(dt > MAX_GAP_NS)
        consecutive = previous is not None and num == previous + 1
        run = run + 1 if consecutive else int(num is not None)
        longest = max(longest, run)
        if not consecutive or dt > MAX_GAP_NS:
            window_len, window_start = 0, ns
        window_len += int(num is not None)
        if window_len >= MIN_FRAMES and ns - window_start >= MIN_SPAN_NS:
            eligible += 1

        kind = None
        if num is None:
            kind = 'unknown_id'
            may_infer_gap = False
        elif previous is None:
            may_infer_gap = True
        elif num <= previous:
            kind = 'duplicate' if num == previous else 'reversed'
            if num < previous:
                may_infer_gap = False
        else:
            # After a reversal, the first advancing pair restores the reference;
            # duplicates while waiting do not restore it. All adjacent events remain observable.
            if may_infer_gap and num > previous + 1:
                kind = 'missing_range'
            may_infer_gap = True
        if kind:
            first = previous + 1 if kind == 'missing_range' else None
            last = num - 1 if kind == 'missing_range' else None
            events.append((kind, num, previous, first, last, last-first+1 if first is not None else 0, ns))
        previous, prev_ns = num, ns

    duration = (stream[-1][1] - stream[0][1]) / 1e9 if stream else 0
    kinds = Counter(e[0] for e in events)
    gaps = Counter(e[5] for e in events if e[0] == 'missing_range')
    return dict(frames=len(stream), receive_span_s=duration,
                actual_fps=(len(stream)-1)/duration if duration else None,
                max_receive_gap_s=max_dt/1e9, receive_gaps_over_180ms=long_gaps,
                longest_consecutive_sdk_run=longest,
                window_eligible_ends=eligible, missing_between_ids=sum(k*n for k,n in gaps.items()),
                missing_range_length_histogram=dict(sorted(gaps.items())), duplicates=kinds['duplicate'],
                reversals=kinds['reversed'], unknown_ids=kinds['unknown_id'],
                first_id_events=[dict(zip(GAP_FIELDS[1:], event)) for event in events[:20]]), events


def decode_avi(path):
    if not path.is_file() or path.suffix.lower() != '.avi':
        raise ValueError('supply an existing local .avi file')
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError('cannot open AVI')
        reported = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        decoded = 0
        while True:
            ok, frame = capture.read()
            if not ok or frame is None or frame.size == 0:
                break
            decoded += 1
        return dict(header_frames=reported, decoded_frames=decoded,
                    header_playback_fps=fps if math.isfinite(fps) else None)
    finally:
        capture.release()


def compare_clock_summary(manifest, stats, issues, duration_key, fps_key):
    for key, value in ((duration_key, stats['receive_span_s']), (fps_key, stats['actual_fps'])):
        if key not in manifest:
            continue
        actual = manifest[key]
        equal = actual is None and value is None
        if value is not None and isinstance(actual, (int, float)):
            equal = math.isclose(actual, value, rel_tol=1e-8, abs_tol=1e-9)
        if not equal:
            issues.append(f'manifest {key} does not match receive timestamps')


def audit_v2(video, manifest, saved, result):
    issues = result['integrity_errors']
    captured = frames(video.with_suffix('.capture.csv'), 'capture_index')
    stats, events = stream_stats(captured)
    result['capture'] = stats
    drops, reasons, sdk_rows = Counter(), Counter(), Counter()
    for row in table(video.with_suffix('.gaps.csv'), GAP_FIELDS):
        kind, num = row['kind'], optional_id(row[ID])
        first, last = optional_id(row['missing_first']), optional_id(row['missing_last'])
        count, ns = int(row['missing_count'] or 0), int(row[TIME])
        if row['scope'] == 'sdk_delivery':
            sdk_rows[(kind, num, optional_id(row['previous_sdk_frame_number']), first, last, count, ns)] += 1
        elif row['scope'] == 'local_recording':
            if not kind or (first, last, count) != (num, num, 1):
                raise ValueError('invalid local_recording reason or single-frame loss range in gaps.csv')
            drops[(num, ns)] += 1
            reasons[kind] += 1
        else:
            raise ValueError(f"unknown gaps.csv scope: {row['scope']}")
    result['local_drops_by_reason'] = dict(reasons)
    if sdk_rows != Counter(events):
        issues.append('gaps.csv SDK events do not match capture IDs/times/ranges')
    # Strict receive times already prove order. Counts alone cannot catch an ID substitution.
    if Counter(saved) + drops != Counter(captured):
        issues.append('saved identities plus local loss identities do not equal captured identities')
    continuity = manifest.get('continuity')
    if not isinstance(continuity, dict):
        raise ValueError('missing manifest continuity section')
    compare_clock_summary(continuity, stats, issues, 'capture_host_duration_s', 'capture_host_fps')
    expected = dict(captured_frames=len(captured), local_dropped_frames=sum(drops.values()),
                    sdk_missing_between_received=stats['missing_between_ids'])
    for key, value in expected.items():
        if continuity.get(key) != value:
            issues.append(f'manifest continuity.{key} does not match sidecars ({value})')
    status = continuity.get('status')
    result['manifest_continuity_status'] = status
    if status not in ('continuous', 'gaps_observed', 'unverified'):
        issues.append('missing or unsupported manifest continuity status')
    elif status == 'continuous' and (events or drops):
        issues.append('manifest claims continuity despite ID events or local loss')
    elif status == 'gaps_observed' and not events and not drops:
        issues.append('manifest claims gap events which are absent from both streams')
    if status != 'continuous' or events or drops or not captured:
        result['acceptance_failures'].append('capture continuity is not established')


def inspect_recording(video, *, min_seconds=30.0):
    """Return a JSON-ready report; diagnose incomplete audit trails without modifying them."""
    video = Path(video)
    result = dict(video=str(video), outcome='fail', integrity_errors=[], acceptance_failures=[])
    issues, failures = result['integrity_errors'], result['acceptance_failures']
    try:
        if not math.isfinite(min_seconds) or min_seconds < 0:
            raise ValueError('min_seconds must be finite and non-negative')
        result['min_receive_span_s'] = min_seconds
        avi = result['avi'] = decode_avi(video)
        manifest = json.loads(video.with_suffix('.recording.json').read_text(encoding='utf-8-sig'))
        if not isinstance(manifest, dict) or manifest.get('schema_version') not in (1, 2):
            raise ValueError('manifest must be an object with supported schema_version (1 or 2)')
        schema = manifest['schema_version']
        result.update(schema_version=schema, scope='capture_and_saved' if schema == 2 else 'legacy_saved_only',
                      manifest_status=manifest.get('status'))
        if manifest.get('status') != 'complete' or manifest.get('error'):
            issues.append(f"recording is not complete: {manifest.get('status')}; {manifest.get('error', '')}")
        nominal = float(manifest['nominal_playback_fps'])
        if not math.isfinite(nominal) or nominal <= 0:
            raise ValueError('invalid nominal playback FPS')
        result['nominal_playback_fps'] = nominal
        saved = frames(video.with_suffix('.timestamps.csv'), 'video_frame_index')
        stats, _ = stream_stats(saved)
        result['saved'] = stats
        compare_clock_summary(manifest, stats, issues, 'host_receive_duration_s', 'host_receive_fps')
        counts = {k: manifest.get(k) for k in ('recorded_frames', 'written_timestamp_rows', 'encoded_frame_count')}
        counts.update(timestamp_rows=len(saved), avi_header=avi['header_frames'], decoded=avi['decoded_frames'])
        result['counts'] = counts
        if not saved or not all(v == len(saved) for v in counts.values()):
            issues.append('AVI/manifest/saved timestamp counts are zero or disagree')
        if stats['receive_span_s'] < min_seconds:
            failures.append('saved first-to-last receive span below requested duration')
        if not stats['window_eligible_ends']:
            failures.append('no eligible saved-frame timing window')
        if stats['receive_gaps_over_180ms']:
            failures.append('saved receive interval exceeds 0.18 s; timing window interrupted')
        if schema == 2:
            audit_v2(video, manifest, saved, result)
            if not issues and not failures:
                result['outcome'] = 'pass'
        elif not issues:
            result['outcome'] = 'unverified'
    except (OSError, csv.Error, TypeError, KeyError, ValueError, OverflowError, cv2.error) as exc:
        issues.append(str(exc))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path, help='local finalized AVI, with sidecars beside it')
    parser.add_argument('--min-seconds', type=float, default=30.0,
                        help='minimum saved receive-clock span (default: 30; use 0 for clip diagnostics)')
    args = parser.parse_args(argv)
    result = inspect_recording(args.video, min_seconds=args.min_seconds)
    print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    return {'pass': 0, 'fail': 1, 'unverified': 2}[result['outcome']]


if __name__ == '__main__':
    raise SystemExit(main())
