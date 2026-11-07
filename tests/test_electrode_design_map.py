"""Synthetic geometric fixtures, not measured PCB/electrical results."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from dmf.vision.electrode_map import _grid_polygon
from dmf.layout import cell_from_electrode_id


def gerber(polygons):
    parts = ['G04 synthetic test fixture*', '%FSLAX45Y45*%', '%MOMM*%']
    for pts in polygons:
        parts.append('G36*')
        for i, (x, y) in enumerate(list(pts) + [pts[0]]):
            parts.append(f'G01X{round(x * 1e5)}Y{round(y * 1e5)}D0{2 if i == 0 else 1}*')
        parts.append('G37*')
    return '\n'.join(parts) + '\nM02*'


def fixture():
    return [tuple((x * 3.2 - 46.159, 169.962 - y * 3.2)
                  for x, y in _grid_polygon(cell_from_electrode_id(eid)))
            for eid in range(1, 421)]


def profile():
    return dict(schema='dmf_electrode_design_profile_v1', source_kind='synthetic_fixture',
                pitch_mm=3.2, core_top_left_center_gerber_mm=[-44.559, 168.362],
                binding=dict(confirmed=True, status='synthetic_test_fixture',
                             orientation='front_top_left_1_top_right_20_bottom_left_381_bottom_right_400'),
                match_tolerances_mm=dict(core=.005, small=.005, large=1.5, corner=2.5))


class DesignMapTests(unittest.TestCase):
    def test_mm_vertices_area_and_source_index(self):
        from scripts.build_electrode_design_map import parse_regions
        result = parse_regions(gerber([[(1, 2), (4, 2), (4, 6), (1, 6)]]))
        self.assertEqual(result[0]['polygon_gerber_mm'][0], [1., 2.])
        self.assertEqual(result[0]['source_region_key'], 'GTL_R0001')
        self.assertEqual(result[0]['polygon'].area, 12.)

    def test_unsupported_units_arcs_polarity_and_transforms_rejected(self):
        from scripts.build_electrode_design_map import parse_regions
        raw = gerber([[(0, 0), (1, 0), (1, 1)]])
        for text in (raw.replace('MOMM', 'MOIN'), raw.replace('G01X100000Y0D01', 'G02X100000Y0D01'),
                     raw.replace('G36*', '%LPC*%\nG36*'), raw.replace('G36*', '%LR90*%\nG36*')):
            with self.subTest(text=text[:70]), self.assertRaises(ValueError):
                parse_regions(text)

    def test_invalid_and_multicontour_regions_rejected(self):
        from scripts.build_electrode_design_map import parse_regions
        with self.assertRaises(ValueError):
            parse_regions(gerber([[(0, 0), (1, 1), (0, 1), (1, 0)]]))
        raw = gerber([[(0, 0), (1, 0), (1, 1)]])
        with self.assertRaises(ValueError):
            parse_regions(raw.replace('G37*', 'G01X200000Y200000D02*\nG37*'))

    def test_user_confirmation_required(self):
        from scripts.build_electrode_design_map import bind_regions, parse_regions
        cfg = profile()
        cfg['binding']['confirmed'] = False
        with self.assertRaisesRegex(ValueError, 'confirm'):
            bind_regions(parse_regions(gerber(fixture())), cfg)

    def test_full_bijection_and_user_confirmed_four_corners(self):
        from scripts.build_electrode_design_map import bind_regions, parse_regions
        result = bind_regions(parse_regions(gerber(fixture())), profile())
        self.assertEqual([r['control_id'] for r in result], list(range(1, 421)))
        by_id = {r['control_id']: r for r in result}
        for eid, point in [(1, (1.6, 1.6)), (20, (62.4, 1.6)), (381, (1.6, 62.4)), (400, (62.4, 62.4))]:
            for a, b in zip(by_id[eid]['center_map_mm'], point):
                self.assertAlmostEqual(a, b, places=6)
        self.assertFalse(by_id[1]['electrical_verified'])

    def test_source_order_does_not_determine_id(self):
        from scripts.build_electrode_design_map import bind_regions, parse_regions
        forward = bind_regions(parse_regions(gerber(fixture())), profile())
        reverse = bind_regions(parse_regions(gerber(list(reversed(fixture())))), profile())
        self.assertEqual([r['polygon_map_mm'] for r in forward], [r['polygon_map_mm'] for r in reverse])
        self.assertNotEqual(forward[0]['source_region_key'], reverse[0]['source_region_key'])

    def test_missing_and_duplicate_geometry_rejected(self):
        from scripts.build_electrode_design_map import bind_regions, parse_regions
        for polygons in (fixture()[:-1], fixture()[:-1] + [fixture()[0]]):
            with self.assertRaises(ValueError):
                bind_regions(parse_regions(gerber(polygons)), profile())

    def test_outputs_keep_provenance_and_all_labels_and_refuse_overwrite(self):
        from scripts.build_electrode_design_map import build, sha256
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.zip'
            with zipfile.ZipFile(source, 'w') as z:
                z.writestr('Gerber_TopLayer.GTL', gerber(fixture()))
                z.writestr('Gerber_TopSolderMaskLayer.GTS', gerber(fixture()[:400]))
            cfg = profile()
            cfg['source_sha256'] = sha256(source)
            config_path = root / 'profile.json'
            config_path.write_text(json.dumps(cfg), encoding='utf-8')
            result = build(source, config_path, root / 'out')
            self.assertEqual(result['electrode_count'], 420)
            document = json.loads((root / 'out/electrode_design_map.json').read_text(encoding='utf-8'))
            self.assertEqual(document['source_kind'], 'synthetic_fixture')
            self.assertEqual(document['coordinate_system']['unit'], 'mm')
            self.assertFalse(document['camera_calibration_performed'])
            svg = (root / 'out/electrode_top_view.svg').read_text(encoding='utf-8')
            self.assertEqual(svg.count('data-electrode-id='), 420)
            self.assertTrue((root / 'out/electrode_top_view.png').is_file())
            with self.assertRaises(FileExistsError):
                build(source, config_path, root / 'out')


if __name__ == '__main__':
    unittest.main()
