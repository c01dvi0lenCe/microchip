"""B2 software counterexamples only; no camera/serial hardware is opened."""
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from dmf.experiment import evidence
from dmf.experiment.actuator import AMActuator, SerialTransport, DeadlineTransactionClient
from dmf.experiment.policy import Decision
from dmf.experiment.sources import LiveSource, VideoSource
from dmf.vision import contracts
from tests.test_chapter2_runner import make_inputs, read_rows
from dmf.experiment.runner import run_experiment


class CausalityTests(unittest.TestCase):
    def timing(self, **changes):
        self.assertTrue(hasattr(contracts, 'FrameTiming'), 'FrameTiming metadata is missing')
        defaults = dict(capture_frame_id=7, receive_monotonic_ns=1_100_000_000,
                        receive_perf_counter_ns=8_100_000_000, device_ticks_raw=123456,
                        clock_domain='host_monotonic', timing_quality='host_receive')
        defaults.update(changes)
        return contracts.FrameTiming(**defaults)

    def context(self, **changes):
        self.assertTrue(hasattr(evidence, 'StepContext'), 'task identity is implicit')
        defaults = dict(run_id='r', step_index=0, attempt_index=0, epoch=1,
                        source_id=190, target_id=191, applied_receive_ns=1_000_000_000,
                        clock_domain='host_monotonic')
        defaults.update(changes)
        return evidence.StepContext(**defaults)

    def guard(self):
        self.assertTrue(hasattr(evidence, 'FrameCausalityGuard'), 'no task-scoped frame guard')
        return evidence.FrameCausalityGuard()

    def packet(self, frame_id=0, **timing):
        return contracts.FramePacket('v', frame_id, 1.1+frame_id*.1,
                                     'host_receive_monotonic', np.zeros((8, 8, 3), np.uint8),
                                     self.timing(**timing))

    def event(self, context=None, event_id='event'):
        self.assertTrue(hasattr(evidence, 'ArrivalEvent'), 'arrival is not an explicit event')
        return evidence.ArrivalEvent(event_id, context or self.context(), 7, 11, 1.1, 1.5, 1_600_000_000)

    def test_old_packet_constructor_still_works(self):
        packet = contracts.FramePacket('v', 0, 0., 'video_pts', np.zeros((8, 8, 3), np.uint8))
        self.assertTrue(hasattr(packet, 'timing'), 'optional timing seam is missing')
        self.assertIsNone(packet.timing)

    def test_sdk_identity_survives_latest_frame_queue(self):
        ready = threading.Event()
        class Camera:
            def read(self, timeout_s):
                self.last_frame_metadata = dict(sdk_frame_number=987, device_timestamp_raw=2**45+42,
                    host_receive_monotonic_ns=time.monotonic_ns(), host_receive_perf_counter_ns=time.perf_counter_ns())
                ready.set()
                time.sleep(.005)
                return np.zeros((8, 8, 3), np.uint8)
            def close(self): pass
        source = LiveSource({'frame_timeout_s': .2}, factory=Camera)
        try:
            self.assertTrue(ready.wait(.5))
            packet = next(source)
            self.assertTrue(hasattr(packet, 'timing'), 'SDK metadata was discarded')
            self.assertEqual(packet.timing.capture_frame_id, 987)
            self.assertEqual(packet.timing.device_ticks_raw, 2**45+42)
            self.assertIsNotNone(packet.timing.receive_perf_counter_ns)
        finally:
            source.close(); source.worker.join(1)

    def test_recorded_video_retains_raw_anchor_and_sdk_host_stamp(self):
        import csv
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); make_inputs(root,[(190,190,6,6)]*2)
            path=root/'times.csv'
            with path.open('w',encoding='utf8',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=('video_frame_index','sdk_frame_number','device_timestamp_raw',
                    'sdk_host_timestamp_raw','host_receive_monotonic_ns','host_receive_perf_counter_ns','host_utc_ns'))
                writer.writeheader()
                for i in range(2):writer.writerow(dict(video_frame_index=i,sdk_frame_number=900+i,device_timestamp_raw=1234+i,
                    sdk_host_timestamp_raw=4567+i,host_receive_monotonic_ns=1_000_000_000+i*100_000_000,
                    host_receive_perf_counter_ns=8_000_000_000+i*100_000_000,host_utc_ns=10_000_000_000+i*100_000_000))
            source=VideoSource(dict(video=root/'sample.avi',timestamps_csv=path))
            try:
                next(source); packet=next(source)
                self.assertTrue(hasattr(packet.timing,'relative_anchor_perf_counter_ns'))
                self.assertEqual(packet.timing.relative_anchor_perf_counter_ns,8_000_000_000)
                self.assertEqual(packet.timing.sdk_host_timestamp_raw,4568)
                self.assertAlmostEqual(packet.timestamp_s,.1)
            finally:source.close()

    def test_latest_queue_overwrite_count_is_observable(self):
        import queue
        source=LiveSource.__new__(LiveSource); source.queue=queue.Queue(maxsize=1); source.queue_overwrites=0
        source._put('old'); source._put('new')
        self.assertEqual(source.queue_overwrites,1)
        self.assertEqual(source.queue.get_nowait(),'new')

    def test_duplicate_sdk_id_with_new_consumer_index_is_rejected(self):
        guard = self.guard(); context = self.context()
        self.assertTrue(guard.check(self.packet(), context, mode='experiment').accepted)
        assessment = guard.check(self.packet(1), context, mode='experiment')
        self.assertFalse(assessment.accepted)
        self.assertEqual(assessment.reason, 'DUPLICATE_OR_REVERSED_FRAME')

    def test_duplicate_identity_cannot_reenter_after_epoch_switch(self):
        guard = self.guard(); context = self.context()
        guard.check(self.packet(), context, mode='experiment')
        self.assertFalse(guard.check(self.packet(1), replace(context, epoch=2), mode='experiment').accepted)

    def test_estimated_command_return_barrier_is_not_an_actual_ack(self):
        self.assertIn('software_barrier_ns',evidence.StepContext.__dataclass_fields__)
        context=self.context(applied_receive_ns=None,software_barrier_ns=1_000_000_000,
                             applied_time_quality='command_return_estimate')
        a=self.guard().check(self.packet(exposure_start_ns=1_050_000_000,
            exposure_clock_domain='host_monotonic',timing_quality='exposure_mapped'),context,mode='experiment')
        self.assertTrue(a.accepted)
        self.assertEqual(a.causality,'causality_unknown')

    def test_pre_applied_receive_is_rejected(self):
        a = self.guard().check(self.packet(receive_monotonic_ns=900_000_000), self.context(), mode='experiment')
        self.assertFalse(a.accepted)
        self.assertEqual(a.reason, 'PRE_ACTUATION_FRAME')

    def test_receive_after_ack_does_not_prove_exposure_causality(self):
        a = self.guard().check(self.packet(), self.context(), mode='experiment')
        self.assertTrue(a.accepted)
        self.assertEqual(a.causality, 'causality_unknown')

    def test_old_exposure_received_after_ack_is_rejected(self):
        a = self.guard().check(self.packet(exposure_start_ns=900_000_000,
            exposure_clock_domain='host_monotonic', timing_quality='exposure_mapped'), self.context(), mode='experiment')
        self.assertFalse(a.accepted)
        self.assertEqual(a.reason, 'PRE_ACTUATION_EXPOSURE')

    def test_mapped_post_ack_exposure_is_explicit(self):
        a = self.guard().check(self.packet(exposure_start_ns=1_050_000_000,
            exposure_clock_domain='host_monotonic', timing_quality='exposure_mapped'), self.context(), mode='experiment')
        self.assertTrue(a.accepted)
        self.assertEqual(a.causality, 'exposure_order_verified')

    def test_different_clock_domains_are_not_subtracted(self):
        a = self.guard().check(self.packet(clock_domain='device_ticks'), self.context(), mode='experiment')
        self.assertFalse(a.accepted)
        self.assertEqual(a.reason, 'CLOCK_DOMAIN_MISMATCH')

    def test_offline_timestamp_domain_cannot_change_mid_attempt(self):
        packet=self.packet(clock_domain='recorded_host_relative')
        context=self.context(applied_receive_ns=None,clock_domain='video_relative',applied_timestamp_s=1.)
        a=self.guard().check(packet,context,mode='offline')
        self.assertFalse(a.accepted)
        self.assertEqual(a.reason,'CLOCK_DOMAIN_MISMATCH')

    def test_cross_task_packet_is_rejected(self):
        a = self.guard().check(self.packet(task_epoch=0), self.context(), mode='experiment')
        self.assertFalse(a.accepted)
        self.assertEqual(a.reason, 'TASK_EPOCH_MISMATCH')

    def test_exposure_later_than_receive_cannot_be_verified(self):
        a=self.guard().check(self.packet(exposure_start_ns=1_200_000_000,
            exposure_clock_domain='host_monotonic',timing_quality='exposure_mapped'),self.context(),mode='experiment')
        self.assertFalse(a.accepted)
        self.assertEqual(a.reason,'INVALID_EXPOSURE_TIMESTAMP')

    def test_impossible_exposure_is_rejected_before_initial_source_confirmation(self):
        a=self.guard().check(self.packet(exposure_start_ns=1_200_000_000,
            exposure_clock_domain='host_monotonic',timing_quality='exposure_mapped'),
            self.context(applied_receive_ns=None),mode='experiment')
        self.assertFalse(a.accepted)

    def test_confirmed_old_window_cannot_be_relabelled_as_new_context(self):
        old=self.context(); new=replace(old,epoch=2)
        window=evidence.EvidenceWindow(1,0.,.25)
        window.observe((old,'Arrived'),7,1.1,True)
        with self.assertRaises(ValueError):evidence.ArrivalEvent.from_window(new,window,123,'host_monotonic','causality_unknown')

    def test_invalid_timing_metadata_is_rejected(self):
        for changes in (dict(receive_monotonic_ns=-1),dict(exposure_start_ns=float('nan')),
                        dict(capture_frame_id=1.5),dict(queue_overwrites=-1)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.timing(**changes)

    def test_ledger_consumes_step_once_even_with_another_event_id(self):
        self.assertTrue(hasattr(evidence, 'ArrivalEventLedger'), 'no exactly-once ledger')
        ledger = evidence.ArrivalEventLedger(); context = self.context(); ledger.activate(context)
        self.assertTrue(ledger.consume(self.event(context)))
        self.assertFalse(ledger.consume(self.event(context)))
        self.assertFalse(ledger.consume(self.event(context, 'another-confirmation')))

    def test_ledger_rejects_stale_attempt_and_same_pair_on_another_step_is_distinct(self):
        self.assertTrue(hasattr(evidence, 'ArrivalEventLedger'), 'no task event ledger')
        ledger = evidence.ArrivalEventLedger(); old = self.context(); new = replace(old, epoch=2, attempt_index=1)
        ledger.activate(new)
        self.assertFalse(ledger.consume(self.event(old)))
        self.assertTrue(ledger.consume(self.event(new)))
        repeated_pair = replace(new, step_index=2, epoch=3)
        ledger.activate(repeated_pair)
        self.assertTrue(ledger.consume(self.event(repeated_pair, 'revisited-pair')))

    def test_non_hardware_commands_have_no_real_applied_stamp(self):
        for mode in ('offline', 'dry_run'):
            command = AMActuator(mode, {}).execute(Decision('Start', 191))
            self.assertTrue(hasattr(command, 'simulated'), 'simulation acceptance is not distinguished from ACK')
            self.assertTrue(command.simulated)
            self.assertIsNone(command.applied_monotonic_ns)

    def test_observer_returns_actual_applied_receive_not_execute_return_time(self):
        self.assertTrue(hasattr(SerialTransport, '_observe_transaction'), 'APPLIED observer is not captured')
        transport = SerialTransport.__new__(SerialTransport)
        transport.config = {'command_timeout_s': .3}; transport.error = ''; seen = []
        transport._observer = lambda event: (seen.append(event), time.sleep(.005) if event['event']=='applied' else None)
        def send(line):
            parts = line.split(':')
            if parts[0]=='BEGIN': transport.client.feed_line(f'ACK:{parts[1]}:BEGIN')
            elif parts[0]=='SET': transport.client.feed_line(f'ACK:42:SET:{parts[1]}')
            elif parts[0]=='COMMIT': transport.client.feed_line(f'ACK:{parts[1]}:APPLIED')
            return True
        transport.client = DeadlineTransactionClient(send, ack_timeout_s=.1, max_retries=2,
            initial_sequence=42, event_observer=transport._observe_transaction,
            deadline_provider=lambda: transport.deadline, cancelled=lambda: False)
        sequence, ok, error = transport.apply({191: 1})
        self.assertTrue(ok, error); self.assertEqual(sequence, 42)
        received = next(e for e in seen if e.get('line')=='ACK:42:APPLIED')
        self.assertEqual(transport.last_applied_monotonic_ns, received['host_monotonic_ns'])
        self.assertEqual(transport.last_applied_perf_counter_ns, received['host_perf_counter_ns'])
        self.assertLess(transport.last_applied_monotonic_ns, time.monotonic_ns()-1_000_000)
        transport.client._send_line = lambda line: False
        self.assertFalse(transport.apply({192: 1})[1])
        self.assertIsNone(transport.last_applied_monotonic_ns, 'failed ACK must not reuse a prior stamp')

    def test_runner_emits_task_event_and_separate_latency_table(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = run_experiment(make_inputs(root, [(190,190,6,6)]*2+[(210,190,6,6)]*4))
            self.assertEqual(report['status'], 'complete')
            self.assertTrue((root/'results/arrivals.csv').exists(), 'arrival has no explicit identity')
            arrivals = read_rows(root/'results/arrivals.csv')
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(arrivals[0]['consumed'], 'True')
            self.assertEqual(arrivals[0]['causality'], 'offline_replay')
            latencies = read_rows(root/'results/latencies.csv')
            self.assertEqual(len(latencies), report['frames'])
            self.assertTrue(all(row['receive_to_ingest_ms']=='' for row in latencies), 'video time is not host time')
            self.assertTrue(all(row['command_to_applied_ms']=='' for row in latencies), 'offline ACK must stay absent')

    def run_packets(self, root, specs, **overrides):
        config=make_inputs(root,[],**overrides)
        packets=[]
        for i,(x,sdk,epoch) in enumerate(specs):
            image=np.full((400,400,3),255,np.uint8)
            import cv2
            cv2.circle(image,(x,190),6,(0,0,0),-1)
            packets.append(contracts.FramePacket('fixture',i,i*.1,'video_pts',image,
                contracts.FrameTiming(capture_frame_id=sdk,clock_domain='video_relative',timing_quality='video_pts',task_epoch=epoch)))
        class Source:
            def __iter__(self):return iter(packets)
            def close(self):pass
        return run_experiment(config,source_factory=lambda c:Source())

    def test_runner_duplicate_sdk_frame_rebuilds_arrival_window(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            report=self.run_packets(root,[(190,100,0),(210,101,1),(210,101,1),(210,102,1),(210,103,1)],
                control={'source_frames':1,'source_duration_s':0,'wait_s':2.,'max_retries':1,'max_recoveries':1})
            self.assertEqual(report['status'],'complete')
            rows=read_rows(root/'results/frames.csv')
            self.assertEqual([r['event_action'] for r in rows],['Start','Hold','Hold','Hold','Complete'])
            self.assertEqual(rows[2]['error'],'DUPLICATE_OR_REVERSED_FRAME')

    def test_sdk_identity_availability_change_rebuilds_window(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            report=self.run_packets(root,[(190,0,0),(210,1,1),(210,None,1),(210,None,1)],
                control={'source_frames':1,'source_duration_s':0,'wait_s':2.,'max_retries':1,'max_recoveries':1})
            self.assertEqual(report['status'],'complete')
            rows=read_rows(root/'results/frames.csv')
            self.assertEqual(rows[2]['event_action'],'Hold','changing SDK identity availability must not finish old window')
            self.assertEqual(rows[3]['event_action'],'Complete')

    def test_runner_old_epoch_cannot_trigger_next_step(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            report=self.run_packets(root,[(190,100,0),(210,101,1),(210,102,1),
                (230,103,1),(230,104,2),(230,105,2)],route=[190,191,192])
            self.assertEqual(report['status'],'complete')
            rows=read_rows(root/'results/frames.csv')
            self.assertEqual(rows[2]['event_action'],'Update')
            self.assertEqual(rows[3]['error'],'TASK_EPOCH_MISMATCH')
            self.assertEqual(rows[4]['event_action'],'Hold')
            events=read_rows(root/'results/arrivals.csv')
            self.assertEqual([r['step_index'] for r in events],['0','1'])
            self.assertEqual([r['epoch'] for r in events],['1','2'])

    def test_stream_change_cannot_inflate_transport_duration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); config=make_inputs(root,[])
            image=np.full((400,400,3),255,np.uint8)
            import cv2
            cv2.circle(image,(190,190),6,(0,0,0),-1)
            packets=[contracts.FramePacket('a',0,0.,'video_pts',image),
                     contracts.FramePacket('b',0,1000.,'video_pts',image)]
            class Source:
                def __iter__(self):return iter(packets)
                def close(self):pass
            report=run_experiment(config,source_factory=lambda c:Source())
            self.assertEqual(report['status'],'stopped')
            self.assertIn('stream',report['reason'])
            self.assertEqual(float(read_rows(root/'results/steps.csv')[0]['transport_time']),0.)

    def test_next_command_ack_failure_keeps_one_prior_arrival_without_activating_epoch(self):
        from dmf.experiment.actuator import CommandResult
        class Failure(AMActuator):
            def execute(self,d):
                if d.action=='Update':return CommandResult(2,False,False,'mock ACK timeout')
                return super().execute(d)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            report=run_experiment(make_inputs(root,[(190,190,6,6)]*2+[(210,190,6,6)]*4,route=[190,191,192]),
                                  actuator_factory=Failure)
            self.assertEqual(report['status'],'error')
            self.assertEqual(report['arrival_events_consumed'],1)
            self.assertEqual(len(read_rows(root/'results/arrivals.csv')),1)
            commands=read_rows(root/'results/commands.csv')
            failed=next(r for r in commands if r['action']=='Update')
            self.assertIn('requested_epoch',failed)
            self.assertEqual(failed['requested_epoch'],'2')
            self.assertEqual(read_rows(root/'results/frames.csv')[-1]['epoch'],'1')


if __name__ == '__main__': unittest.main()
