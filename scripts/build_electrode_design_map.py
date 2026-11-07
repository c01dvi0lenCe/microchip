"""Offline FBC6-3 shape-only design map. Does not load hardware or camera APIs."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from dmf.layout import CORNER_RESERVOIRS, SIDE_RESERVOIR_LARGE, cell_from_electrode_id
from dmf.vision.electrode_map import _grid_polygon, polygon_centroid


ORIENTATION = 'front_top_left_1_top_right_20_bottom_left_381_bottom_right_400'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def parse_regions(text, prefix='GTL'):
    """Strict subset for this source: absolute mm 4.5, one straight closed ring.

    Flashes outside regions are deliberately not electrodes (e.g. test pads).
    This is NOT a general Gerber/composited copper or exposure-surface parser.
    """
    if '%FSLAX45Y45*%' not in text or '%MOMM*%' not in text or '%MOIN*%' in text:
        raise ValueError('only absolute 4.5 millimetre Gerber coordinates supported')
    if re.search(r'%(?:LPC|LR|LM|LS|SR|MI|SF|OF|AS)', text):
        raise ValueError('clear polarity, repeats and coordinate transforms unsupported')
    bodies = re.findall(r'G36\*(.*?)G37\*', text, re.S)
    if len(bodies) != text.count('G36*') or len(bodies) != text.count('G37*'):
        raise ValueError('unbalanced region commands')
    result = []
    for index, body in enumerate(bodies, 1):
        clean = re.sub(r'G04[^*]*\*', '', body)
        commands = re.findall(r'G01X(-?\d+)Y(-?\d+)D0([12])\*', clean)
        residual = re.sub(r'G01X-?\d+Y-?\d+D0[12]\*', '', clean).strip()
        if residual or not commands or commands[0][2] != '2' or sum(d == '2' for x, y, d in commands) != 1:
            raise ValueError('unsupported arc, omitted coordinate or multiple region contours')
        points = [(int(x) / 100000., int(y) / 100000.) for x, y, d in commands]
        if points[-1] != points[0]:
            raise ValueError('source region must be explicitly closed')
        points = points[:-1]
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.is_empty or polygon.area <= 1e-10 or len(polygon.interiors):
            raise ValueError('invalid or degenerate region polygon')
        result.append(dict(source_region_key=f'{prefix}_R{index:04d}',
                           source_region_index=index,
                           source_region_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(),
                           polygon_gerber_mm=[list(p) for p in points], polygon=polygon))
    return result


def bind_regions(regions, profile):
    """Geometric matching is authorized by external human ID/direction evidence."""
    if profile.get('binding', {}).get('confirmed') is not True:
        raise ValueError('explicit user confirmation required for ID binding')
    if profile['binding'].get('orientation') != ORIENTATION:
        raise ValueError('unsupported or unconfirmed orientation')
    if len(regions) != 420:
        raise ValueError('exactly 420 source regions required')
    pitch = float(profile['pitch_mm'])
    anchor = profile['core_top_left_center_gerber_mm']
    if not math.isfinite(pitch) or pitch <= 0 or len(anchor) != 2 or not all(math.isfinite(v) for v in anchor):
        raise ValueError('invalid pitch or origin')
    ox, oy = anchor[0] - pitch / 2, anchor[1] + pitch / 2
    polygons = [r['polygon'] for r in regions]
    tree = STRtree(polygons)
    for i, polygon in enumerate(polygons):
        for j in tree.query(polygon):
            if int(j) > i and polygon.intersection(polygons[int(j)]).area > 1e-8:
                raise ValueError('overlapping or duplicate electrode geometry')
    available = []
    for region in regions:
        points = [[round(x - ox, 5), round(oy - y, 5)] for x, y in region['polygon_gerber_mm']]
        available.append((region, points, polygon_centroid(points)))
    output = []
    for eid in range(1, 421):
        cell = cell_from_electrode_id(eid)
        kind = ('core' if eid <= 400 else 'corner' if cell in CORNER_RESERVOIRS else
                'large' if cell in SIDE_RESERVOIR_LARGE else 'small')
        template = tuple((x * pitch, y * pitch) for x, y in _grid_polygon(cell))
        expected = polygon_centroid(template)
        tolerance = float(profile['match_tolerances_mm'][kind])
        if not math.isfinite(tolerance) or tolerance <= 0:
            raise ValueError('invalid matching tolerance')
        matches = [i for i, (_, _, center) in enumerate(available) if math.dist(center, expected) <= tolerance]
        if len(matches) != 1:
            raise ValueError(f'ID {eid}: expected one unique source contour, got {len(matches)}')
        region, points, center = available.pop(matches[0])
        polygon = region['polygon']
        map_polygon = Polygon(points)
        ref_polygon = Polygon(template)
        center_raw = polygon_centroid(region['polygon_gerber_mm'])
        label_point = map_polygon.centroid
        if not map_polygon.covers(label_point):
            label_point = map_polygon.representative_point()
        output.append(dict(control_id=eid, logical_row=cell[0], logical_col=cell[1],
                           geometry_class=kind, **{k: v for k, v in region.items() if k != 'polygon'},
                           polygon_map_mm=points, center_gerber_mm=list(center_raw), center_map_mm=list(center),
                           label_point_map_mm=[label_point.x, label_point.y],
                           center_definition='polygon area centroid, not bounding-box midpoint',
                           bbox_map_mm=list(map_polygon.bounds), area_mm2=polygon.area,
                           vertex_count=len(points), template_area_mm2=ref_polygon.area,
                           area_difference_percent=(polygon.area / ref_polygon.area - 1) * 100,
                           template_polygon_iou=map_polygon.intersection(ref_polygon).area / map_polygon.union(ref_polygon).area,
                           template_center_offset_mm=math.dist(center, expected),
                           binding_status=profile['binding']['status'], electrical_verified=False,
                           scan_row_zero_based=(eid - 1) // 20 if eid <= 400 else eid - 401,
                           scan_col_zero_based=(eid - 1) % 20 if eid <= 400 else 20))
    if available:
        raise ValueError('unassigned source contours remain')
    return output


def _csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _inspection_view(output, electrodes):
    """Engineering SVG/Pillow drawing, not a new manuscript figure or image edit."""
    palette = dict(core='#c8dfef', small='#87c5c8', large='#f1cc88', corner='#b6d39b')
    view = (-15., -19., 94., 104.)
    width, height = 2820, 3120
    sx, sy = width / view[2], height / view[3]
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    font_path = Path('C:/Windows/Fonts/arial.ttf')
    def font(size):
        return ImageFont.truetype(str(font_path), max(8, round(size * sy))) if font_path.is_file() else ImageFont.load_default(size=max(8, round(size * sy)))
    def point(p):
        return ((p[0] - view[0]) * sx, (p[1] - view[1]) * sy)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="235mm" height="260mm" viewBox="{" ".join(map(str, view))}">',
           '<rect x="-15" y="-19" width="94" height="104" fill="white"/>',
           '<g font-family="Arial, sans-serif">']
    def text(x, y, value, size=1., color='#183244', center=False):
        svg.append(f'<text x="{x:.6f}" y="{y:.6f}" font-size="{size}" fill="{color}" text-anchor="{"middle" if center else "start"}" dominant-baseline="middle">{value}</text>')
        draw.text(point((x, y)), value, font=font(size), fill=color, anchor='mm' if center else 'lm')
    text(-13, -16., '420-electrode design map | FBC6-3', 1.7)
    text(-13, -13.4, 'Geometry: Gerber outlines | IDs: user-confirmed PC layout', 1.02)
    text(-13, -11.4, 'Front view: 1 top-left; 20 top-right; 381 bottom-left; 400 bottom-right', .9)
    for row in electrodes:
        pts = row['polygon_map_mm']
        values = ' '.join(f'{x:.5f},{y:.5f}' for x, y in pts)
        color = palette[row['geometry_class']]
        svg.append(f'<polygon data-electrode-id="{row["control_id"]}" points="{values}" fill="{color}" stroke="#34454c" stroke-width="0.025"/>')
        xy = [point(p) for p in pts]
        draw.polygon(xy, fill=color)
        draw.line(xy + [xy[0]], fill='#34454c', width=1)
    for row in electrodes:
        eid = row['control_id']
        x, y = row['label_point_map_mm']
        text(x, y, str(eid), .85 if eid <= 400 else 1.15,
             '#b42926' if eid in {1, 20, 381, 400} else '#17313f', True)
    # Millimetre scale and coordinate arrows, not a fabricated camera scale.
    svg.append('<path d="M -11,79 H -1 M -11,78.6 V79.4 M -1,78.6 V79.4" stroke="#243d4b" fill="none" stroke-width="0.12"/>')
    draw.line([point((-11, 79)), point((-1, 79))], fill='#243d4b', width=4)
    for x in (-11, -1):
        draw.line([point((x, 78.6)), point((x, 79.4))], fill='#243d4b', width=3)
    text(-6, 80.3, '10 mm', .95, center=True)
    text(6, 78.7, 'Map axes: +X right, +Y down; unit mm', 1.)
    text(6, 80.6, 'No camera calibration / electrical continuity verification', .9)
    svg.append('</g></svg>')
    (output / 'electrode_top_view.svg').write_text('\n'.join(svg), encoding='utf-8')
    image.save(output / 'electrode_top_view.png', dpi=(304.8, 304.8))


def build(source, profile_path, output):
    source, profile_path, output = Path(source).resolve(), Path(profile_path).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'preserve existing design map: {output}')
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    if profile.get('schema') != 'dmf_electrode_design_profile_v1' or profile.get('source_kind') not in {'design_gerber', 'synthetic_fixture'}:
        raise ValueError('invalid or unspecified design source profile')
    source_hash = sha256(source)
    if source_hash != profile['source_sha256']:
        raise ValueError('source ZIP hash differs from approved version')
    with zipfile.ZipFile(source) as archive:
        copper_raw = archive.read('Gerber_TopLayer.GTL')
        mask_raw = archive.read('Gerber_TopSolderMaskLayer.GTS')
    regions = parse_regions(copper_raw.decode('utf-8-sig'))
    masks = parse_regions(mask_raw.decode('utf-8-sig'), 'GTS')
    rows = bind_regions(regions, profile)
    mask_union = unary_union([r['polygon'] for r in masks])
    for row in rows:
        polygon = Polygon(row['polygon_gerber_mm'])
        row['mask_polygon_overlap_fraction'] = polygon.intersection(mask_union).area / polygon.area
        row['exposed_surface_verified'] = False
    pitch = profile['pitch_mm']
    anchor = profile['core_top_left_center_gerber_mm']
    ox, oy = anchor[0] - pitch / 2, anchor[1] + pitch / 2
    document = dict(schema='dmf_electrode_design_map_v1', version='2026-10-21_fbc6_3_user_confirmed_v1',
                    source_kind=profile['source_kind'], source_zip=str(source), source_sha256=source_hash,
                    source_layers_sha256={name: hashlib.sha256(raw).hexdigest() for name, raw in
                                          [('Gerber_TopLayer.GTL', copper_raw), ('Gerber_TopSolderMaskLayer.GTS', mask_raw)]},
                    geometry_scope='Gerber top copper region outlines only; source confirmed shape-only use',
                    binding=profile['binding'],
                    coordinate_system=dict(unit='mm', source='native Gerber absolute X/Y',
                                           map='core nominal grid top-left origin; X right, Y down',
                                           transform_gerber_to_map=[[1, 0, -ox], [0, -1, oy], [0, 0, 1]],
                                           original_coordinate_quantum_mm=.00001, quantum_is_manufacturing_accuracy=False),
                    pitch_mm=pitch, center_definition='polygon area centroid', electrode_count=len(rows),
                    camera_calibration_performed=False, electrical_continuity_verified=False,
                    as_manufactured_geometry_verified=False, runtime_map_replaced=False, electrodes=rows)
    output.mkdir(parents=True)
    (output / 'electrode_design_map.json').write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'binding_profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    centers, vertices, comparison = [], [], []
    for r in rows:
        centers.append(dict(control_id=r['control_id'], geometry_class=r['geometry_class'],
                            center_x_mm=r['center_map_mm'][0], center_y_mm=r['center_map_mm'][1],
                            gerber_center_x_mm=r['center_gerber_mm'][0], gerber_center_y_mm=r['center_gerber_mm'][1],
                            area_mm2=r['area_mm2'], source_region_key=r['source_region_key'],
                            scan_row_zero_based=r['scan_row_zero_based'], scan_col_zero_based=r['scan_col_zero_based'],
                            binding_status=r['binding_status'], electrical_verified=False))
        for i, (raw, local) in enumerate(zip(r['polygon_gerber_mm'], r['polygon_map_mm'])):
            vertices.append(dict(control_id=r['control_id'], vertex_index=i, gerber_x_mm=raw[0], gerber_y_mm=raw[1],
                                 map_x_mm=local[0], map_y_mm=local[1]))
        comparison.append({key: r[key] for key in ('control_id', 'geometry_class', 'area_mm2', 'template_area_mm2',
                                                  'area_difference_percent', 'template_polygon_iou',
                                                  'template_center_offset_mm', 'mask_polygon_overlap_fraction')})
    _csv(output / 'electrode_centers.csv', centers)
    _csv(output / 'electrode_vertices.csv', vertices)
    _csv(output / 'template_comparison.csv', comparison)
    _inspection_view(output, rows)
    if sha256(source) != source_hash:
        raise ValueError('source changed during extraction')
    manifest = dict(schema='dmf_electrode_design_export_v1', created_utc=datetime.now(timezone.utc).isoformat(),
                    electrode_count=len(rows), source_sha256=source_hash,
                    binding_status=profile['binding']['status'], electrical_verified=False,
                    mask_unmatched_control_ids=[r['control_id'] for r in rows if r['mask_polygon_overlap_fraction'] < 1e-8],
                    source_code_sha256={str(p.relative_to(ROOT)): sha256(p) for p in
                                        [Path(__file__), ROOT / 'dmf/layout.py', ROOT / 'dmf/vision/electrode_map.py',
                                         ROOT / 'configs/electrode_map.yaml']},
                    profile_sha256=sha256(profile_path),
                    outputs_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--profile', type=Path, default=ROOT / 'configs/electrode_design_fbc6_3.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = build(args.source, args.profile, args.output)
    print(json.dumps(dict(electrode_count=result['electrode_count'], binding_status=result['binding_status'],
                         output=str(args.output), runtime_map_replaced=False), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
