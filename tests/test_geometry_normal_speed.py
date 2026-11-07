import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
MAP=BASE/'电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1/electrode_design_map.json'
MASK=BASE/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot/masks/sample_0002.png'


class NormalSpeedTests(unittest.TestCase):
    def test_isolated_engine_changes_identity_not_original_module_or_source(self):
        from dmf.chapter2_geometry_sim.normal_speed import isolated_engine, TRIAL_ID
        from dmf.chapter2_geometry_sim import single_step
        before=Path(single_step.__file__).read_bytes()
        original=single_step.TRIAL
        engine=isolated_engine()
        self.assertEqual(engine.TRIAL,TRIAL_ID)
        self.assertNotEqual(engine.TRIAL,original)
        self.assertEqual(single_step.TRIAL,original)
        self.assertEqual(Path(engine.__file__).read_bytes(),before)

    def test_only_declared_normal_speed_scope_is_accepted(self):
        from dmf.chapter2_geometry_sim.normal_speed import normal_config, validate_config
        c=normal_config()
        self.assertEqual((c.speed_mm_s,c.duration_s,c.seed),(1.4,6.,264900))
        validate_config(c)
        for change in (dict(speed_mm_s=2.),dict(position_noise_mm=.01),dict(duration_s=3.)):
            with self.assertRaises(ValueError):validate_config(dataclasses.replace(c,**change))

    def test_new_trial_has_601_ticks_120_masks_unique_events_and_strict_audit(self):
        from dmf.chapter2_geometry_sim.normal_speed import run_normal_trial,audit_normal_trial,TRIAL_ID
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'trial'
            m=run_normal_trial(MAP,MASK,root)
            self.assertEqual(m['trial_id'],TRIAL_ID)
            self.assertEqual(m['summary']['world_ticks'],601)
            self.assertEqual(m['summary']['processed_masks'],120)
            self.assertEqual(m['summary']['request_count'],1)
            self.assertGreater(m['summary']['center_reached_s'],4.9)
            self.assertTrue(audit_normal_trial(root)['passed'])
            with self.assertRaises(FileExistsError):run_normal_trial(MAP,MASK,root)
            p=root/'manifest.json';m=json.loads(p.read_text(encoding='utf-8'))
            m['config']['speed_mm_s']=4.8
            p.write_text(json.dumps(m),encoding='utf-8')
            self.assertFalse(audit_normal_trial(root)['passed'])


if __name__=='__main__':unittest.main()
