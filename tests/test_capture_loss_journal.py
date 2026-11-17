import csv
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from dmf.recording import RecordingJournal


def record(stamp, sdk_id):
    return dict(sdk_frame_number=sdk_id, host_receive_perf_counter_ns=stamp,
                host_receive_monotonic_ns=stamp, host_utc_ns=1_000_000_000 + stamp,
                timestamp_source='host_receive_perf_counter')


def read(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


class CaptureLossJournalTests(unittest.TestCase):
    def journal(self, temp, n):
        path = Path(temp) / 'sample.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (16, 16))
        self.assertTrue(writer.isOpened())
        for _ in range(n):
            writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
        writer.release()
        journal = RecordingJournal(path, 10)
        self.addCleanup(journal.log.close)
        return journal

    def test_received_missing_range_and_local_drop_are_disjoint(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            j = self.journal(folder, 3)
            for k, sid in enumerate([10, 11, 14, 15], start=1):
                meta = record(k*100_000_000, sid)
                j.observe_capture(meta)
                if sid == 11:
                    j.record_loss(meta, 'queue_full')
                else:
                    j.add_frame(meta)
            j.close()
            gaps = read(j.paths['gaps'])
            self.assertEqual([(x['scope'], x['kind']) for x in gaps],
                             [('local_recording', 'queue_full'), ('sdk_delivery', 'missing_range')])
            self.assertEqual((gaps[0]['sdk_frame_number'], gaps[1]['missing_first'],
                              gaps[1]['missing_last'], gaps[1]['missing_count']), ('11','12','13','2'))
            self.assertEqual([int(x['sdk_frame_number']) for x in read(j.paths['capture'])],[10,11,14,15])
            self.assertEqual([int(x['sdk_frame_number']) for x in read(j.paths['timestamps'])],[10,14,15])
            meta = json.loads(j.paths['manifest'].read_text())
            self.assertEqual(meta['status'], 'complete')  # valid AVI, not continuous
            summary = meta['continuity']
            self.assertEqual(summary['status'], 'gaps_observed')
            self.assertEqual((summary['captured_frames'], summary['sdk_missing_between_received'],
                              summary['local_dropped_frames']), (4, 2, 1))

    def test_unaccounted_received_frame_is_incomplete(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            j = self.journal(folder, 1)
            j.observe_capture(record(1, 21))
            j.add_frame(record(1, 21))
            j.observe_capture(record(2, 22))
            with self.assertRaisesRegex(OSError, 'capture accounting'):
                j.close()
            meta = json.loads(j.paths['manifest'].read_text())
            self.assertEqual(meta['status'], 'incomplete')
            self.assertEqual(meta['continuity']['status'], 'unverified')

    def test_unordered_and_unknown_ids_do_not_establish_continuity(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            j = self.journal(folder, 7)
            for t, sid in enumerate([10, 10, 9, 11, '', 101, 102], start=1):
                meta = record(t, sid)
                j.observe_capture(meta)
                j.add_frame(meta)
            j.close()
            self.assertEqual([r['kind'] for r in read(j.paths['gaps'])],
                             ['duplicate','reversed','unknown_id'])
            c = json.loads(j.paths['manifest'].read_text())['continuity']
            self.assertEqual(c['status'], 'unverified')
            self.assertEqual(c['sdk_missing_between_received'], 0)

    def test_encoded_only_client_is_not_mistaken_for_capture_audit(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            j = self.journal(folder, 1)
            j.add_frame(record(1, 10))
            j.close()
            self.assertEqual(json.loads(j.paths['manifest'].read_text())['continuity']['status'], 'unverified')

    def test_every_observable_duplicate_or_reversal_is_logged_even_after_reset(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            ids = [10, 9, 8, 8, 11, 12]
            j = self.journal(folder, len(ids))
            for i, number in enumerate(ids):
                meta = record(i + 1, number)
                j.observe_capture(meta)
                j.add_frame(meta)
            j.close()
            self.assertEqual([(x['kind'], x['previous_sdk_frame_number'], x['sdk_frame_number'])
                              for x in read(j.paths['gaps'])], [('reversed', '10', '9'),
                               ('reversed', '9', '8'), ('duplicate', '8', '8')])

    def test_preview_replacement_does_not_drop_a_recording_frame(self):
        from controllers.camera_controller import recording_continuity_message
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            j = self.journal(folder, 3)
            for i in range(3):
                meta = record(1+i*50_000_000, i+25)
                j.observe_capture(meta)
                j.add_frame(meta)
            j.record_preview_replacement()
            j.close()
            summary = json.loads(j.paths['manifest'].read_text())['continuity']
            self.assertEqual((summary['status'], summary['preview_replacements'],
                              summary['capture_host_fps']), ('continuous', 1, 20))
            message = recording_continuity_message(j.video)
            self.assertIn('实收 3', message)
            self.assertIn('已写 3', message)
            self.assertIn('未发现缺号', message)
