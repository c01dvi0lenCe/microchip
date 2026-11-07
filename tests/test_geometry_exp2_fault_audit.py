"""Rehashed corruption must fail an independent saved-output audit."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cv2
from dataclasses import replace
from tests.test_geometry_exp2 import fixture
from dmf.chapter2_geometry_sim.exp2_faults.spec import CASES
from dmf.chapter2_geometry_sim.exp2_faults.runner import run_case
from dmf.chapter2_geometry_sim.exp2_faults.persistence import persist_case
from dmf.chapter2_geometry_sim.exp2.persistence import sha256, write_json, write_csv

ROOT=Path(__file__).resolve().parents[1]


class FaultAuditTests(unittest.TestCase):
    def module(self):
        path=ROOT/'scripts/audit_geometry_exp2_faults.py'
        self.assertTrue(path.is_file(), 'independent fault audit not implemented')
        spec=importlib.util.spec_from_file_location('fault_audit_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def saved_fixture(self, root, horizon=.6):
        geometry,pool,config=fixture();config=replace(config,horizon_s=horizon,control_budget_s=horizon)
        map_path=root/'map.json'
        write_json(map_path,dict(electrodes=[dict(control_id=i,polygon_map_mm=list(p.exterior.coords)) for i,p in geometry.polygons.items()]))
        result=run_case(CASES[0],geometry,pool,config,inputs=dict(map_path=str(map_path),map_sha256=sha256(map_path)))
        output=root/'trial';persist_case(result,output)
        return output

    def replace_csv(self, folder, name, change):
        with (folder/name).open(encoding='utf-8-sig',newline='') as stream:records=list(csv.DictReader(stream))
        change(records);write_csv(folder/name,records)
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        manifest['artifacts'][name]=sha256(folder/name);write_json(folder/'manifest.json',manifest)

    def test_changed_recorded_speed_cannot_forge_reference(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory))
            self.replace_csv(folder,'world.csv',lambda r:r[-1].update(speed_mm_s=1000.))
            result=m.audit_case(folder);self.assertFalse(result['passed'])
            self.assertIn('speed_consistency:60',result['failures'])

    def test_changed_run_identity_is_not_accepted_as_current_task(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory))
            self.replace_csv(folder,'captures.csv',lambda rows:[r.update(captured_run_id='other-run') for r in rows])
            self.replace_csv(folder,'deliveries.csv',lambda rows:[r.update(captured_run_id='other-run') for r in rows])
            result=m.audit_case(folder);self.assertFalse(result['passed'])
            self.assertIn('capture_run_identity:1',result['failures'])

    def test_consumed_delivery_cannot_lose_its_frame_record(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory))
            self.replace_csv(folder,'frames.csv',lambda rows:rows.pop())
            result=m.audit_case(folder);self.assertFalse(result['passed'])
            self.assertIn('consumed_delivery_frame_bijection',result['failures'])

    def test_swapped_delivery_ids_cannot_misjoin_frame_evidence(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory))
            def swap(rows):rows[1]['delivery_uid'],rows[2]['delivery_uid']=rows[2]['delivery_uid'],rows[1]['delivery_uid']
            self.replace_csv(folder,'frames.csv',swap)
            result=m.audit_case(folder);self.assertFalse(result['passed'])
            self.assertIn('frame_delivery_join:1',result['failures'])

    def test_intervention_log_cannot_omit_actual_fake_mask(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory),2.3)
            self.replace_csv(folder,'interventions.csv',lambda rows:rows.clear())
            result=m.audit_case(folder);self.assertFalse(result['passed'])
            self.assertIn('intervention_log_matches_declarations',result['failures'])

    def test_unmodified_short_synthetic_fixture_passes(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(m.audit_case(self.saved_fixture(Path(directory)))['passed'])

    def test_rehashed_mask_corruption_is_not_hidden_by_manifest(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory));path=folder/'masks/0001.png'
            mask=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE);mask[0,0]=255;cv2.imwrite(str(path),mask)
            with (folder/'captures.csv').open(encoding='utf-8-sig',newline='') as stream:captures=list(csv.DictReader(stream))
            for key in ('mask_sha256','visible_mask_sha256','source_mask_sha256'):captures[1][key]=sha256(path)
            write_csv(folder/'captures.csv',captures)
            manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            for name in ('masks/0001.png','captures.csv'):manifest['artifacts'][name]=sha256(folder/name)
            write_json(folder/'manifest.json',manifest)
            result=m.audit_case(folder)
            self.assertFalse(result['passed']);self.assertIn('mask_source_geometry:1',result['failures'])

    def test_rehashed_feature_corruption_is_detected(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as directory:
            folder=self.saved_fixture(Path(directory))
            with (folder/'frames.csv').open(encoding='utf-8-sig',newline='') as stream:frames=list(csv.DictReader(stream))
            frames[1]['x_mm']=str(float(frames[1]['x_mm'])+1.)
            write_csv(folder/'frames.csv',frames)
            manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            manifest['artifacts']['frames.csv']=sha256(folder/'frames.csv');write_json(folder/'manifest.json',manifest)
            result=m.audit_case(folder)
            self.assertFalse(result['passed']);self.assertIn('feature_centroid:1',result['failures'])


if __name__=='__main__':unittest.main()
