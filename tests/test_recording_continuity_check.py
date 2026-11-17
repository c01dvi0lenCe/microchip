import csv
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np


class RecordingContinuityCheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.video = Path(tmp.name) / 'sample.avi'

    def table(self, suffix, columns, rows):
        with self.video.with_suffix(suffix).open('w', encoding='utf-8', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(columns.split())
            writer.writerows(rows)

    def write_avi(self, n):
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*'MJPG'), 30, (32,32))
        self.assertTrue(writer.isOpened())
        try:
            for i in range(n):
                writer.write(np.full((32, 32, 3), i % 255, np.uint8))
        finally:
            writer.release()

    def bundle(self, received, *, saved=None, stamp=None, events=(), legacy=False,
               encoded=None, missing=0, local=0):
        stamp = stamp or [1_000_000_000 + i * 62_500_000 for i in range(len(received))]
        saved = list(range(len(received))) if saved is None else saved
        n = len(saved)
        self.write_avi(n if encoded is None else encoded)
        self.table('.timestamps.csv', 'video_frame_index sdk_frame_number host_receive_perf_counter_ns',
                   ((i, received[j], stamp[j]) for i, j in enumerate(saved)))
        manifest = dict(schema_version=1 if legacy else 2, status='complete', error='',
                        recorded_frames=n, written_timestamp_rows=n, encoded_frame_count=n,
                        nominal_playback_fps=30)
        if not legacy:
            self.table('.capture.csv', 'capture_index sdk_frame_number host_receive_perf_counter_ns',
                       ((i, num, stamp[i]) for i, num in enumerate(received)))
            self.table('.gaps.csv', 'scope kind sdk_frame_number previous_sdk_frame_number '
                       'missing_first missing_last missing_count host_receive_perf_counter_ns', events)
            manifest['continuity'] = dict(captured_frames=len(received), local_dropped_frames=local,
                                          sdk_missing_between_received=missing,
                                          status='continuous' if not events else 'gaps_observed')
        self.video.with_suffix('.recording.json').write_text(json.dumps(manifest), encoding='utf-8')

    def inspect(self, **kwargs):
        self.assertIsNotNone(importlib.util.find_spec('scripts.check_recording_continuity'),
                             'missing read-only continuity inspector')
        fn = importlib.import_module('scripts.check_recording_continuity').inspect_recording
        return fn(self.video, **{'min_seconds': 0, **kwargs})

    def test_smooth_clip_distinguishes_nominal_and_actual_fps_and_inclusive_window(self):
        self.bundle(list(range(12)))
        result = self.inspect()
        self.assertEqual(result['integrity_errors'], [])
        self.assertEqual(result['outcome'], 'pass')
        self.assertEqual(result['avi']['decoded_frames'], 12)
        self.assertEqual(result['nominal_playback_fps'], 30)
        self.assertEqual(result['saved']['actual_fps'], 16)
        self.assertEqual(result['saved']['longest_consecutive_sdk_run'], 12)
        self.assertEqual(result['saved']['window_eligible_ends'], 8)
        self.assertEqual(self.inspect(min_seconds=30)['outcome'], 'fail')

    def test_fast_fps_windows_can_use_more_than_five_frames_but_never_cross_long_gap(self):
        # Exactly 5 at .03125s each is insufficient. Exactly .25 s between ends qualifies.
        times = [1_000_000_000 + i*31_250_000 for i in range(9)]
        times += [times[-1]+180_000_001, times[-1]+360_000_001]
        self.bundle(list(range(11)), stamp=times)
        result = self.inspect()
        self.assertEqual(result['saved']['window_eligible_ends'], 1)
        self.assertEqual(result['outcome'], 'fail', 'one good window must not hide a timing gap')
        self.assertEqual(result['saved']['receive_gaps_over_180ms'], 1)
        self.assertFalse(result['integrity_errors'])
        times[9] -= 1
        times[10] -= 1
        self.bundle(list(range(11)), stamp=times)
        result = self.inspect()
        self.assertEqual(result['saved']['window_eligible_ends'], 3)
        self.assertEqual(result['outcome'], 'pass')

    def test_gap_scopes_and_saved_id_vs_received_id_are_not_conflated(self):
        events = [('sdk_delivery','missing_range',14,11,12,13,2,1_125_000_000),
                  ('local_recording','queue_full',11,'',11,11,1,1_062_500_000)]
        self.bundle([10,11,14,15], saved=[0,2,3], events=events, missing=2, local=1)
        result = self.inspect()
        self.assertFalse(result['integrity_errors'], result)
        self.assertEqual(result['outcome'], 'fail')
        self.assertEqual(result['saved']['missing_between_ids'], 3)
        self.assertEqual(result['capture']['missing_between_ids'], 2)
        self.assertEqual(result['capture']['longest_consecutive_sdk_run'], 2)
        self.assertEqual(result['local_drops_by_reason'], {'queue_full':1})

    def test_legacy_reports_saved_ids_only_and_never_returns_acceptance(self):
        self.bundle([12,13,17,17,16,None,19,20], legacy=True)
        result = self.inspect()
        self.assertEqual(result['scope'], 'legacy_saved_only')
        self.assertEqual(result['outcome'], 'unverified')
        self.assertNotIn('capture', result)
        stats = result['saved']
        self.assertEqual((stats['missing_between_ids'], stats['duplicates'],
                          stats['reversals'], stats['unknown_ids']), (3,1,1,1))
        self.assertEqual(stats['longest_consecutive_sdk_run'], 2)
        self.assertEqual(stats['window_eligible_ends'], 0)

    def test_adjacent_repeats_and_reversals_remain_visible_even_after_a_reset(self):
        self.bundle([15,14,14,13,12,40], legacy=True)
        stats = self.inspect()['saved']
        self.assertEqual(stats['duplicates'], 1)
        self.assertEqual(stats['reversals'], 3)

    def test_v2_reset_records_verifiable_adjacent_events_but_no_speculative_gap(self):
        ids = [10,9,8,8,11,12,15]
        ns = [1_000_000_000 + i * 62_500_000 for i in range(len(ids))]
        events = [('sdk_delivery','reversed',9,10,'','','',ns[1]),
                  ('sdk_delivery','reversed',8,9,'','','',ns[2]),
                  ('sdk_delivery','duplicate',8,8,'','','',ns[3]),
                  ('sdk_delivery','missing_range',15,12,13,14,2,ns[6])]
        self.bundle(ids, stamp=ns, events=events, missing=2)
        result = self.inspect()
        self.assertEqual(result['integrity_errors'], [])
        stats = result['capture']
        self.assertEqual((stats['reversals'], stats['duplicates'], stats['missing_between_ids']), (2,1,2))
        self.assertEqual([(e['kind'], e['previous_sdk_frame_number'], e['sdk_frame_number'])
                          for e in stats['first_id_events']],
                         [('reversed',10,9), ('reversed',9,8), ('duplicate',8,8), ('missing_range',12,15)])
        self.bundle(ids, stamp=ns, events=events[1:], missing=2)
        self.assertTrue(self.inspect()['integrity_errors'], 'silently omitted reversal must fail audit')

    def test_missing_or_fabricated_loss_record_or_saved_identity_invalidates_integrity(self):
        self.bundle([8,9,11,12], saved=[0,2,3], missing=1, local=1)
        self.assertTrue(self.inspect()['integrity_errors'])
        self.bundle(list(range(8)))
        self.table('.timestamps.csv', 'video_frame_index sdk_frame_number host_receive_perf_counter_ns',
                   ((i, i+100, 1_000_000_000 + i*62_500_000) for i in range(8)))
        self.assertTrue(self.inspect()['integrity_errors'])
        self.bundle(list(range(8)), events=[('local_recording','queue_full',1,'','','',1,1_062_500_000)])
        self.assertTrue(self.inspect()['integrity_errors'])

    def test_invalid_video_counts_missing_capture_and_nonmonotonic_times_never_pass(self):
        self.bundle(list(range(6)), encoded=5)
        self.assertTrue(self.inspect()['integrity_errors'])
        self.bundle(list(range(6)), stamp=[10,20,20,21,22,23])
        self.assertTrue(self.inspect()['integrity_errors'])
        self.bundle(list(range(6)))
        self.video.with_suffix('.capture.csv').unlink()
        self.assertTrue(self.inspect()['integrity_errors'])

    def test_bad_manifest_or_non_avi_input_is_reported_without_traceback(self):
        self.bundle(list(range(7)))
        self.video.with_suffix('.recording.json').write_text('[]', encoding='utf-8')
        self.assertTrue(self.inspect()['integrity_errors'])
        proc = subprocess.run([sys.executable, '-m','scripts.check_recording_continuity',
                               str(self.video.with_suffix('.absent'))], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn('Traceback', proc.stderr)
        self.assertTrue(json.loads(proc.stdout)['integrity_errors'])

    def test_real_journal_unknown_and_reversal_do_not_invent_a_missing_range(self):
        from dmf.recording import RecordingJournal

        ids = [10,10,9,8,8,11,-1,100,101,104]
        self.write_avi(len(ids)-1)
        journal = RecordingJournal(self.video, 30)
        self.addCleanup(journal.log.close)
        for i, num in enumerate(ids):
            ns = 1_000_000_000 + i * 62_500_000
            row = dict(sdk_frame_number=num, host_receive_perf_counter_ns=ns, host_utc_ns=ns,
                       host_receive_monotonic_ns=ns)
            journal.observe_capture(row)
            if num == 101:
                journal.record_loss(row, 'queue_full')
            else:
                journal.add_frame(row)
        journal.close()
        result = self.inspect()
        self.assertEqual(result['integrity_errors'], [])
        self.assertEqual(result['outcome'], 'fail')
        self.assertEqual(result['capture']['missing_between_ids'], 2)
        self.assertEqual(result['capture']['unknown_ids'], 1)
        self.assertEqual((result['capture']['reversals'], result['capture']['duplicates']), (2,2))
        self.assertEqual(result['local_drops_by_reason'], {'queue_full':1})

    def test_manifest_time_summary_disagreeing_with_saved_timestamps_fails_audit(self):
        self.bundle(list(range(10)))
        path = self.video.with_suffix('.recording.json')
        meta = json.loads(path.read_text(encoding='utf-8'))
        meta['host_receive_duration_s'] = 6000
        meta['continuity']['capture_host_fps'] = 30
        path.write_text(json.dumps(meta), encoding='utf-8')
        self.assertTrue(self.inspect()['integrity_errors'])

    def test_default_cli_accepts_exactly_30_seconds_without_modifying_its_inputs(self):
        self.bundle(list(range(481)))
        def contents():
            return {p.name: p.read_bytes() for p in self.video.parent.iterdir()}
        before = contents()
        proc = subprocess.run([sys.executable, '-m', 'scripts.check_recording_continuity',
                               str(self.video)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        report = json.loads(proc.stdout)
        self.assertEqual(report['outcome'], 'pass')
        self.assertEqual(report['saved']['receive_span_s'], 30)
        self.assertEqual(report['saved']['window_eligible_ends'], 477)
        self.assertEqual(contents(), before)
