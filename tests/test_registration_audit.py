"""Synthetic arithmetic/storage fixtures, never real registration evidence."""
import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from dmf.vision import registration_audit as audit
from dmf.vision import registration_repeatability as repeat


def fixture():
    points = []
    for i, xy in enumerate(((0, 0), (10, 0), (10, 10), (0, 10))):
        points.append(dict(point_id=f'F{i+1}', role='fit', map_mm=list(xy),
                           observed_px=[xy[0]*2, xy[1]*2], status='confirmed'))
    points += [dict(point_id='C1', role='check', map_mm=[2, 3],
                    observed_px=[7, 10], status='confirmed'),
               dict(point_id='C2', role='check', map_mm=[4, 5],
                    observed_px=[8, 10], status='confirmed')]
    return dict(image_size=[100, 80], fit_freeze=dict(
        image_to_design_mm=[[.5, 0, 0], [0, .5, 0], [0, 0, 1]]), points=points)


def review():
    catalog = [dict(point_id=f'C{i}', control_id=i, vertex_index=0,
                    map_mm=[float(i), 0.]) for i in range(1, 17)]
    return repeat.new_review(catalog, [100, 80], seed=23)


class IndependentArithmeticTests(unittest.TestCase):
    def test_signed_inverse_pixel_and_forward_design_residuals(self):
        result = audit.recompute(fixture(), core_bounds=[0, 0, 10, 10])
        row = result['points'][0]
        self.assertEqual((row['du_px'], row['dv_px']), (-3., -4.))
        self.assertEqual(row['error_px'], 5.)
        self.assertEqual((row['dx_design_mm'], row['dy_design_mm']), (1.5, 2.))
        self.assertEqual(row['error_design_mm'], 2.5)
        self.assertAlmostEqual(result['summary']['rmse_px'], np.sqrt(12.5))
        self.assertAlmostEqual(result['summary']['p95_px'], 4.75)
        self.assertEqual(result['summary']['max_px'], 5.)
        self.assertEqual(result['summary']['fit_count'], 4)
        self.assertEqual(result['summary']['check_total'], 2)

    def test_fit_observations_do_not_change_check_errors(self):
        w = fixture(); before = audit.recompute(w, core_bounds=[0, 0, 10, 10])
        w['points'][0]['observed_px'] = [99, 79]
        after = audit.recompute(w, core_bounds=[0, 0, 10, 10])
        self.assertEqual(before['points'], after['points'])

    def test_missing_check_preserves_denominator_and_null_aggregate(self):
        w = fixture(); w['points'][-1].update(status='pending', observed_px=None)
        result = audit.recompute(w, core_bounds=[0, 0, 10, 10])
        self.assertEqual(result['summary']['check_total'], 2)
        self.assertEqual(result['summary']['check_missing'], 1)
        self.assertIsNone(result['summary']['rmse_px'])

    def test_reject_singular_or_nonfinite_matrix(self):
        for h in (np.zeros((3, 3)), np.full((3, 3), np.nan)):
            w = fixture(); w['fit_freeze']['image_to_design_mm'] = h.tolist()
            with self.assertRaises(ValueError): audit.recompute(w, core_bounds=[0, 0, 10, 10])

    def test_comparison_is_per_point_not_rounded_totals(self):
        result = audit.recompute(fixture(), core_bounds=[0, 0, 10, 10])
        previous = dict(result['summary'], residuals=[dict(point_id=r['point_id'],
                         error_px=r['error_px'], error_design_mm=r['error_design_mm'])
                         for r in result['points']])
        self.assertTrue(audit.compare_previous(result, previous)['matches'])
        previous['residuals'][0]['error_px'] += .001
        self.assertFalse(audit.compare_previous(result, previous)['matches'])


class RepeatabilityTests(unittest.TestCase):
    def test_new_rounds_have_no_matrix_or_old_coordinates(self):
        data = review()
        self.assertEqual(len(data['rounds']), 2)
        self.assertEqual(len(data['catalog']), 16)
        self.assertNotIn('observed_px', str(data))
        self.assertNotIn('suggested_px', str(data))
        self.assertNotIn('image_to_design', str(data))
        self.assertEqual(data['rounds'][0]['observations'], {})
        self.assertEqual(data['rounds'][1]['observations'], {})

    def test_second_round_blocked_until_first_is_sealed(self):
        with self.assertRaises(ValueError): repeat.record_click(review(), 2, 'C1', [1, 2], 'reviewer')

    def test_keeps_raw_click_and_requires_explicit_reviewer(self):
        data = review()
        with self.assertRaises(ValueError): repeat.record_click(data, 1, 'C1', [1, 2], '')
        repeat.record_click(data, 1, 'C1', [1.125, 2.875], 'human')
        self.assertEqual(data['rounds'][0]['observations']['C1']['pixel'], [1.125, 2.875])
        with self.assertRaises(ValueError): repeat.record_click(data, 1, 'C2', [100, 3], 'human')

    def test_missing_repeat_statistics_are_null(self):
        result = repeat.summarize(review())
        self.assertEqual(result['status'], 'pending_human_rounds')
        self.assertEqual(result['planned_points'], 16)
        self.assertIsNone(result['rmse_between_rounds_px'])

    def test_seals_round_and_reports_pairs_not_independent_samples(self):
        data = review()
        for i in range(1, 17): repeat.record_click(data, 1, f'C{i}', [i, 10], 'human')
        repeat.seal_round(data, 1)
        with self.assertRaises(ValueError): repeat.record_click(data, 1, 'C1', [3, 3], 'human')
        for i in range(1, 17): repeat.record_click(data, 2, f'C{i}', [i+3, 14], 'human')
        self.assertIsNone(repeat.summarize(data)['rmse_between_rounds_px'])
        repeat.seal_round(data, 2)
        result = repeat.summarize(data)
        self.assertEqual(result['paired_points'], 16)
        self.assertEqual(result['rmse_between_rounds_px'], 5.)
        self.assertEqual(result['independent_acquisition_groups'], 1)
        data['rounds'][0]['observations']['C1']['pixel'][0] += 1
        with self.assertRaises(ValueError): repeat.summarize(data)

    def test_save_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'repeat.json'
            repeat.save_new(path, review())
            a = repeat.load_review(path); b = repeat.load_review(path)
            repeat.record_click(a, 1, 'C1', [1, 2], 'human'); repeat.save_review(path, a)
            with self.assertRaises(ValueError): repeat.save_review(path, b)

    def test_invisible_reason_keeps_missing_pair_denominator(self):
        data = review()
        with self.assertRaises(ValueError): repeat.exclude(data, 1, 'C1', '', 'human')
        repeat.exclude(data, 1, 'C1', 'reflection', 'human')
        self.assertEqual(repeat.summarize(data)['planned_points'], 16)
        self.assertIsNone(repeat.summarize(data)['rmse_between_rounds_px'])


class FinalBindingTests(unittest.TestCase):
    def test_preexperiment_or_blank_template_never_valid(self):
        m = audit.final_manifest_template()
        with self.assertRaises(ValueError): audit.validate_final_binding(m, {}, 'image', 'map')
        m['source_scope'] = 'pre_experiment_only'
        with self.assertRaises(ValueError): audit.validate_final_binding(m, {}, 'image', 'map')

    def test_validated_conditions_are_exact_and_geometry_change_rejected(self):
        m = audit.final_manifest_template()
        conditions = {key: 'documented' for key in audit.CONDITION_FIELDS}
        conditions.update(resolution=[5472, 3648], chip_height_mm=12.5, focal_length_mm=25.)
        m.update(status='accepted_final_calibration',source_scope='final_apparatus', final_height_fixed=True,
                 conditions=conditions, reference_sha256='a'*64, design_map_sha256='b'*64,
                 image_to_design_mm=np.eye(3).tolist(), independently_checked=True,
                 acceptance=dict(declared_before_check_review=True, thresholds_px=dict(
                     rmse_px=2., p95_px=3., max_px=4.), measured_px=dict(
                     rmse_px=1., p95_px=2., max_px=3.)), reviewer='human')
        audit.validate_final_binding(m, copy.deepcopy(conditions), 'a'*64, 'b'*64)
        changed = dict(conditions, chip_height_mm=13.)
        with self.assertRaises(ValueError): audit.validate_final_binding(m, changed, 'a'*64, 'b'*64)
        with self.assertRaises(ValueError): audit.validate_final_binding(m, conditions, 'c'*64, 'b'*64)

    def test_populated_template_and_explicit_failure_are_not_accepted(self):
        m=audit.final_manifest_template()
        conditions={key:'documented' for key in audit.CONDITION_FIELDS}
        m.update(source_scope='final_apparatus', final_height_fixed=True, conditions=conditions,
            reference_sha256='a'*64,design_map_sha256='b'*64,image_to_design_mm=np.eye(3).tolist(),
            independently_checked=True,reviewer='human',acceptance=dict(
            declared_before_check_review=True,thresholds_px=dict(rmse_px=2,p95_px=3,max_px=4),
            measured_px=dict(rmse_px=1,p95_px=2,max_px=3)))
        with self.assertRaises(ValueError): audit.validate_final_binding(m,conditions,'a'*64,'b'*64)


class SourceIntegrityTests(unittest.TestCase):
    def test_blind_payload_rejects_accidental_matrix_injection(self):
        data=review();data['image_to_design_mm']=np.eye(3).tolist()
        with self.assertRaises(ValueError):repeat.validate(data)

    def test_complete_source_preparation_preserves_old_records(self):
        import test_registration_workspace as fixtures
        from dmf.vision.design_registration import (file_hash, project, record_observation,
                                                   freeze_fit, seal_evaluation)
        from dmf.vision.registration_workspace import load_workspace,save_workspace
        base=fixtures.WorkspaceTests('test_cli_help');base.setUp();self.addCleanup(base.doCleanups)
        path=base.prepare()[0];w=load_workspace(path)
        inverse=np.linalg.inv(w['initial_image_to_design_mm'])
        for role in ('fit','check'):
            for p in w['points']:
                if p['role']==role:record_observation(w,p['point_id'],project([p['map_mm']],inverse)[0],'fixture')
            if role=='fit':freeze_fit(w)
        seal_evaluation(w);save_workspace(path,w);before=file_hash(path)
        output=base.root/'blind';new_path=repeat.prepare_repeatability(path,output)
        self.assertEqual(file_hash(path),before)
        data=repeat.load_review(new_path)
        self.assertEqual(data['rounds'][0]['observations'],{})
        self.assertNotIn('suggested_px',new_path.read_text(encoding='utf-8'))
        self.assertNotIn('image_to_design_mm',new_path.read_text(encoding='utf-8'))
        launcher=(output/'启动盲法两轮核对.cmd').read_bytes()
        self.assertNotIn(b'\n',launcher.replace(b'\r\n',b''))
        with self.assertRaises(FileExistsError):repeat.prepare_repeatability(path,output)

    def test_blind_window_loads_no_historical_marker(self):
        import subprocess,sys
        import test_registration_workspace as fixtures
        from dmf.vision.design_registration import file_hash
        from dmf.vision.image_io import write_image
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);design=fixtures.design_fixture()
            (folder/'map.json').write_text(json.dumps(design),encoding='utf-8')
            write_image(folder/'image.png',np.zeros((80,100,3),np.uint8))
            data=review();data.update(image_path='image.png',image_sha256=file_hash(folder/'image.png'),
                design_map_path='map.json',design_map_sha256=file_hash(folder/'map.json'))
            for p in data['catalog']:p['map_mm']=design['electrodes'][p['control_id']-1]['polygon_map_mm'][0]
            from dmf.vision.design_registration import digest
            data['catalog_sha256']=digest(data['catalog'])
            path=folder/'repeat.json';repeat.save_new(path,data)
            code='''import sys,tkinter as tk
from dmf.vision.registration_repeatability_gui import RepeatabilityApp
root=tk.Tk();root.withdraw()
app=RepeatabilityApp(root,sys.argv[1]);root.update_idletasks()
assert app.draft is None
assert len(app.canvas.canvas.find_withtag('all'))==1
assert 'image_to_design_mm' not in app.data
app.table.selection_set('C10');app.select();root.update_idletasks()
assert '第1行' in app.location.get() and '第10列' in app.location.get()
assert len(app.global_canvas.find_withtag('current_electrode'))==1
assert len(app.canvas.canvas.find_withtag('all'))==1
root.destroy()
'''
            run=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)


class PresentationTests(unittest.TestCase):
    def test_core_location_uses_confirmed_direction_and_distinguishes_peripheral(self):
        from dmf.vision.registration_repeatability_gui import electrode_location
        for electrode_id,row,col in ((1,1,1),(20,1,20),(381,20,1),(400,20,20),
                                      (190,10,10),(211,11,11),(316,16,16)):
            text=electrode_location(electrode_id)
            self.assertIn(f'第{row}行',text);self.assertIn(f'第{col}列',text)
        for electrode_id,direction in ((417,'左上'),(418,'右上'),(419,'右下'),(420,'左下')):
            self.assertIn(direction,electrode_location(electrode_id))
            self.assertNotIn('行',electrode_location(electrode_id))
        with self.assertRaises(ValueError):electrode_location(0)
        with self.assertRaises(ValueError):electrode_location(421)

    def test_global_reference_uses_all_design_polygons_and_one_target(self):
        from dmf.vision.registration_repeatability_gui import draw_global_reference
        import test_registration_workspace as fixtures
        class Canvas:
            def __init__(self):self.polygons=[];self.text=[]
            def delete(self,*args):pass
            def create_polygon(self,*args,**kwargs):self.polygons.append((args,kwargs))
            def create_text(self,*args,**kwargs):self.text.append((args,kwargs))
        canvas=Canvas();draw_global_reference(canvas,fixtures.design_fixture(),316)
        self.assertEqual(len(canvas.polygons),420)
        selected=[p for p in canvas.polygons if 'current_electrode' in p[1].get('tags',())]
        self.assertEqual(len(selected),1)
        self.assertIn('electrode_316',selected[0][1]['tags'])
        self.assertTrue(all(np.isfinite(p[0]).all() for p in canvas.polygons))
        self.assertTrue(any('1 → 20' in p[1].get('text','') for p in canvas.text))

    def test_repeat_report_defaults_to_new_timestamped_directory(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'repeat.json';repeat.save_new(path,review())
            run=subprocess.run([sys.executable,'run_registration_audit.py','repeat-report',str(path)],
                               capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            files=list(Path(temp).glob('reports/*/repeatability_result.json'))
            self.assertEqual(len(files),1)
            self.assertIsNone(json.loads(files[0].read_text())['rmse_between_rounds_px'])

    def test_blind_overlay_does_not_reveal_saved_clicks(self):
        from dmf.vision.registration_repeatability_gui import draft_overlay
        class Canvas:
            def __init__(self): self.lines=[]
            def create_line(self, *args, **kwargs): self.lines.append(args)
        canvas=Canvas(); draft_overlay(canvas, 2., None)
        self.assertEqual(canvas.lines, [])
        draft_overlay(canvas, 2., [10, 20])
        self.assertEqual(len(canvas.lines), 2)

    def test_cli_help_is_available_without_hardware(self):
        import subprocess, sys
        run=subprocess.run([sys.executable, 'run_registration_audit.py', '--help'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('prepare', run.stdout); self.assertIn('review', run.stdout)

    def test_residual_plot_uses_all_points_and_declares_arrow_gain(self):
        from dmf.vision.registration_audit_plotting import render_audit
        result=audit.recompute(fixture(), core_bounds=[0,0,10,10])
        with tempfile.TemporaryDirectory() as temp:
            render_audit(result, Path(temp), image_size=[100,80])
            integrity=json.loads((Path(temp)/'figure_integrity.json').read_text())
            self.assertEqual(integrity['check_points_plotted'], 2)
            self.assertEqual(integrity['arrow_gain'], 80)
            self.assertFalse(integrity['physical_accuracy_claim'])
            self.assertTrue((Path(temp)/'residual_vectors.pdf').is_file())
            self.assertTrue((Path(temp)/'residual_vectors.png').is_file())


if __name__ == '__main__': unittest.main()
