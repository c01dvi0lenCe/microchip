"""Fabricated/manual fixtures only: never generate formal research assets."""
import copy
import importlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def module(name):
    try:
        return importlib.import_module('dmf.chapter2_geometry_sim.exp1b_formal.' + name)
    except ModuleNotFoundError:
        return None


def row(seed=0, outcome='reference_supported', **changes):
    data = dict(seed=seed, condition='N', stratum='base', method='M1', reference_id='R0',
        status='executed', primary_outcome=outcome, reference_status='completed_by_H',
        reference_arrivals=1, supported_by_H=int(outcome == 'reference_supported'),
        latency_s=.2 if outcome == 'reference_supported' else None,
        observation_right_censored=False, reference_right_censored=False,
        reference_known=True)
    data.update(changes)
    return data


class FormalStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.s = module('statistics')
        self.assertIsNotNone(self.s, 'formal statistics implementation is required')

    def test_cp_hand_boundaries(self):
        lo, hi = self.s.clopper_pearson(0, 5)
        self.assertEqual(lo, 0.)
        self.assertAlmostEqual(hi, 1-.025**.2, places=12)
        lo, hi = self.s.clopper_pearson(5, 5)
        self.assertAlmostEqual(lo, .025**.2, places=12)
        self.assertEqual(hi, 1.)

    def test_single_strength_and_conservative_equal_mixture(self):
        low = [row(i) for i in range(10)]
        high = [row(i+10, 'before_reference') for i in range(10)]
        a = self.s.rate(low, 'reference_supported_per_planned')
        b = self.s.mixture_rate([low, high], 'reference_supported_per_planned')
        self.assertEqual((a['n_planned'], a['k']), (10, 10))
        self.assertEqual((b['n_planned'], b['estimate']), (20, .5))
        l0, u0 = self.s.clopper_pearson(10, 10, .025)
        l1, u1 = self.s.clopper_pearson(0, 10, .025)
        self.assertAlmostEqual(b['ci_lower'], (l0+l1)/2)
        self.assertAlmostEqual(b['ci_upper'], (u0+u1)/2)
        self.assertNotEqual(b['ci_lower'], self.s.clopper_pearson(10,20)[0])

    def test_missing_keeps_denominator_and_suppresses_ci(self):
        rows = [row(0), row(1, 'unattempted', status='unattempted')]
        result = self.s.rate(rows, 'reference_supported_per_planned')
        self.assertEqual((result['n_planned'], result['n_known'], result['n_unknown']), (2,1,1))
        self.assertEqual((result['estimate'],result['ident_lower'],result['ident_upper']), (.5,.5,1.))
        self.assertIsNone(result['ci_lower'])

    def test_future_pending_does_not_make_fixed_h_unknown(self):
        pending = row(0, 'reference_not_confirmed', observation_right_censored=True)
        self.assertEqual(self.s.endpoint(pending, 'reference_supported_per_planned'), 0)
        no_ref = row(1, 'no_confirmation_reference_pending_at_H', reference_arrivals=0,
            reference_status='approaching_at_H', reference_right_censored=True)
        self.assertEqual(self.s.endpoint(no_ref, 'no_reference_confirmation_per_planned'), 0)
        self.assertEqual(self.s.endpoint(no_ref, 'reference_supported_per_planned'), 0)
        self.assertIsNone(self.s.endpoint(row(2, 'unattempted',status='unattempted'),
            'reference_supported_per_planned'))

    def test_unknown_truth_retains_known_reference_recall_denominator(self):
        failed = row(0, 'unattempted', status='unattempted')
        r = self.s.rate([failed], 'reference_recall')
        self.assertEqual((r['n_planned'],r['n_unknown'],r['k']), (1,1,0))
        self.assertIsNone(r['ci_upper'])
        self.assertIsNone(self.s.endpoint(row(1, 'unattempted',status='unattempted',
            reference_known=False), 'reference_supported_per_planned'))

    def test_paired_discordance_identical_uncertainty_and_missing(self):
        a = [row(0),row(1,'before_reference')]
        b = [row(0,'before_reference'),row(1)]
        r = self.s.paired_rate(a,b,'reference_supported_per_planned')
        self.assertEqual((r['discordant_plus'],r['discordant_minus'],r['estimate']), (1,1,0.))
        identical = self.s.paired_rate(a,a,'reference_supported_per_planned')
        self.assertLess(identical['ci_lower'],0.)
        self.assertGreater(identical['ci_upper'],0.)
        missing = self.s.paired_rate([row(0)], [row(0,'unattempted',status='unattempted')],
            'reference_supported_per_planned')
        self.assertEqual((missing['ident_lower'],missing['ident_upper']), (0.,1.))
        self.assertIsNone(missing['ci_lower'])

    def test_latency_joint_four_no_interval_five_deterministic(self):
        a = [row(i,latency_s=.1*i) for i in range(6)]
        b = [row(i,latency_s=.03*i) for i in range(6)]
        r4 = self.s.paired_latency(a[:4],b[:4], stream='manual')
        self.assertEqual(r4['n_joint'],4)
        self.assertIsNone(r4['ci_lower'])
        r5 = self.s.paired_latency(a[:5],b[:5],stream='manual')
        self.assertEqual(r5,self.s.paired_latency(a[:5],b[:5],stream='manual'))
        self.assertEqual(r5['n_joint'],5)
        self.assertIsNotNone(r5['ci_lower'])
        self.assertAlmostEqual(r5['median_difference_s'],.14)
        b[0] = row(0,'before_reference')
        self.assertEqual(self.s.paired_latency(a,b,stream='manual')['n_joint'],5)


class FormalPlanTests(unittest.TestCase):
    def setUp(self):
        self.p = module('spec')
        self.assertIsNotNone(self.p, 'formal plan implementation is required')

    def test_exact_plan_and_seeds_no_subset(self):
        c = self.p.load_protocol()
        self.assertEqual(self.p.validate_formal_seeds(range(266000,266020)),list(range(266000,266020)))
        for bad in ([266000],[268000],list(range(266001,266021)),[266000]*20):
            with self.assertRaises(ValueError): self.p.validate_formal_seeds(bad)
        self.assertEqual(len(self.p.planned_identities(c)),10080)
        self.assertEqual(len(self.p.planned_identities(c,primary=True)),1440)

    def test_identity_missing_and_duplicate_rejected(self):
        ids = [('0','N','M1','R0'),('1','N','M1','R0')]
        rows = [row(0),row(1)]
        self.p.validate_identities(rows,ids)
        with self.assertRaises(ValueError): self.p.validate_identities(rows[:1],ids)
        with self.assertRaises(ValueError): self.p.validate_identities([rows[0],rows[0]],ids)

    def test_draw_formulas_match_approved_dev_fixture_no_formal_draws(self):
        d = module('draws')
        self.assertIsNotNone(d)
        from dmf.chapter2_geometry_sim.exp1b_random.spec import load_protocol
        from dmf.chapter2_geometry_sim.exp1b_random import draws as old
        c = load_protocol()
        self.assertEqual(d.fixture_motion(268000,c),old.draw_motion(268000,c))
        for cid in ('N','J','TF'):
            a = d.fixture_observation(268000,cid,'low',c)
            b = old.draw_observation(268000,cid,'low',c)
            self.assertEqual({k:v for k,v in a.items() if k!='arrays'},
                {k:v for k,v in b.items() if k!='arrays'})
            for key in a['arrays']:
                self.assertTrue((a['arrays'][key] == b['arrays'][key]).all())
        with self.assertRaises(ValueError): d.draw_motion(268000,self.p.load_protocol())

    def test_runner_missing_freeze_hard_block(self):
        r = module('runner')
        self.assertIsNotNone(r)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises((ValueError,FileNotFoundError)):
                r.run_formal(Path(temp)/'new',freeze_path=None)
            self.assertFalse((Path(temp)/'new').exists())


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.f = module('freeze')
        self.assertIsNotNone(self.f, 'formal freeze implementation is required')
        self.registry_temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.registry_temp.cleanup)
        self.registry_patch=patch.object(self.f,'BATCH_REGISTRY',
            Path(self.registry_temp.name)/'approved_batch_claim.json',create=True)
        self.registry_patch.start();self.addCleanup(self.registry_patch.stop)

    def test_seed_scan_ignores_reservations_and_finds_actual_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'proposal.json').write_text(json.dumps({'formal_seed_reservation_only':[266000]}))
            (root/'source_snapshot.json').write_text(json.dumps({'actual_formal_seeds':[266001]}))
            (root/'manifest.json').write_text(json.dumps({'actual_development_seeds':[268000]}))
            self.assertEqual(self.f.scan_seed_use(root)['used_formal_seeds'],[])
            (root/'actual.csv').write_text('seed,status\n266003,executed\n')
            self.assertEqual(self.f.scan_seed_use(root)['used_formal_seeds'],[266003])

    def test_verification_evidence_rejects_nonzero_tests_and_unapproved(self):
        good=dict(protocol_approved=True,explicit_run_approval=True,spec_review_passed=True,
            quality_review_passed=True,tests=[dict(command='manual-fixture-tests',exit_code=0)])
        self.f.validate_verification(good)
        for key in ('protocol_approved','explicit_run_approval','spec_review_passed','quality_review_passed'):
            bad=copy.deepcopy(good);bad[key]=False
            with self.assertRaises(ValueError):self.f.validate_verification(bad)
        good['tests'][0]['exit_code']=1
        with self.assertRaises(ValueError):self.f.validate_verification(good)

    def test_freeze_does_not_initialize_formal_rng_and_detects_tamper(self):
        # Fabricated immutable input map; no runtime world/cache generation.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);code=root/'code.py';code.write_text('fixture')
            evidence=root/'verification.json'
            evidence.write_text(json.dumps(dict(protocol_approved=True,explicit_run_approval=True,
                spec_review_passed=True,quality_review_passed=True,
                tests=[dict(command='manual-fixture-tests',exit_code=0)])))
            config=module('spec').load_protocol()
            with patch.object(self.f,'source_inventory',return_value={str(code):self.f.sha(code)}), \
                 patch.object(self.f,'scan_seed_use',return_value=dict(scope=str(root),used_formal_seeds=[],files=[])), \
                 patch('numpy.random.PCG64',side_effect=AssertionError('freeze drew RNG')):
                path=self.f.create_freeze(root/'frozen',evidence,config=config)
                self.f.verify_freeze(path,config=config,check_unused=False)
                frozen=json.loads(path.read_text(encoding='utf-8'))
                frozen['environment']['numpy']='tampered'
                with self.assertRaises(ValueError):self.f.verify_freeze_data(frozen,config)
                frozen=json.loads(path.read_text(encoding='utf-8'))
                changed_config=copy.deepcopy(config);changed_config['time']['horizon_s']=11.
                with self.assertRaises(ValueError):self.f.verify_freeze_data(frozen,changed_config)
                code.write_text('changed')
                with self.assertRaises(ValueError):self.f.verify_freeze(path,config=config,check_unused=False)

    def test_claim_is_one_use(self):
        with tempfile.TemporaryDirectory() as temp:
            freeze=Path(temp)/'freeze.json';freeze.write_text('{"source_hashes":{"fabricated.py":"fixture"}}')
            self.f.claim_batch(freeze,Path(temp)/'first')
            with self.assertRaises(FileExistsError):self.f.claim_batch(freeze,Path(temp)/'second')

    def test_shared_claim_blocks_a_new_freeze_and_outside_scope_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);first=root/'freeze1';second=root/'freeze2';first.mkdir();second.mkdir()
            for folder in (first,second):
                (folder/'freeze.json').write_text('{"source_hashes":{"fabricated.py":"fixture"}}')
            self.f.claim_batch(first/'freeze.json',root/'outside_results_scope'/'one')
            with self.assertRaises(FileExistsError):
                self.f.claim_batch(second/'freeze.json',root/'outside_results_scope'/'two')
            with self.assertRaises(FileExistsError):
                self.f.create_freeze(root/'third_freeze',root/'missing_verification.json')
            claim=json.loads(self.f.BATCH_REGISTRY.read_text(encoding='utf-8'))
            self.assertEqual(claim['formal_seeds'],list(range(266000,266020)))
            self.assertEqual(claim['freeze_sha256'],self.f.sha(first/'freeze.json'))
            self.assertEqual(claim['source_hashes'],{'fabricated.py':'fixture'})


class FormalAuditAndTablesTests(unittest.TestCase):
    def test_world_progress_and_stall_metadata_are_independently_checked(self):
        audit=module('audit')
        self.assertTrue(callable(getattr(audit,'audit_world_motion',None)),
            'independent WORLD progress and manifest validator required')
        parameters=dict(normal_peak_speed_mm_s=1.5,slow_peak_speed_mm_s=1.5,
            response_delay_s=0.,pause_progress=.5,pause_duration_s=.01,stall_progress=.5)
        source=(0.,0.);target=(.016,0.)
        for kind,phases,speeds in (('normal',[0.,.5,1.],[0.,.8,.8]),
                ('stall',[0.,.5,.5],[0.,.8,0.]),('pause',[0.,.5,.5],[0.,.8,0.])):
            rows=[dict(time_s=i*.01,x_mm=q*.016,y_mm=0.,speed_mm_s=speeds[i],progress=q,
                shape_phase=q,active=191,response_at_s=0.,permanent_stall=kind=='stall' and i>=1)
                for i,q in enumerate(phases)]
            manifest=dict(kind=kind,ticks=3,applied_s=0.,response_s=0.,peak_speed_mm_s=1.5,duration_s=.02,
                permanent_stall_started_s=.01 if kind=='stall' else None,
                first_exactly_stationary_stall_tick_s=.02 if kind=='stall' else None,
                pause_started_s=.01 if kind=='pause' else None,pause_duration_s=.01 if kind=='pause' else None)
            def issues(rr,mm):
                found=[]
                expected_rows,metadata=audit.audit_world_motion(rr,mm,parameters,kind,source,target,
                    lambda ok,label:found.append(label) if not ok else None,horizon=.02,dt=.01,applied=0.)
                return found,expected_rows,metadata
            found,expected,derived=issues(rows,manifest)
            self.assertEqual(found,[],kind)
            self.assertAlmostEqual(expected[1]['progress'],.5)
            for key in ('progress','shape_phase','time_s','response_at_s','speed_mm_s','active'):
                bad=copy.deepcopy(rows);bad[1][key]+=.001
                self.assertTrue(issues(bad,manifest)[0],key)
            if kind=='stall':
                self.assertEqual(derived['permanent_stall_started_s'],.01)
                for key in ('permanent_stall_started_s','first_exactly_stationary_stall_tick_s'):
                    bad=copy.deepcopy(manifest);bad[key]+=.01
                    self.assertTrue(issues(rows,bad)[0],key)

    def test_raw_chronology_is_bound_to_independent_delivery_projection(self):
        audit=module('audit')
        self.assertTrue(callable(getattr(audit,'audit_capture_chronology',None)),
            'independent capture/raw chronology validator required')
        captures=[];plans=[];raw=[]
        for i in range(200):
            t=round(i/20,10);available=round(t+.048,12)
            processed=round(math.ceil(available/.01-1e-9)*.01,10)
            captures.append(dict(frame_id=i,exposure_start_s=t,exposure_end_s=t+.008,
                available_s=available,captured_epoch='1' if t>=.54-1e-10 else ''))
            plans.append((processed,i,available))
            raw.append(dict(delivery_id=i,frame_id=i,exposure_start_s=t,exposure_end_s=t+.008,
                available_s=available,processed_at_s=processed))
        def issues(caps,rows):
            found=[]
            audit.audit_capture_chronology(caps,rows,plans,
                lambda ok,label:found.append(label) if not ok else None)
            return found
        self.assertEqual(issues(captures,raw),[])
        for key in ('processed_at_s','exposure_start_s','exposure_end_s','available_s','frame_id','delivery_id'):
            corrupt=copy.deepcopy(raw);corrupt[30][key]+=1
            self.assertTrue(issues(captures,corrupt),key)
        reordered=copy.deepcopy(raw);reordered[30],reordered[31]=reordered[31],reordered[30]
        self.assertTrue(issues(captures,reordered))
        corrupt=copy.deepcopy(captures);corrupt[30]['captured_epoch']='0'
        self.assertTrue(issues(corrupt,raw))
        corrupt=copy.deepcopy(captures);corrupt[30]['exposure_end_s']+=.001
        self.assertTrue(issues(corrupt,raw))

    def test_saved_audit_is_independent_of_runtime_recognizer_and_scorer(self):
        audit=module('audit')
        self.assertIsNotNone(audit,'independent formal audit implementation required')
        text=Path(audit.__file__).read_text(encoding='utf-8')
        for forbidden in ('RawAssessor','GateRunner','build_reference(','score(','audit_development('):
            self.assertNotIn(forbidden,text)
        self.assertTrue(callable(audit.audit_formal))

    def test_manual_complete_plan_tables_no_grand_pool_and_full_denominators(self):
        spec=module('spec');summary=module('summary')
        self.assertIsNotNone(summary)
        config=spec.load_protocol();records=[]
        for seed,cid,method,rid in spec.planned_identities(config):
            condition=next(c for c in config['conditions'] if c['id']==cid)
            records.append(row(int(seed),'unattempted',condition=cid,method=method,reference_id=rid,
                stratum=spec.stratum(int(seed),condition),status='unattempted'))
        tables=summary.build_tables(records,config)
        for table in tables.values():self.assertTrue(all(r['condition'] in {c['id'] for c in config['conditions']} for r in table))
        selected=[r for r in tables['statistics_rates.csv'] if r['reference_id']=='R0'
            and r['method']=='M1' and r['endpoint']=='reference_supported_per_planned']
        expected={'base':20,'low':10,'high':10,'mixture':20}
        self.assertTrue(all(r['n_planned']==expected[r['stratum']] and r['n_unknown']==expected[r['stratum']]
            and r['ci_lower'] is None for r in selected))
        self.assertTrue(summary.definitions(config)['no_cross_condition_grand_accuracy'])
        with self.assertRaises(ValueError):summary.build_tables(records[:-1],config)
        with tempfile.TemporaryDirectory() as temp:
            summary.write_statistics(temp,records,config)
            audit=module('audit');issues=[]
            audit.audit_statistics(Path(temp),audit.read(Path(temp)/'reference_sensitivity_results.csv')
                if (Path(temp)/'reference_sensitivity_results.csv').exists() else
                [{k: str(v) if v is not None else '' for k,v in r.items()} for r in records],
                config,lambda ok,label: issues.append(label) if not ok else None)
            self.assertEqual(issues,[])

    def test_runner_failure_known_reference_is_not_zero_recall(self):
        runner=module('runner')
        self.assertIsNotNone(runner)
        known=dict(status='completed_by_H',intervals=[dict(confirmed_s=2.,end_s=10.,terminal_inclusive=True)])
        result=runner.failure_score(known,10.)
        self.assertTrue(result['reference_known'])
        self.assertEqual(result['reference_arrivals'],1)
        self.assertIsNone(result['supported_by_H'])
        self.assertIsNone(result['missed_references_by_H'])
        unknown=runner.failure_score(None,10.)
        self.assertFalse(unknown['reference_known'])
        self.assertIsNone(unknown['reference_arrivals'])


if __name__ == '__main__':
    unittest.main()
