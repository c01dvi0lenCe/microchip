import tempfile
import unittest
from pathlib import Path
import numpy as np

try:
    from dmf.chapter2_sim.s2.spec import StudySpecS2, CONDITIONS
    from dmf.chapter2_sim.s2.inputs import generate_base, validate_teacher, observation_variant, freeze_input
    READY = True
except ModuleNotFoundError:
    READY = False


class S2InputTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(READY, 'S2 fixed single-task teacher is not implemented')
        self.spec=StudySpecS2()

    def test_thirteen_conditions(self):
        self.assertEqual(len(CONDITIONS),13)
        self.assertEqual(len(set(CONDITIONS)),13)

    def test_one_applied_target_for_whole_followup(self):
        base=generate_base(self.spec,262000,'normal')
        audit=validate_teacher(base)
        self.assertTrue(audit['consistent'])
        self.assertEqual(len(base['commands']),1)
        self.assertAlmostEqual(base['commands'][0]['applied_s'],.04)
        self.assertEqual(base['commands'][0]['target'],191)
        self.assertEqual(len(base['applied_events']),1)
        self.assertAlmostEqual(base['applied_events'][0]['executed_s'],.04)
        self.assertAlmostEqual(base['applied_events'][0]['response_at_s'],.22)
        self.assertTrue(all(r['world_active']==191 for r in base['truth'] if r['time_s']>=.05))
        self.assertEqual(base['truth'][-1]['time_s'],4.)
        self.assertEqual(len(base['observations']['normal']),80)
        self.assertEqual(base['geometry'].shape,(164,212))

    def test_teacher_rejects_target_mismatch(self):
        base=generate_base(self.spec,262000,'normal')
        base['truth'][200]['target']=192
        with self.assertRaises(ValueError):validate_teacher(base)

    def test_stress_preserves_missing_and_time_metadata(self):
        base=generate_base(self.spec,262000,'failure')
        frames=base['observations']['normal']
        altered=observation_variant(frames,base['snapshot'],'C_jump_short',self.spec)
        for old,new in zip(frames,altered):
            self.assertEqual(old['frame_id'],new['frame_id'])
            self.assertEqual(old['exposure_s'],new['exposure_s'])
            self.assertEqual(old['available_s'],new['available_s'])
            if old['mask'] is None:self.assertIsNone(new['mask'])

    def test_tail_pixel_counts_and_input_has_no_truth(self):
        from dmf.experiment.mask_cache import load_cache
        base=generate_base(self.spec,262000,'failure')
        frames=observation_variant(base['observations']['normal'],base['snapshot'],'D_tail_false',self.spec)
        mask=next(r['mask'] for r in frames if r['mask'] is not None)
        self.assertEqual(np.count_nonzero(mask),105)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'inputs'
            freeze_input(base,frames,p,self.spec)
            cache=load_cache(p)
            self.assertEqual(cache['tasks'],base['tasks'])
            self.assertNotIn('truth',cache)
            with self.assertRaises(FileExistsError):freeze_input(base,frames,p,self.spec)


if __name__ == '__main__':unittest.main()
