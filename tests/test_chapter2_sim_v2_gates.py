"""Research-only v2 gate contracts. Production modules must remain unchanged."""
from dataclasses import replace
import itertools
import unittest

import cv2
import numpy as np

try:
    from dmf.chapter2_sim.v2.spec import StudySpecV2, FactorFlags, method_flags
    from dmf.chapter2_sim.v2.adapter import ResearchAdapter
except ImportError:
    StudySpecV2 = None

from dmf.chapter2_sim.config import SimConfig
from dmf.chapter2_sim.geometry import SimulationMap
from dmf.chapter2_sim.vision import SyntheticFrame


class V2GateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(StudySpecV2, 'v2 research interface missing')
        self.spec=StudySpecV2()
        self.geometry=SimulationMap(self.spec.environment)

    def frame(self,i,t,point=None,confidence=1.):
        point=self.geometry.center(191) if point is None else np.array(point)
        mask=np.zeros(self.geometry.shape,np.uint8)
        cv2.circle(mask,tuple(np.rint(self.geometry.to_pixel(point)).astype(int)),12,255,-1)
        from dmf.chapter2_sim.v2.observation import ObservedFrame
        return ObservedFrame(i,t,t+.008,t+.05,mask,confidence=confidence)

    def adapter(self,method='F',flags=None):
        a=ResearchAdapter(self.spec,self.geometry,method,flags=flags,run_id='probe')
        a.begin_transport(.04)
        return a

    def test_btq_and_f_have_exact_same_window_contract(self):
        b,f=self.adapter('BTQ'),self.adapter('F')
        self.assertEqual(b.arrival.contract,f.arrival.contract)
        self.assertEqual(method_flags('BTQ'),FactorFlags(S=False,K=False))
        self.assertEqual(method_flags('BT'),FactorFlags(S=False,K=False,Q=False))

    def test_single_frame_insufficient_shared_window_confirms_same_frame(self):
        methods=[self.adapter(m) for m in ('BT','BTQ','F')]
        event_ids=[]
        for a in methods:
            outcomes=[a.observe(self.frame(i,.1+i*.05),.15+i*.05) for i in range(6)]
            self.assertIsNone(outcomes[0].arrival_event)
            self.assertIsNotNone(outcomes[-1].arrival_event)
            self.assertEqual(outcomes[-1].arrival_event.first_frame_id,0)
            event_ids.append(outcomes[-1].arrival_event.last_frame_id)
        self.assertEqual(event_ids,[5,5,5])

    def test_duplicate_cannot_build_evidence(self):
        a=self.adapter()
        a.observe(self.frame(0,.1),.15)
        out=a.observe(self.frame(0,.15),.2)
        self.assertFalse(a.last_trace['C0_passed'])
        self.assertEqual(a.arrival.window.count,0)
        self.assertIsNone(out.arrival_event)

    def test_old_exposure_cannot_confirm_under_any_flags(self):
        for bits in itertools.product((False,True),repeat=4):
            a=self.adapter(flags=FactorFlags(*bits))
            out=a.observe(self.frame(0,.01),.06)
            self.assertFalse(a.last_trace['C0_passed'])
            self.assertIsNone(out.arrival_event)

    def test_all_switches_leave_raw_values_identical(self):
        traces=[]
        for bits in itertools.product((False,True),repeat=4):
            a=self.adapter(flags=FactorFlags(*bits))
            for i,point in enumerate([(10.4,9.5),(10.5,9.5),(9.55,9.5)]):
                a.observe(self.frame(i,.1+i*.05,point,.1 if i==2 else 1.),.15+i*.05)
            traces.append(a.last_trace['raw'])
        self.assertTrue(all(t==traces[0] for t in traces))

    def test_quality_off_does_not_disable_motion_gate(self):
        a=self.adapter(flags=FactorFlags(Q=False))
        a.observe(self.frame(0,.1,(9.5,9.5)),.15)
        a.observe(self.frame(1,.15,(10.5,9.5),.01),.2)
        self.assertFalse(a.last_trace['raw']['K'])
        self.assertFalse(a.last_trace['raw']['Q'])
        self.assertFalse(a.last_trace['eligible'])

    def test_long_gap_rebuilds_confirmation(self):
        a=self.adapter()
        for i in range(5):a.observe(self.frame(i,.1+i*.05),.15+i*.05)
        out=a.observe(self.frame(5,1.),1.05)
        self.assertIsNone(out.arrival_event)
        self.assertEqual(a.arrival.window.count,1)
        self.assertIn('long_gap',a.last_trace['rebuild_reasons'])

    def test_invalid_mask_never_allowed_even_all_flags_off(self):
        a=self.adapter(flags=FactorFlags(False,False,False,False))
        out=a.observe(replace(self.frame(0,.1),mask=None),.15)
        self.assertFalse(a.last_trace['C0_passed'])
        self.assertIsNone(out.arrival_event)

    def test_event_only_consumed_on_accepted_issued_update(self):
        a=self.adapter('BTQ')
        for i in range(6):out=a.observe(self.frame(i,.1+i*.05),.15+i*.05)
        d=out.decision
        self.assertEqual(d.action,'Update')
        self.assertFalse(a.accept(d,.44,accepted=False))
        self.assertTrue(a.accept(d,.44))
        self.assertFalse(a.accept(d,.44))
        self.assertEqual(a.context.epoch,2)

    def test_source_config_not_changed_by_target_switches(self):
        for bits in itertools.product((False,True),repeat=4):
            a=self.adapter(flags=FactorFlags(*bits))
            self.assertEqual(a.source_contract,self.spec.source)
            self.assertEqual(a.recovery_contract,self.spec.recovery)

    def test_clock_epoch_and_nonmonotone_time_remain_mandatory(self):
        for bits in itertools.product((False,True),repeat=4):
            flags=FactorFlags(*bits)
            for change in ({'clock_domain':'host_monotonic'},{'task_epoch':0}):
                a=self.adapter(flags=flags);out=a.observe(replace(self.frame(0,.1),**change),.15)
                self.assertFalse(a.last_trace['C0_passed']);self.assertIsNone(out.arrival_event)
            a=self.adapter(flags=flags);a.observe(self.frame(0,.2),.25)
            out=a.observe(self.frame(1,.1),.3)
            self.assertFalse(a.last_trace['C0_passed']);self.assertIsNone(out.arrival_event)

    def test_target_window_off_cannot_shorten_source_preparation(self):
        a=ResearchAdapter(self.spec,self.geometry,'F',flags=FactorFlags(False,False,False,False))
        a.context=replace(a.context,applied_timestamp_s=.04);a.ledger.activate(a.context)
        for i in range(2):
            out=a.observe(self.frame(i,.1+i*.05,self.geometry.center(190)),.15+i*.05)
            self.assertEqual(out.decision.action,'Hold')
        self.assertEqual(a.phase,'confirm_source')

    def test_switches_do_not_rewrite_protection_observations(self):
        snapshots=[]
        for bits in itertools.product((False,True),repeat=4):
            a=self.adapter(flags=FactorFlags(*bits))
            out=a.observe(self.frame(0,.1,(11.5,9.5),.1),.15)
            snapshots.append(out.observation)
        self.assertTrue(all(v==snapshots[0] for v in snapshots))
        self.assertFalse(snapshots[0].valid)
        self.assertFalse(snapshots[0].spatial_ok)

    def test_spatial_switch_does_not_suppress_recovery_before_arrival(self):
        sequences=[]
        for enabled in (False,True):
            a=self.adapter(flags=FactorFlags(S=enabled))
            sequence=[]
            for i in range(4):
                out=a.observe(self.frame(i,.1+i*.05,(11.5,9.5)),.15+i*.05)
                sequence.append((out.state,out.decision.action,out.observation))
            sequences.append(sequence)
        self.assertEqual(sequences[0],sequences[1])
        self.assertIn('Recovery',[r[1] for r in sequences[0]])


if __name__=='__main__':unittest.main()
