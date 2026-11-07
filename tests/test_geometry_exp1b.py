import unittest
from dataclasses import replace
import numpy as np
from dmf.experiment.evidence import StepContext
from dmf.chapter2_geometry_sim.observation import CameraFrame


class Exp1BTests(unittest.TestCase):
    def context(self):
        return StepContext('test',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54)

    def frame(self,i,t,**kwargs):
        return CameraFrame(i,t,t+.008,t+.048,np.ones((4,4),np.uint8)*255,
                           kwargs.get('context',self.context()),kwargs.get('processed',t+.05))

    def features(self,**kwargs):
        return dict(valid=True,x_mm=0.,y_mm=0.,rho_target=.95,eta_source=.05,
                    components=1,touches_roi_border=False,distance_mm=.1,**kwargs)

    def test_six_orthogonal_specs_and_fixed_sixteen_cases(self):
        from dmf.chapter2_geometry_sim.exp1b.spec import METHODS,CASES
        self.assertEqual(len(METHODS),6);self.assertEqual(len(CASES),16)
        self.assertEqual([s.name for s in METHODS],['M1','GQ','M2','M2_S','M2_K','M3'])
        self.assertEqual([(s.q,s.w,s.s,s.k) for s in METHODS],
            [(False,False,False,False),(True,False,False,False),(True,True,False,False),
             (True,True,True,False),(True,True,False,True),(True,True,True,True)])

    def test_single_and_six_frame_window(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor,GateRunner
        from dmf.chapter2_geometry_sim.exp1b.spec import METHODS
        raw=RawAssessor(self.context());runners=[GateRunner(s,self.context()) for s in METHODS]
        for i in range(6):
            f=self.frame(i,.6+i*.05);a=raw.observe(f,self.features())
            for runner in runners:runner.observe(f,a)
        self.assertAlmostEqual(runners[0].event['decision_s'],.65)
        self.assertAlmostEqual(runners[2].event['decision_s'],.9)
        self.assertEqual(runners[2].event['last_frame_id'],5)

    def test_duplicate_rebuilds_without_advancing_or_rewinding_highwater(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor,GateRunner
        from dmf.chapter2_geometry_sim.exp1b.spec import METHODS
        a=RawAssessor(self.context());r=GateRunner(METHODS[2],self.context())
        sequence=[(0,.6),(1,.65),(2,.7),(2,.7),(3,.75),(4,.8),(5,.85)]
        for i,t in sequence:
            f=self.frame(i,t);raw=a.observe(f,self.features());out=r.observe(f,raw)
            if (i,t)==(2,.7) and raw['c0_reason']:
                self.assertFalse(raw['C0']);self.assertEqual(out['window_count'],0)
        self.assertIsNone(r.event)
        self.assertFalse(a.observe(self.frame(1,.65),self.features())['C0'])

    def test_old_context_preapplied_empty_and_bad_time_common_rejection(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor
        bad=[(self.frame(0,.6,context=replace(self.context(),epoch=0)),self.features()),
             (self.frame(0,.5),self.features()),(self.frame(0,.6),{'valid':False}),
             (self.frame(0,float('nan')),self.features())]
        for f,x in bad:self.assertFalse(RawAssessor(self.context()).observe(f,x)['C0'])

    def test_event_consumed_once(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor,GateRunner
        from dmf.chapter2_geometry_sim.exp1b.spec import METHODS
        a=RawAssessor(self.context());r=GateRunner(METHODS[0],self.context());count=0
        for i in range(10):
            f=self.frame(i,.6+.05*i);count+=r.observe(f,a.observe(f,self.features()))['new_event']
        self.assertEqual(count,1)

    def test_raw_k_shared_independent_of_quality_or_coverage(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor
        a=RawAssessor(self.context())
        a.observe(self.frame(0,.6),self.features())
        x=self.features();x.update(x_mm=1.2,components=2,rho_target=.1)
        out=a.observe(self.frame(1,.65),x)
        self.assertFalse(out['K']);self.assertFalse(out['Q']);self.assertFalse(out['G'])
        self.assertAlmostEqual(out['raw_speed_mm_s'],24.)
        next_x=self.features();next_x.update(x_mm=1.2)
        self.assertTrue(a.observe(self.frame(2,.7),next_x)['K'])

    def test_gap_resets_k_and_window(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor,GateRunner
        from dmf.chapter2_geometry_sim.exp1b.spec import METHODS
        a=RawAssessor(self.context());r=GateRunner(METHODS[-1],self.context())
        for i,t in [(0,.6),(1,.65),(6,.9)]:
            f=self.frame(i,t);out=r.observe(f,a.observe(f,self.features()))
        self.assertEqual(out['window_count'],1);self.assertIsNone(r.event)

    def test_q_and_s_are_not_invented_confidence_or_corridor_gates(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor
        x=self.features();x.update(components=2,distance_mm=.6)
        out=RawAssessor(self.context()).observe(self.frame(0,.6),x)
        self.assertTrue(out['C0']);self.assertTrue(out['G']);self.assertFalse(out['Q']);self.assertFalse(out['S'])

    def test_reference_scoring_null_premature_supported_departure(self):
        from dmf.chapter2_geometry_sim.exp1b.evaluate import score_event
        ref={'intervals':[dict(start_s=4.57,end_s=6.,confirmed_s=4.72)]}
        self.assertEqual(score_event(None,ref,10)['missed_references'],1)
        x=score_event({'decision_s':4.65},ref,10)
        self.assertEqual(x['category'],'premature');self.assertEqual(x['timing_region'],'dwell_building')
        self.assertEqual(x['missed_references'],1)
        self.assertEqual(score_event({'decision_s':4.8},ref,10)['category'],'supported')
        self.assertEqual(score_event({'decision_s':6.1},ref,10)['category'],'unsupported')
        self.assertEqual(score_event({'decision_s':2},dict(intervals=[]),10)['category'],'unsupported')

    def test_incomplete_reference_dwell_is_not_fabricated_arrival(self):
        from dmf.chapter2_geometry_sim.exp1b.evaluate import score_event
        x=score_event(None,dict(intervals=[dict(start_s=9.95,end_s=10,confirmed_s=None)]),10)
        self.assertEqual(x['reference_arrivals'],0);self.assertTrue(x['reference_dwell_censored'])

    def test_declared_mask_and_delivery_changes_are_real(self):
        from dmf.chapter2_geometry_sim.exp1b.generate import alter_mask,delivery_plan
        mask=np.zeros((60,100),np.uint8);mask[10:50,20:80]=255
        fragmented=alter_mask('C4',mask,4.3,np.array([0,0]),mask)
        import cv2
        self.assertEqual(cv2.connectedComponents(fragmented)[0]-1,2)
        self.assertLess(alter_mask('C3',mask,4.3,np.array([0,0]),mask).sum(),mask.sum())
        self.assertEqual(delivery_plan('D1',88,4.4,4.45),[])
        self.assertEqual(len(delivery_plan('D3',88,4.4,4.45)),2)
        self.assertAlmostEqual(delivery_plan('D4',88,4.4,4.45)[0]['processed_s'],4.75)

    def test_motion_variants_keep_activation_and_do_not_fabricate_stall_arrival(self):
        from dmf.chapter2_geometry_sim.exp1b.generate import make_kinematics
        base=[];previous=0.
        for i in range(601):
            t=i*.01;u=min(1,max(0,(t-.72)/(1.875*3.2/1.4)))
            q=10*u**3-15*u**4+6*u**5;x=3.2*q
            base.append(dict(time_s=t,x_mm=x,y_mm=0.,speed_mm_s=(x-previous)/.01 if i else 0.,
                active=191 if t>=.54 else 190,response_at_s=.72,activation_segment=int(t>=.54)))
            previous=x
        for name in ('normal','slow','pause','stall'):
            world=make_kinematics(base,name)
            self.assertEqual(len(world),1001)
            self.assertTrue(all(r['x_mm']==0 for r in world if r['time_s']<=.72))
            self.assertTrue(all(r['active']==191 for r in world if r['time_s']>=.54))
            self.assertLessEqual(max(r['speed_mm_s'] for r in world),(.7 if name=='slow' else 1.4)+1e-3)
            if name=='stall':self.assertLess(world[-1]['x_mm'],2.)
            else:self.assertAlmostEqual(world[-1]['x_mm'],3.2)

    def test_raw_finite_centroid_required_for_common_integrity(self):
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor
        x=self.features();x['x_mm']=float('nan')
        self.assertFalse(RawAssessor(self.context()).observe(self.frame(0,.6),x)['C0'])

    def test_independent_reference_rebuild_after_leaving_and_gap(self):
        from dmf.chapter2_geometry_sim.exp1b.audit import reference_from_world
        world=[]
        for i in range(41):
            t=.54+i*.01
            world.append(dict(time_s=t,x_mm=0. if i<20 or i>24 else 2.,y_mm=0.,speed_mm_s=0.,active=191))
        ref=reference_from_world(world,(0.,0.))
        self.assertEqual(len(ref['intervals']),2)
        self.assertAlmostEqual(ref['intervals'][0]['confirmed_s'],.69)
        self.assertAlmostEqual(ref['intervals'][1]['confirmed_s'],.94)

    def test_independent_window_event_hand_calculation(self):
        from dmf.chapter2_geometry_sim.exp1b.audit import manual_first_event
        rows=[dict(frame_id=i,exposure_start_s=.6+i*.05,processed_at_s=.65+i*.05,
                   C0=True,G=True,Q=True,S=True,K=True) for i in range(6)]
        self.assertAlmostEqual(manual_first_event(rows,True,True,False,False),.9)
        rows.insert(3,dict(rows[2]))
        rows[3]['C0']=False
        self.assertIsNone(manual_first_event(rows,True,True,False,False))

    def test_world_generation_failure_keeps_six_planned_denominators(self):
        from dmf.chapter2_geometry_sim.exp1b.generate import unattempted_results
        from dmf.chapter2_geometry_sim.exp1b.spec import CASES
        records=unattempted_results(CASES[1],'invalid interpolated polygon')
        self.assertEqual(len(records),6)
        self.assertEqual(sum(r['planned_steps'] for r in records),6)
        self.assertTrue(all(r['unattempted'] and r['status']=='world_generation_failed' for r in records))
        self.assertTrue(all(r['reference_arrivals'] is None for r in records))


if __name__=='__main__':unittest.main()
