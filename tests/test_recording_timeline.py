import csv
import ctypes
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import yaml

from dmf.recording import (AsyncCsvLog, ElectrodeEventStream, RecordingJournal,
    FRAME_FIELDS, load_recorded_timestamps, sidecar_paths)
from dmf.experiment.sources import VideoSource, LiveSource
from dmf.experiment.mvs_camera import MvsCamera
from tests.test_mvs_camera import PixelTypes
from dmf.vision.cli import extract_frames
from dmf.vision.pipeline import run_baseline


def rows(path):
    with Path(path).open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def frame(stamp):
    return dict(sdk_frame_number=10, device_timestamp_raw=55, sdk_host_timestamp_raw=66,
        host_receive_monotonic_ns=stamp, host_utc_ns=100000000000,
        host_receive_perf_counter_ns=stamp,
        timestamp_source='host_receive_perf_counter', input_completed_monotonic_ns=stamp+5,
        width=16, height=16, pixel_type=1)


def event(kind, stamp, request='r1', **values):
    return dict(event=kind, host_monotonic_ns=stamp, host_perf_counter_ns=stamp, host_utc_ns=100000000000,
        request_id=request, **values)


class RecordingTimelineTests(unittest.TestCase):
    def make_video(self, path, count=4):
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 20, (16,16))
        self.assertTrue(writer.isOpened())
        for index in range(count):
            writer.write(np.full((16,16,3), index*30, dtype=np.uint8))
        writer.release()

    def test_recorded_time_not_container_fps_and_state_alignment(self):
        stream = ElectrodeEventStream()
        stream.emit(event('all_off_confirmed', time.monotonic_ns()))
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder)/'test.avi'
            self.make_video(video)
            journal = RecordingJournal(video, 20, stream)
            start = time.perf_counter_ns()+1000000
            journal.add_frame(frame(start))
            stream.emit(event('transaction_requested', start+50000000, changes={420:1, 1:1}))
            journal.add_frame(frame(start+100000000))
            stream.emit(event('applied', start+150000000, changes={420:1, 1:1}))
            journal.add_frame(frame(start+300000000))
            stream.emit(event('all_off_requested', start+350000000, request='r2'))
            stream.emit(event('all_off_confirmed', start+400000000, request='r2'))
            journal.add_frame(frame(start+450000000))
            journal.close()
            self.assertFalse(journal.log.worker.is_alive())
            manifest=json.loads(journal.paths['manifest'].read_text())
            self.assertEqual(manifest['status'], 'complete')
            self.assertEqual(manifest['recorded_frames'], 4)
            aligned=rows(journal.paths['alignment'])
            self.assertEqual([r['state_status'] for r in aligned],
                ['confirmed', 'pending', 'confirmed', 'confirmed'])
            self.assertEqual(json.loads(aligned[2]['confirmed_active_ids']), [1,420])
            self.assertEqual(json.loads(aligned[3]['confirmed_active_ids']), [])
            source=VideoSource({'video':video})
            try:packets=list(source)
            finally:source.close()
            self.assertEqual([p.timestamp_s for p in packets], [0,.1,.3,.45])
            self.assertEqual({p.timestamp_source for p in packets}, {'host_receive_perf_counter'})
            extracted=extract_frames(video,'test',Path(folder)/'extract')
            self.assertEqual([float(r['timestamp_s']) for r in rows(extracted)],[0,.1,.3,.45])
            (Path(folder)/'map.yaml').write_text(yaml.safe_dump(dict(rows=20,cols=20,
                pitch_mm=1,core_corners_px=[[0,0],[16,0],[16,16],[0,16]])))
            config=dict(video=dict(path='test.avi',video_id='v',batch_id='b',split='test'),
                electrode_map='map.yaml',output_dir='baseline',
                algorithm=dict(name='threshold',parameters=dict(color_space='gray',lower=[0],upper=[50],min_area_px=1)))
            config_path=Path(folder)/'baseline.yaml';config_path.write_text(yaml.safe_dump(config))
            results,_=run_baseline(config_path)
            self.assertEqual([float(r['timestamp_s']) for r in rows(results)],[0,.1,.3,.45])

    def test_unknown_initial_and_failed_ack_stay_unknown(self):
        stream=ElectrodeEventStream()
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'unknown.avi';self.make_video(video,3)
            journal=RecordingJournal(video, 20, stream)
            start=time.perf_counter_ns()+1000
            journal.add_frame(frame(start))
            stream.emit(event('transaction_requested', start+1, changes={3:1}))
            stream.emit(event('applied', start+2, changes={3:1}))
            journal.add_frame(frame(start+3))
            stream.emit(event('all_off_confirmed', start+4))
            stream.emit(event('transaction_requested', start+5, changes={3:1}))
            stream.emit(event('transaction_failed', start+6, changes={3:1}))
            journal.add_frame(frame(start+7))
            journal.close()
            self.assertEqual([r['state_status'] for r in rows(journal.paths['alignment'])],
                ['unknown','unknown','unknown'])

    def test_recording_started_during_transaction_marks_pending(self):
        stream=ElectrodeEventStream()
        stream.emit(event('all_off_confirmed',time.monotonic_ns()))
        stream.emit(event('transaction_requested',time.monotonic_ns(), changes={8:1}))
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'pending.avi';self.make_video(video,1)
            journal=RecordingJournal(video,20,stream)
            journal.add_frame(frame(time.perf_counter_ns()))
            journal.close()
            self.assertEqual(rows(journal.paths['alignment'])[0]['state_status'],'pending')

    def test_invalid_missing_or_nonmonotonic_timestamps_never_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'bad.avi'
            self.assertIsNone(load_recorded_timestamps(video))
            with self.assertRaises(FileNotFoundError):load_recorded_timestamps(video,Path(folder)/'missing.csv')
            paths=sidecar_paths(video)
            paths['manifest'].write_text(json.dumps({'status':'complete'}))
            with self.assertRaisesRegex(ValueError,'missing'):load_recorded_timestamps(video)
            for times,ids in [([12,12],[0,1]),([12,11],[0,1]),([12,15],[0,2])]:
                with paths['timestamps'].open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=FRAME_FIELDS);writer.writeheader()
                    for stamp,index in zip(times,ids):writer.writerow(dict(frame(stamp),video_frame_index=index))
                with self.assertRaises(ValueError):load_recorded_timestamps(video)

    def test_frame_count_mismatch_is_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'bad.avi';self.make_video(video)
            journal=RecordingJournal(video,20)
            journal.add_frame(frame(time.monotonic_ns()))
            with self.assertRaisesRegex(OSError,'mismatch'):journal.close()
            self.assertEqual(json.loads(journal.paths['manifest'].read_text())['status'],'incomplete')
            with self.assertRaisesRegex(ValueError,'incomplete'):VideoSource({'video':video})

    def test_queue_overflow_is_explicit_and_does_not_block_producer(self):
        with tempfile.TemporaryDirectory() as folder:
            log=AsyncCsvLog({'events':(Path(folder)/'events.csv',('value',))},capacity=1)
            entered,release=threading.Event(),threading.Event()
            original=log.writers['events'].writerow
            def slow(row):
                entered.set();release.wait(2);original(row)
            log.writers['events'].writerow=slow
            try:
                log.append('events',{'value':1})
                self.assertTrue(entered.wait(1))
                started=time.monotonic()
                log.append('events',{'value':2});log.append('events',{'value':3})
                self.assertLess(time.monotonic()-started,.1)
                self.assertIn('overflow',log.error)
            finally:release.set();log.close()

    def test_disk_failure_is_reported_and_writer_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            log=AsyncCsvLog({'events':(Path(folder)/'events.csv',('value',))})
            log.writers['events'].writerow=lambda row: (_ for _ in ()).throw(OSError('disk full'))
            log.append('events',{'value':1});log.close()
            self.assertIn('disk full',log.error)
            self.assertFalse(log.worker.is_alive())

    def test_live_packet_uses_receive_time_before_expensive_conversion(self):
        class Camera:
            def __init__(self):self.received=[]
            def read(self,timeout_s):
                self.last_frame_metadata={'host_receive_monotonic_ns':time.monotonic_ns()}
                self.received.append(self.last_frame_metadata['host_receive_monotonic_ns'])
                time.sleep(.02)
                return np.zeros((8,8,3),np.uint8)
            def close(self):pass
        camera=Camera()
        source=LiveSource({'frame_timeout_s':.2},factory=lambda:camera)
        try:
            packet=next(source)
            self.assertIn(packet.timestamp_s,[stamp/1e9 for stamp in camera.received])
            self.assertEqual(packet.timestamp_source,'host_receive_monotonic')
        finally:source.close();source.worker.join(1)

    def test_sdk_raw_ticks_are_not_mislabelled_as_seconds(self):
        raw=ctypes.create_string_buffer(bytes(16))
        info=SimpleNamespace(nFrameLen=16,nWidth=4,nHeight=4,enPixelType=1,
            nFrameNum=987,nDevTimeStampHigh=2,nDevTimeStampLow=42,nHostTimeStamp=123)
        def get_buffer(out,timeout):
            out.stFrameInfo=info;out.pBufAddr=ctypes.addressof(raw);return 0
        camera=MvsCamera.__new__(MvsCamera)
        camera.closed=False;camera.started=True;camera.recording=True
        camera.headers=SimpleNamespace(MV_FRAME_OUT=SimpleNamespace)
        camera.pixels=PixelTypes
        camera.camera=SimpleNamespace(MV_CC_GetImageBuffer=get_buffer,MV_CC_FreeImageBuffer=lambda f:0)
        camera._input_record_frame=lambda f:None
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'sdk.avi';self.make_video(video,1)
            camera.recording_journal=RecordingJournal(video,20)
            before=time.monotonic_ns();image=camera.read(.1);after=time.monotonic_ns()
            camera.recording_journal.close()
            row=rows(camera.recording_journal.paths['timestamps'])[0]
            self.assertEqual(int(row['device_timestamp_raw']),(2<<32)|42)
            self.assertEqual(int(row['sdk_frame_number']),987)
            self.assertEqual(int(row['sdk_host_timestamp_raw']),123)
            self.assertTrue(before<=int(row['host_receive_monotonic_ns'])<=after)
            self.assertEqual(image.shape,(4,4,3))
            metadata=json.loads(camera.recording_journal.paths['manifest'].read_text())
            self.assertEqual(metadata['device_timestamp_unit'],'unknown_raw_ticks')

    def test_missing_avi_is_not_reported_as_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=RecordingJournal(Path(folder)/'missing.avi',20)
            journal.add_frame(frame(time.monotonic_ns()))
            with self.assertRaisesRegex(OSError,'not created'):journal.close()
            self.assertEqual(json.loads(journal.paths['manifest'].read_text())['status'],'incomplete')

    def test_high_resolution_clock_preserves_sub_tick_intervals(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'fast.avi';self.make_video(video,2)
            journal=RecordingJournal(video,20)
            start=time.perf_counter_ns()
            first=frame(start);second=frame(start+5000000)
            first['host_receive_monotonic_ns']=second['host_receive_monotonic_ns']=time.monotonic_ns()
            journal.add_frame(first);journal.add_frame(second);journal.close()
            self.assertEqual(load_recorded_timestamps(video),[0,.005])

    def test_closed_camera_command_fails_without_waiting_forever(self):
        class Camera:
            def read(self,timeout_s):time.sleep(.01);return np.zeros((4,4,3),np.uint8)
            def close(self):pass
        source=LiveSource({'frame_timeout_s':.1},factory=Camera)
        source.close();source.worker.join(1)
        with self.assertRaisesRegex(RuntimeError,'closed'):
            source.submit_camera_command('start_recording','test.avi').result(timeout=.1)


if __name__=='__main__':unittest.main()
