"""Random-protocol development contracts; no formal study seeds executed."""
import math
import unittest
import numpy as np


class RandomProtocolTests(unittest.TestCase):
    def test_approved_base_digest_cannot_be_replaced_with_matching_tampered_digest(self):
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol,DEFAULT_CONFIG
        import json,tempfile,hashlib
        from pathlib import Path
        wrapper=json.loads(DEFAULT_CONFIG.read_text(encoding='utf-8'))
        base=json.loads((DEFAULT_CONFIG.parent/wrapper['extends']).read_text(encoding='utf-8'))
        base['motion']['normal_peak_speed_mm_s']['range']=[99.,100.]
        base['conditions'].append(dict(id='EXTRA',world='normal',observation='clean',strata='base'))
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);proposal=temp/'proposal.json';proposal.write_text(json.dumps(base),encoding='utf-8')
            wrapper.update(extends=str(proposal),base_sha256=hashlib.sha256(proposal.read_bytes()).hexdigest())
            file=temp/'wrapper.json';file.write_text(json.dumps(wrapper),encoding='utf-8')
            with self.assertRaises(ValueError):load_protocol(file)

    def test_approved_tf_revision_and_development_limits_are_exact(self):
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol,DEFAULT_CONFIG
        import copy,json,tempfile
        from pathlib import Path
        original=json.loads(DEFAULT_CONFIG.read_text(encoding='utf-8'))
        original['extends']=str((DEFAULT_CONFIG.parent/original['extends']).resolve())
        mutations=[('development_max_unique_seeds',3),('development_max_caches',25),
                   ('development_seed_slots',{'268000':1,'268001':10}),
                   ('development_seed_slots',{'268000':False,'268001':10}),('formal_execution_allowed',True)]
        mutations += [('TF_revision.'+k,v) for k,v in [('fixed_offset_s',.3),
            ('consecutive_frames',{'low':[1,3],'high':[7,12]}),('no_redraw',False),('no_redraw',1),
            ('require_entire_episode_after_stall',False),('start_rule','progress'),('persist_times',[])]]
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'wrapper.json'
            for key,value in mutations:
                wrapper=copy.deepcopy(original)
                if '.' in key:wrapper['TF_revision'][key.split('.')[1]]=value
                else:wrapper[key]=value
                file.write_text(json.dumps(wrapper),encoding='utf-8')
                with self.subTest(key=key),self.assertRaises(ValueError):load_protocol(file)

    def test_wrapper_cannot_override_unapproved_base_parameters(self):
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol,DEFAULT_CONFIG
        import json,tempfile
        from pathlib import Path
        wrapper=json.loads(DEFAULT_CONFIG.read_text(encoding='utf-8'))
        wrapper['extends']=str((DEFAULT_CONFIG.parent/wrapper['extends']).resolve())
        wrapper['motion']={'normal_peak_speed_mm_s':{'range':[99.,100.]}}
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'tampered.json';file.write_text(json.dumps(wrapper),encoding='utf-8')
            with self.assertRaises(ValueError):load_protocol(file)

    def test_effective_config_keeps_formal_blocked_and_gates(self):
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol,validate_development_seeds
        c=load_protocol()
        self.assertFalse(c['formal_execution_allowed'])
        self.assertEqual(c['TF_revision']['fixed_offset_s'],.2)
        self.assertEqual(c['shared_gates']['K_raw_history_speed_max_mm_s'],19.2)
        self.assertEqual(c['development_seed_slots'],{'268000':0,'268001':10})
        for seeds in ([266000],[268000,268000],[268000,268001,268002]):
            with self.assertRaises(ValueError):validate_development_seeds(seeds,c)
        validate_development_seeds([268000,268001],c)

    def test_raw_random_arrays_repeat_without_method_dependence(self):
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol
        from dmf.chapter2_geometry_sim.exp1b_random.draws import draw_motion,draw_observation
        c=load_protocol()
        a=draw_motion(268000,c);b=draw_motion(268000,c)
        self.assertEqual(a,b)
        x=draw_observation(268000,'J','low',c);y=draw_observation(268000,'J','low',c)
        self.assertEqual(x['parameters'],y['parameters'])
        for key in x['arrays']:np.testing.assert_array_equal(x['arrays'][key],y['arrays'][key])
        self.assertNotEqual(x['parameters'],draw_observation(268001,'J','high',c)['parameters'])

    def test_tf_episode_is_entirely_after_stall_not_progress(self):
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol
        from dmf.chapter2_geometry_sim.exp1b_random.cache import tf_episode
        p=tf_episode(2.03,8,load_protocol())
        self.assertAlmostEqual(p['start_s'],2.25)
        self.assertAlmostEqual(p['end_s'],2.60)
        self.assertEqual(p['frame_count'],8)
        self.assertGreaterEqual(p['start_s'],2.03+.2-1e-9)


def row(t,x=0.,v=0.,active=191):
    return dict(time_s=t,x_mm=x,y_mm=0.,speed_mm_s=v,active=active)


class RandomReferenceTests(unittest.TestCase):
    spec=dict(radius_mm=.288,max_speed_mm_s=.192,dwell_s=.15)

    def reference(self,rows,**kw):
        from dmf.chapter2_geometry_sim.exp1b_random.reference import build_reference
        return build_reference(rows,(0.,0.),target=191,applied_s=0.,spec=self.spec,**kw)

    def score(self,event,ref,horizon,**kw):
        from dmf.chapter2_geometry_sim.exp1b_random.evaluation import score
        return score(event,ref,horizon,**kw)

    def test_H_terminal_valid_support_is_inclusive(self):
        r=self.reference([row(round(i*.01,10)) for i in range(21)],horizon=.2)
        s=self.score({'decision_s':.2},r,.2)
        self.assertEqual(r['status'],'completed_by_H')
        self.assertEqual(s['primary_outcome'],'reference_supported')
        self.assertAlmostEqual(s['latency_s'],.05)

    def test_actual_exit_is_right_open(self):
        r=self.reference([row(round(i*.01,10),x=0. if i<20 else 1.) for i in range(26)],horizon=.25)
        s=self.score({'decision_s':.2},r,.25)
        self.assertEqual(s['primary_outcome'],'outside_reference_support')

    def test_reference_building_and_event_is_uncertain_not_false_alarm(self):
        r=self.reference([row(round(i*.01,10),x=1. if i<10 else 0.) for i in range(21)],horizon=.2)
        s=self.score({'decision_s':.18},r,.2)
        self.assertEqual(r['status'],'dwell_incomplete_at_H')
        self.assertEqual(s['primary_outcome'],'confirmation_reference_pending_at_H')
        self.assertEqual(s['not_supported_by_H'],1)
        self.assertIsNone(s['physical_wrong_advance'])

    def test_moving_toward_target_is_not_permanent_stall(self):
        r=self.reference([row(0.,x=1.,v=.2),row(.01,x=.998,v=.2)],horizon=.01)
        self.assertEqual(r['status'],'approaching_at_H')
        self.assertEqual(self.score(None,r,.01)['primary_outcome'],'no_confirmation_reference_pending_at_H')

    def test_permanent_stall_with_or_without_false_confirmation(self):
        r=self.reference([row(0.,x=1.),row(.01,x=1.)],horizon=.01,permanent_stall=True)
        self.assertEqual(r['status'],'permanent_stall_without_reference')
        self.assertEqual(self.score(None,r,.01)['primary_outcome'],'permanent_stall_no_confirmation')
        self.assertEqual(self.score({'decision_s':.01},r,.01)['primary_outcome'],'no_reference_confirmation')

    def test_completed_reference_miss_retained_despite_pending_delivery(self):
        r=self.reference([row(round(i*.01,10)) for i in range(21)],horizon=.2)
        s=self.score(None,r,.2,pending_count=1)
        self.assertEqual(s['primary_outcome'],'reference_not_confirmed')
        self.assertEqual(s['missed_references_by_H'],1)
        self.assertTrue(s['observation_right_censored'])
        self.assertEqual(s['supported_by_H'],0)
        self.assertEqual(s['not_supported_by_H'],0)

    def test_no_reference_without_declared_permanent_stall_is_not_proven_false(self):
        r=self.reference([row(0.,x=1.),row(.01,x=1.)],horizon=.01)
        self.assertEqual(r['status'],'no_reference_by_H')
        self.assertEqual(self.score({'decision_s':.01},r,.01)['primary_outcome'],'confirmation_reference_pending_at_H')

    def test_invalid_event_time_is_rejected(self):
        r=self.reference([row(round(i*.01,10)) for i in range(21)],horizon=.2)
        for t in (float('nan'),float('inf'),-.01):
            with self.assertRaises(ValueError):self.score({'decision_s':t},r,.2)

    def test_before_reference_is_not_duplicate_primary_failure(self):
        r=self.reference([row(round(i*.01,10)) for i in range(21)],horizon=.2)
        s=self.score({'decision_s':.1},r,.2)
        self.assertEqual(s['primary_outcome'],'before_reference')
        self.assertEqual(s['primary_outcome_count'],1)
        self.assertEqual(s['missed_references_by_H'],1)

    def test_reference_does_not_bridge_invalid_tick_gap(self):
        r=self.reference([row(0.),row(.01),row(.15),row(.16)],horizon=.16)
        self.assertIsNone(r['confirmed_s'])


class RandomStatisticsTests(unittest.TestCase):
    def test_exact_binomial_boundaries(self):
        from dmf.chapter2_geometry_sim.exp1b_random.statistics import clopper_pearson
        lo,hi=clopper_pearson(0,20)
        self.assertEqual(lo,0.)
        self.assertAlmostEqual(hi,1-.025**(1/20),places=10)
        lo,hi=clopper_pearson(20,20)
        self.assertAlmostEqual(lo,.025**(1/20),places=10)
        self.assertEqual(hi,1.)

    def test_identical_pairs_not_claimed_exact_equivalence(self):
        from dmf.chapter2_geometry_sim.exp1b_random.statistics import paired_binary_difference
        r=paired_binary_difference([0]*20,[0]*20)
        self.assertEqual(r['estimate'],0.)
        self.assertLess(r['lower'],0.)
        self.assertGreater(r['upper'],0.)

    def test_development_no_fake_twenty_replication(self):
        from dmf.chapter2_geometry_sim.exp1b_random.statistics import summarize_development
        records=[dict(seed=268000,condition='N',method='M1',primary_outcome='reference_supported'),
                 dict(seed=268001,condition='N',method='M1',primary_outcome='before_reference')]
        r=summarize_development(records)
        self.assertFalse(r['performance_CI_reported'])
        self.assertEqual(r['planned_method_records'],2)


class RandomWorldAndCacheTests(unittest.TestCase):
    def test_worlds_share_draws_and_replay_without_repair(self):
        from types import SimpleNamespace
        from shapely.geometry import Point, box
        from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol
        from dmf.chapter2_geometry_sim.exp1b_random.draws import draw_motion
        from dmf.chapter2_geometry_sim.exp1b_random.world import make_world
        c=load_protocol();d=draw_motion(268000,c)
        geometry=SimpleNamespace(center=lambda i:np.array([0. if i==190 else 3.2,0.]),
                                 polygons={190:box(-1.5,-1.5,1.5,1.5),191:box(1.7,-1.5,4.7,1.5)})
        p=Point(0,0).buffer(2.)
        pool=SavedOutlineReplay([0.,1.],[p,p])
        worlds={kind:make_world(c,d,kind,geometry,pool,[0,1]) for kind in ('normal','slow','pause','stall')}
        for kind,w in worlds.items():
            self.assertEqual(len(w['rows']),1001)
            self.assertEqual(w['manifest']['raw_motion_uniforms'],d['raw_uniforms'])
            self.assertGreater(w['manifest']['minimum_moving_previous_overlap_mm2'],0)
            self.assertTrue(all(r['speed_mm_s']==0 for r in w['rows'] if r['time_s']<=.54+d['parameters']['response_delay_s']))
            self.assertTrue(all(not r['topology_repaired'] for r in w['diagnostics']))
            self.assertLess(max(abs(x.area-p.area) for x in w['polygons']),1e-10)
        stall=worlds['stall'];s=stall['manifest']['permanent_stall_started_s']
        tail=[r['progress'] for r in stall['rows'] if r['time_s']>=s]
        self.assertEqual(min(tail),max(tail))

    def test_mask_perturbations_are_actual_pixels(self):
        from dmf.chapter2_geometry_sim.exp1b_random.cache import perturb_mask
        a=np.zeros((20,20),np.uint8);a[5:15,5:15]=255;t=a.copy()
        p=dict(jitter_amplitude_mm=.05,bias_magnitude_mm=.1,bias_angle_rad=0.,
               rear_cut_fraction=.2,fragment_band_pixels=2)
        cut=perturb_mask('C',a,t,p,[.5,.5],40.,(1.,0.),True)
        self.assertEqual(np.count_nonzero(cut),80)
        broken=perturb_mask('R',a,t,p,[.5,.5],40.,(1.,0.),True)
        import cv2
        self.assertEqual(cv2.connectedComponents(broken)[0]-1,2)
        np.testing.assert_array_equal(perturb_mask('TF',a,t,p,[0.,0.],40.,(1.,0.),True),t)

    def test_delivery_plan_preserves_capture_identity_and_pending(self):
        from dmf.chapter2_geometry_sim.exp1b_random.cache import plan_delivery
        p=dict(drop_probability=.25,delay_probability=.1,extra_delay_range_s=[.2,.4])
        self.assertEqual(plan_delivery('D',12,.6,p,.1,[.5,.5],.54),[])
        d=plan_delivery('L',199,9.95,p,.9,[.01,1.],.54)[0]
        self.assertEqual(d['frame_id'],199)
        self.assertAlmostEqual(d['available_s'],10.398)
        self.assertAlmostEqual(d['processed_s'],10.4)
        self.assertTrue(d['pending_at_H'])

    def test_runner_hard_blocks_formal_even_with_config_toggle(self):
        from dmf.chapter2_geometry_sim.exp1b_random.runner import run_development
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                run_development(Path(temp)/'output',seeds=[266000])
            self.assertFalse((Path(temp)/'output').exists())

    def test_tf_cache_saves_exact_stalled_episode_and_all_captures(self):
        from types import SimpleNamespace
        from shapely.geometry import Point,box
        from dmf.experiment.evidence import StepContext
        from dmf.chapter2_geometry_sim.observation import Raster
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol
        from dmf.chapter2_geometry_sim.exp1b_random.draws import draw_observation
        from dmf.chapter2_geometry_sim.exp1b_random.cache import create_cache
        import tempfile
        from pathlib import Path
        c=load_protocol();d=draw_observation(268000,'TF','low',c);d['parameters']['stall_false_frames']=8
        geometry=SimpleNamespace(center=lambda i:np.array([0. if i==190 else 3.2,0.]),
            polygons={190:box(-1.5,-1.5,1.5,1.5),191:box(1.7,-1.5,4.7,1.5)})
        raster=Raster(geometry,190,191,10.,4.);p=Point(1.6,0.).buffer(2.)
        world=dict(rows=[dict(time_s=i*.01,progress=.5,speed_mm_s=0.) for i in range(1001)],polygons=[p]*1001,
                   manifest=dict(permanent_stall_started_s=2.03,first_exactly_stationary_stall_tick_s=2.04))
        ctx=StepContext('fixture',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54)
        template=raster.mask(Point(3.2,0.).buffer(2.))
        with tempfile.TemporaryDirectory() as temp:
            cache=create_cache(Path(temp)/'cache',world,raster,d,c,ctx,template)
            self.assertEqual(len(cache['captures']),200)
            self.assertEqual(cache['manifest']['actual_false_frames'],8)
            self.assertAlmostEqual(cache['manifest']['false_target_start_s'],2.25)
            self.assertAlmostEqual(cache['manifest']['false_target_end_s'],2.60)
            self.assertAlmostEqual(cache['manifest']['first_exactly_stationary_stall_tick_s'],2.04)
            self.assertEqual(len(list((Path(temp)/'cache/masks').glob('*.png'))),200)
            self.assertTrue(all(r['during_permanent_stall'] for r in cache['captures'] if r['false_target']))

    def test_independent_manual_event_rejects_repeat_old_and_out_of_order(self):
        from dmf.chapter2_geometry_sim.exp1b_random.audit import manual_event
        rows=[dict(frame_id=i,exposure_start_s=round(i*.05,10),processed_at_s=round(i*.05+.05,10),
                   C0=True,G=True,Q=True,S=True,K=True) for i in range(8)]
        self.assertAlmostEqual(manual_event(rows,dict(Q=True,W=True,S=True,K=True)),.30)
        rows[2]['C0']=False
        self.assertIsNone(manual_event(rows,dict(Q=True,W=True,S=True,K=True)))

    def test_audit_independently_rebuilds_terminal_and_exit_reference(self):
        from dmf.chapter2_geometry_sim.exp1b_random.audit import independent_reference, independent_outcome
        spec=dict(radius_mm=.288,max_speed_mm_s=.192,dwell_s=.15)
        rows=[row(round(i*.01,10)) for i in range(21)]
        r=independent_reference(rows,(0.,0.),spec,.2,False,0.)
        self.assertEqual(independent_outcome(.2,r,.2),'reference_supported')
        rows.append(row(.21,x=1.))
        r=independent_reference(rows,(0.,0.),spec,.21,False,0.)
        self.assertEqual(independent_outcome(.21,r,.21),'outside_reference_support')

    def test_independent_audit_refuses_incomplete_output(self):
        from dmf.chapter2_geometry_sim.exp1b_random.audit import audit_development
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):audit_development(temp)

    def test_runner_and_audit_on_temporary_synthetic_assets(self):
        """Not a research run: fabricated map/pool, deleted temporary output."""
        import tempfile,json,hashlib
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from shapely.geometry import Point,box
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol
        from dmf.chapter2_geometry_sim.exp1b_random.runner import run_development
        from dmf.chapter2_geometry_sim.exp1b_random.audit import audit_development
        from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
        from dmf.chapter2_geometry_sim.observation import Raster
        c=load_protocol();poly=Point(0.,0.).buffer(2.,quad_segs=8)
        geometry=SimpleNamespace(center=lambda i:np.array([0. if i==190 else 3.2,0.]),
            polygons={190:box(-1.5,-1.5,1.5,1.5),191:box(1.7,-1.5,4.7,1.5)})
        pool=SavedOutlineReplay(np.linspace(0.,1.,430),[poly]*430)
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);source=temp/'shape';(source/'trial').mkdir(parents=True);(source/'shape_inputs').mkdir()
            mapfile=temp/'map.json';mapfile.write_text(json.dumps(dict(electrodes=[dict(control_id=i,
                polygon_map_mm=list(p.exterior.coords)) for i,p in geometry.polygons.items()])),encoding='utf-8')
            (source/'trial/world.csv').write_text('shape_phase\n'+'\n'.join(map(str,pool.phases)),encoding='utf-8')
            (source/'trial/world_polygons.json').write_text(json.dumps([dict(polygon_mm=list(poly.exterior.coords))]*430),encoding='utf-8')
            for name in ('trial/manifest.json','shape_inputs/shape_library.json'):(source/name).write_text('{}',encoding='utf-8')
            c['geometry'].update(map_path=str(mapfile),map_sha256=hashlib.sha256(mapfile.read_bytes()).hexdigest(),shape_source=str(source))
            with patch('dmf.chapter2_geometry_sim.exp1b_random.runner.load_protocol',return_value=c),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.verify_baseline'),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.saved_pool',return_value=([],pool,list(range(430)))),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.DesignGeometry',return_value=geometry),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.Raster',side_effect=lambda g,s,t,scale,d:Raster(g,s,t,10.,d)):
                import contextlib,io
                with contextlib.redirect_stdout(io.StringIO()):records=run_development(temp/'output',seeds=[268000])
            self.assertEqual(len(records),72)
            self.assertTrue(all(r['stratum']=='base' for r in records if r['condition'] in ('N','V','P','T')))
            audited=audit_development(temp/'output')
            self.assertTrue(audited['passed'],audited['failures'])
            self.assertEqual(audited['actual_base_worlds'],4)
            self.assertEqual(audited['actual_caches'],12)
            self.assertEqual(audited['reference_scores'],504)
            # A failed recognizer/cache must not erase independently known truth.
            from dmf.chapter2_geometry_sim.exp1b_random.cache import create_cache
            def fail_clean_cache(*args,**kwargs):
                if args[3]['condition']=='N':raise RuntimeError('forced cache fixture failure')
                return create_cache(*args,**kwargs)
            with patch('dmf.chapter2_geometry_sim.exp1b_random.runner.load_protocol',return_value=c),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.verify_baseline'),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.saved_pool',return_value=([],pool,list(range(430)))),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.DesignGeometry',return_value=geometry),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.Raster',side_effect=lambda g,s,t,scale,d:Raster(g,s,t,10.,d)),\
                 patch('dmf.chapter2_geometry_sim.exp1b_random.runner.create_cache',side_effect=fail_clean_cache):
                with contextlib.redirect_stdout(io.StringIO()):failed_records=run_development(temp/'failed_output',seeds=[268000])
            self.assertEqual(len(failed_records),72)
            failed_clean=[r for r in failed_records if r['condition']=='N']
            self.assertEqual(len(failed_clean),6)
            for record in failed_clean:
                self.assertEqual(record['primary_outcome'],'unattempted')
                self.assertEqual(record['reference_arrivals'],1)
                self.assertIsNotNone(record['reference_confirmed_s'])
                self.assertEqual(record['reference_status'],'completed_by_H')
                self.assertEqual(record['missed_references_by_H'],1)
                self.assertFalse(record['reference_right_censored'])
            failed_audit=audit_development(temp/'failed_output')
            self.assertTrue(failed_audit['passed'],failed_audit['failures'])
            self.assertEqual(failed_audit['planned_method_records'],72)
            self.assertEqual(failed_audit['actual_caches'],11)
            # Semantic corruption must be rejected even after refreshing hashes.
            from dmf.chapter2_geometry_sim.exp1b_random.audit import read
            from dmf.chapter2_geometry_sim.single_step import write_csv
            root=temp/'output';primary=read(root/'planned_method_results.csv')
            primary[0]['method']=primary[1]['method']
            primary[0]['decision_s']='123';primary[0]['primary_outcome']='invented'
            write_csv(root/'planned_method_results.csv',primary)
            sensitivity=read(root/'reference_sensitivity_results.csv')
            for key in ('decision_s','confirmed_by_H','observation_right_censored','reference_right_censored',
                        'signed_deviation_s','latency_s','reference_status','reference_confirmed_s','reference_arrivals'):
                sensitivity[0][key]='999'
            write_csv(root/'reference_sensitivity_results.csv',sensitivity)
            summary=json.loads((root/'development_summary.json').read_text(encoding='utf-8'))
            summary.update(performance_CI_reported=True,counts_only=False,unique_development_seeds=20)
            summary['counts'][0]['count']+=1
            (root/'development_summary.json').write_text(json.dumps(summary),encoding='utf-8')
            manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
            for name in ('planned_method_results.csv','reference_sensitivity_results.csv','development_summary.json'):
                manifest['artifacts'][name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
            (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            corrupted=audit_development(root)
            self.assertFalse(corrupted['passed'])
            self.assertFalse(any(f.startswith('artifact_hash:') for f in corrupted['failures']))
            self.assertIn('primary_plan_identities',corrupted['failures'])
            self.assertIn('primary_R0_correspondence',corrupted['failures'])
            self.assertIn('development_summary_semantics',corrupted['failures'])
            for key in ('decision_s','confirmed_by_H','observation_right_censored','reference_right_censored',
                        'signed_deviation_s','latency_s','reference_status','reference_confirmed_s','reference_arrivals'):
                self.assertIn('score_field:'+key,corrupted['failures'])

    def test_independent_window_tracks_bounded_suffix_and_single_event(self):
        from dmf.chapter2_geometry_sim.exp1b_random.audit import manual_windows
        rows=[dict(frame_id=i,exposure_start_s=round(i*.05,10),processed_at_s=round(i*.05+.05,10),
                   C0=True,G=True,Q=True,S=True,K=True) for i in range(9)]
        logs=manual_windows(rows,dict(Q=True,W=True,S=True,K=True))
        self.assertEqual(sum(r['new_event'] for r in logs),1)
        self.assertEqual(logs[-1]['window_ids'],'3;4;5;6;7;8')
        self.assertEqual(logs[-1]['window_count'],6)

    def test_old_repeat_out_of_order_have_same_raw_history_for_six_methods(self):
        from dmf.experiment.evidence import StepContext
        from dmf.chapter2_geometry_sim.observation import CameraFrame
        from dmf.chapter2_geometry_sim.exp1b.gates import RawAssessor,GateRunner
        from dmf.chapter2_geometry_sim.exp1b.spec import METHODS
        from dataclasses import replace
        ctx=StepContext('hand',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54)
        assessor=RawAssessor(ctx);runners=[GateRunner(m,ctx) for m in METHODS]
        features=dict(valid=True,x_mm=0.,y_mm=0.,rho_target=1.,eta_source=0.,distance_mm=0.,components=1)
        frames=[CameraFrame(i,.6+i*.05,.608+i*.05,.648+i*.05,np.ones((2,2),np.uint8),ctx,.65+i*.05) for i in range(9)]
        frames.insert(2,frames[1]);frames[4]=replace(frames[4],context=replace(ctx,epoch=0))
        reasons=[]
        for frame in frames:
            raw=assessor.observe(frame,features);reasons.append(raw['c0_reason'])
            for gate in runners:gate.observe(frame,raw)
        self.assertIn('DUPLICATE_OR_REVERSED',reasons);self.assertIn('OLD_TASK_FRAME',reasons)
        self.assertEqual(sum(bool(r.event) for r in runners),2)


if __name__=='__main__':unittest.main()
