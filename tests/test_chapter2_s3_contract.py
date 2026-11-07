import unittest
from dataclasses import replace
import numpy as np
import cv2
from dmf.chapter2_sim.geometry import SimulationMap
from dmf.chapter2_sim.v2.observation import ObservedFrame
try:
    from dmf.chapter2_sim.s3.spec import S3Spec, development_plan
    from dmf.chapter2_sim.s3.adapter import S3Adapter, TransactionSlot
    from dmf.chapter2_sim.s3.evaluation import terminal_class
except ImportError:
    S3Spec=S3Adapter=TransactionSlot=terminal_class=None

class S3ContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(S3Spec,'S3 strategy interfaces missing')
        self.spec=S3Spec();self.g=SimulationMap(self.spec.common.environment)
    def frame(self,i,t,point=None,epoch=None,confidence=1.):
        mask=np.zeros(self.g.shape,np.uint8)
        cv2.circle(mask,tuple(np.rint(self.g.to_pixel(self.g.center(191) if point is None else point)).astype(int)),12,255,-1)
        return ObservedFrame(i,t,t+.008,t+.05,mask,confidence=confidence,task_epoch=epoch)
    def adapter(self,method='BTQ',protection=None):
        a=S3Adapter(self.spec,self.g,method,protection=protection,run_id='test');a.begin_transport(.04);return a
    def test_plan_exactly_84_12_24_and_only_development_seeds(self):
        plan=development_plan();self.assertEqual(len(plan),120)
        self.assertEqual([sum(r['cohort']==v for r in plan) for v in ('main','bridge','diagnostic')],[84,12,24])
        self.assertEqual(set(r['seed'] for r in plan),{264000,264001,264002})
        for seed in (263000,265000,265019):
            with self.assertRaises(ValueError):self.spec.validate_seed(seed)
    def test_all_groups_share_source_gate(self):
        values=[S3Adapter(self.spec,self.g,m).source_contract for m in ('A_fixed','B_single','BTQ','F_full')]
        self.assertTrue(all(v==values[0] for v in values))
    def test_fixed_baseline_has_no_visual_arrival_event(self):
        a=self.adapter('A_fixed')
        for i in range(8):self.assertIsNone(a.observe(self.frame(i,.1+i*.05),.15+i*.05).arrival_event)
        self.assertEqual(a.tick(1.23).action,'Hold')
        decision=a.tick(1.24);self.assertEqual(decision.action,'Update');self.assertIsNone(decision.arrival_event_id)
    def test_single_frame_and_strong_window_differ_but_raw_history_does_not(self):
        a,b=self.adapter('B_single'),self.adapter('BTQ')
        x=a.observe(self.frame(0,.1),.15);y=b.observe(self.frame(0,.1),.15)
        self.assertEqual(x.decision.action,'Update');self.assertEqual(y.decision.action,'Hold')
        self.assertEqual(a.last_trace['raw'],b.last_trace['raw'])
        self.assertEqual(list(a.pipeline.history),list(b.pipeline.history))
    def test_sk_switches_do_not_change_common_protection_inputs(self):
        a,b=self.adapter('BTQ'),self.adapter('F_full',protection='P_B')
        for i,p in enumerate(((9.5,9.5),(10.5,9.5),(10.5,10.3))):
            x=a.observe(self.frame(i,.1+.05*i,p,confidence=.1 if i==2 else 1.),.15+.05*i)
            y=b.observe(self.frame(i,.1+.05*i,p,confidence=.1 if i==2 else 1.),.15+.05*i)
            self.assertEqual(x.observation,y.observation)
            self.assertEqual(a.last_trace['raw'],b.last_trace['raw'])
    def test_duplicate_reverse_and_old_epoch_do_not_progress(self):
        for modified in ('duplicate','reverse','epoch'):
            a=self.adapter();a.observe(self.frame(2,.2),.25)
            f=self.frame(2,.25) if modified=='duplicate' else self.frame(3,.15) if modified=='reverse' else self.frame(3,.25,epoch=0)
            o=a.observe(f,.3);self.assertIsNone(o.arrival_event);self.assertFalse(a.last_trace['C0_passed']);self.assertEqual(a.arrival.window.count,0)
    def test_pending_slot_rejects_second_command_and_wrong_completion(self):
        s=TransactionSlot();self.assertTrue(s.reserve('request-1'));self.assertFalse(s.reserve('request-2'))
        self.assertFalse(s.release('request-2'));self.assertTrue(s.release('request-1'))
    def test_failed_applied_does_not_commit_or_consume_event(self):
        a=self.adapter()
        for i in range(6):o=a.observe(self.frame(i,.1+i*.05),.15+i*.05)
        self.assertEqual(o.decision.action,'Update');before=a.context
        self.assertFalse(a.accept(o.decision,.44,False));self.assertEqual(a.context,before)
        self.assertTrue(a.accept(o.decision,.44));self.assertFalse(a.accept(o.decision,.44))
    def test_terminals_are_mutually_exclusive(self):
        self.assertEqual(terminal_class(invalid=True,prepared=True,workflow=True,path=True),'infrastructure_invalid')
        self.assertEqual(terminal_class(prepared=False),'source_preparation_failed')
        self.assertEqual(terminal_class(prepared=True),'transport_aborted')
        self.assertEqual(terminal_class(prepared=True,workflow=True),'workflow_complete_without_supported_path')
        self.assertEqual(terminal_class(prepared=True,workflow=True,path=True),'reference_supported_path_complete')
    def test_bounded_retry_recovery_branch_has_seven_applied_upper_bound(self):
        from dmf.experiment.perception import Observation
        from dmf.vision.contracts import DropletState as S
        a=self.adapter();c=a.controller;t=.04;actions=['Start']
        observation=Observation(valid=True,centroid=(9.5,9.5),area=500,eta_source=1.,eta_target=0.,distance=1.,progress_mm=0.,spatial_ok=True,temporal_ok=True)
        for expected in ('Retry','Retry','Recovery','Retry','Retry','Retry','Stop'):
            if c.phase=='recovering':
                t+=.4;d=c.decide(S.UNKNOWN,t,True,observation=observation)
            else:
                t+=2.61;d=c.decide(S.MOVING,t,observation=observation)
            self.assertEqual(d.action,expected)
            c.accept(d,t)
            if d.action!='Stop':actions.append(d.action)
        self.assertEqual(len(actions),7);self.assertEqual(c.index,0)
        self.assertEqual(c.phase,'stopped');self.assertEqual(c.recovery_total,1)
    def test_pf_and_pb_bridge_separates_persistent_deviation_protection(self):
        b=self.adapter('BTQ');f=self.adapter('BTQ',protection='P_F')
        for i in range(3):
            x=b.observe(self.frame(i,.1+.05*i,(10.5,10.3)),.15+.05*i)
            y=f.observe(self.frame(i,.1+.05*i,(10.5,10.3)),.15+.05*i)
            self.assertEqual(x.observation,y.observation)
        self.assertEqual(x.decision.action,'Hold');self.assertEqual(y.decision.action,'Recovery')

if __name__=='__main__':unittest.main()
