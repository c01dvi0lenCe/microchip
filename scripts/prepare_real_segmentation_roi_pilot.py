"""Prepare native real-video annotation candidates; never create reviewed GT."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dmf.segmentation_research.roi_pilot import (
    native_roi, all_foreground_draft, candidate_row, validate_proposed_groups,
    training_readiness,
)
from dmf.segmentation_research.data import sha256, write_csv
from dmf.vision.image_io import read_image, write_image
from dmf.vision.pilot_annotation import PilotWorkspace


def spread_select(items, count):
    """Deterministic temporal spread without replacement or seed selection."""
    if count < 0 or count > len(items):
        raise ValueError('insufficient unique candidates')
    if not count:
        return []
    return [items[int(i)] for i in np.linspace(0, len(items) - 1, count).round()]


def native_crop(image, roi):
    x, y, w, h = roi
    if any(int(v) != v for v in roi) or min(x, y) < 0 or min(w, h) <= 0:
        raise ValueError('ROI must contain valid integer coordinates')
    if x + w > image.shape[1] or y + h > image.shape[0]:
        raise ValueError('ROI exceeds original pixels')
    return image[y:y+h, x:x+w].copy()


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def save_png(path, image):
    if not write_image(Path(path), image):
        raise OSError(f'cannot write {path}')


def build_selection(dataset):
    inventory = json.loads((dataset/'inventory.json').read_text(encoding='utf-8'))
    videos = inventory['videos']
    if len(videos) != 4:
        raise ValueError('this approved Pilot expects the four inventoried videos')
    movement = read_csv(dataset/'分类数据清单_v2/全部相邻迁移候选_逐滴逐步.csv')
    topology = read_csv(dataset/'分类数据清单_v2/分裂合并供液_逐候选视觉筛查.csv')
    quotas = [(16, 8, 8), (16, 8, 8), (3, 1, 1), (5, 3, 3)]
    selected, occupied = [], set()
    for vi, (video, (n_steps, n_top, n_bg)) in enumerate(zip(videos, quotas)):
        vid = video['video_id']
        geo_root = dataset/'420电极_自动同名特征核对_v2'/vid
        centers = {int(r['control_id']): (float(r['center_u_px']), float(r['center_v_px']))
                   for r in read_csv(geo_root/'420电极中心_原始像素域.csv')}
        screens = read_csv(dataset/vid/'逐帧筛查.csv')
        split = 'train' if vi < 2 else 'val'

        def add(frame, roi, category, group, **extra):
            frame = int(frame)
            # Keep a unique original source frame, even across categories.
            if (vid, frame) in occupied:
                raise ValueError(f'candidate selection duplicates {vid}:{frame}')
            occupied.add((vid, frame))
            selected.append(dict(video_id=vid, source=video['source'],
                source_sha256=video['sha256'], source_frame_id=frame,
                receive_s=float(screens[frame]['receive_relative_s']),
                roi_xywh=roi, category=category, operation_group=group,
                proposed_split=split, **extra))

        accepted = [r for r in movement if r['video_id'] == vid and
                    r['automatic_position_check_passed'] == 'True']
        accepted.sort(key=lambda r: int(r['start_frame']))
        for step in spread_select(accepted, n_steps):
            start, end = int(step['start_frame']), int(step['end_frame_inclusive'])
            source, target = int(step['source_electrode']), int(step['target_electrode'])
            midpoint = np.mean([centers[source], centers[target]], axis=0)
            roi = native_roi(midpoint, (512, 512), (video['width'], video['height']))
            for fraction, stage in [(0.1, 'early_interval'), (0.5, 'mid_interval'), (0.9, 'late_interval')]:
                add(round(start + fraction*(end-start)), roi, 'migration_candidate',
                    f'{vid}:transaction_{step["sequence"]}',
                    phase_candidate=stage, operation_candidate='transport',
                    source_electrode_recorded=source, target_electrode_recorded=target,
                    request_id_recorded=step['request_id'],
                    track_draft=step['track_draft'],
                    scene_qualification='automatic_position_candidate_not_GT')

        events = [r for r in topology if r['video_id'] == vid]
        events.sort(key=lambda r: int(r['start_frame']))
        for event in spread_select(events, n_top):
            x, y, w, h = json.loads(event['roi_full_px'])
            roi = native_roi((x+w/2, y+h/2), (768, 768), (video['width'], video['height']))
            for frame, phase in [(int(event['transition_before_frame'])-2, 'before_topology_candidate'),
                                 (int(event['transition_after_frame'])+2, 'after_topology_candidate')]:
                while (vid, frame) in occupied:
                    frame += 1
                if frame > int(event['end_frame_inclusive']):
                    raise ValueError('cannot select unique topology frame')
                add(frame, roi, 'complex_candidate', event['candidate_id'],
                    phase_candidate=phase, operation_candidate=event['operation_labels'],
                    source_electrode_recorded='', target_electrode_recorded='',
                    request_id_recorded='', track_draft='',
                    scene_qualification='visual_screening_candidate_not_human_GT')

        # Core interior backgrounds, away from ALL screened component bounding boxes.
        # Detection misses remain possible: these are negative candidates, not empty GT.
        possible_centers = [centers[i] for i in (64, 78, 124, 138, 244, 258, 324, 338)]
        bg_frames = spread_select(list(range(20, int(video['frames'])-20)), n_bg)
        for bi, frame in enumerate(bg_frames):
            while (vid, frame) in occupied:
                frame += 1
            components = json.loads(screens[frame]['components_json'])
            chosen = None
            for c in possible_centers[bi % len(possible_centers):] + possible_centers[:bi % len(possible_centers)]:
                roi = native_roi(c, (512, 512), (video['width'], video['height']))
                x, y, w, h = roi
                overlaps = False
                for component in components:
                    bx, by, bw, bh = [4*float(v) for v in component['bbox']]
                    if x < bx+bw+40 and x+w > bx-40 and y < by+bh+40 and y+h > by-40:
                        overlaps = True
                        break
                if not overlaps:
                    chosen = roi
                    break
            if chosen is None:
                raise ValueError('no component-free background candidate; review before changing quota')
            add(frame, chosen, 'empty_or_interference_candidate', f'{vid}:background_{bi:02d}',
                phase_candidate='background_candidate', operation_candidate='none_confirmed',
                source_electrode_recorded='', target_electrode_recorded='',
                request_id_recorded='', track_draft='',
                scene_qualification='screening_empty_not_human_confirmed')
    if len(selected) != 180:
        raise ValueError(f'expected 180 unique candidates, got {len(selected)}')
    return inventory, sorted(selected, key=lambda r: (r['video_id'], r['source_frame_id']))


def extract(dataset, output):
    if output.exists():
        raise FileExistsError('use a new version; never overwrite an annotation workspace')
    inventory, plan = build_selection(dataset)
    inputs = {r['path']: r['sha256'] for r in inventory['source_files']}
    for p in [dataset/'inventory.json',
              dataset/'分类数据清单_v2/全部相邻迁移候选_逐滴逐步.csv',
              dataset/'分类数据清单_v2/分裂合并供液_逐候选视觉筛查.csv']:
        inputs[str(p)] = sha256(p)
    for video in inventory['videos']:
        vid = video['video_id']
        for p in [dataset/vid/'逐帧筛查.csv',
                  dataset/'420电极_自动同名特征核对_v2'/vid/'420电极中心_原始像素域.csv',
                  dataset/'420电极_自动同名特征核对_v2'/vid/'calibration_candidate_manifest.json']:
            inputs[str(p)] = sha256(p)
    for path, digest in inputs.items():
        if sha256(path) != digest:
            raise ValueError(f'source hash changed: {path}')
    output.mkdir(parents=True)
    for sub in ['frames', 'masks_draft', 'exclusions_draft', 'references', 'previews']:
        (output/sub).mkdir()
    rows, clips, references, extraction_qa = [], [], {}, []
    grouped = defaultdict(list)
    for i, task in enumerate(plan, 1):
        task['sample_id'] = f'ROI{i:03d}'
        grouped[task['video_id']].append(task)
    save_json(output/'selection_plan.json', plan)
    for vid, tasks in grouped.items():
        print(f'extracting {vid}: {len(tasks)} native crops', flush=True)
        geo_root = dataset/'420电极_自动同名特征核对_v2'/vid
        polygon_path = geo_root/'420电极轮廓_原始像素域.json'
        polygons = json.loads(polygon_path.read_text(encoding='utf-8'))['electrodes']
        inputs[str(polygon_path)] = sha256(polygon_path)
        # Only a review proposal. Physical reservoir limits need human acceptance.
        exclusion_full = np.zeros((3648, 5472), np.uint8)
        for electrode in polygons:
            if int(electrode['control_id']) > 400:
                cv2.fillPoly(exclusion_full, [np.rint(electrode['polygon_native_px']).astype(np.int32)], 255)
        capture = cv2.VideoCapture(tasks[0]['source'])
        if not capture.isOpened():
            raise ValueError('cannot open native source video')
        try:
            ok, reference = capture.read()
            if not ok or reference.shape[:2] != (3648, 5472):
                raise ValueError('native reference decode failed')
            ref_name = f'references/{vid}.png'
            save_png(output/ref_name, reference)
            references[vid] = dict(image=ref_name, source_video=tasks[0]['source'],
                source_frame_id=0, width=5472, height=3648,
                image_sha256=sha256(output/ref_name))
            for task in tasks:
                frame = task['source_frame_id']
                if not capture.set(cv2.CAP_PROP_POS_FRAMES, frame):
                    raise ValueError('native source seeking failed')
                ok, full = capture.read()
                if not ok or int(round(capture.get(cv2.CAP_PROP_POS_FRAMES)))-1 != frame:
                    raise ValueError(f'frame index decode mismatch {vid}:{frame}')
                image = native_crop(full, task['roi_xywh'])
                sample = task['sample_id']
                image_name = f'frames/{sample}.png'
                draft_name = f'masks_draft/{sample}.png'
                exclude_name = f'exclusions_draft/{sample}.png'
                save_png(output/image_name, image)
                save_png(output/draft_name, all_foreground_draft(image))
                save_png(output/exclude_name, native_crop(exclusion_full, task['roi_xywh']))
                row = candidate_row(sample, vid, task['source_sha256'], frame,
                    task['roi_xywh'], task['receive_s'], task['category'],
                    task['proposed_split'], task['operation_group'], task['track_draft'])
                row.update(frame_path=image_name, draft_mask_path=draft_name,
                    exclusion_draft_path=exclude_name, exclusion_mask_path='',
                    exclusion_definition='peripheral_design_polygon_proposal_requires_human_review',
                    source_electrode=task['source_electrode_recorded'],
                    target_electrode=task['target_electrode_recorded'],
                    task_target_electrode_recorded=task['target_electrode_recorded'],
                    task_target_identity_reviewed=False,
                    operation_candidate=task['operation_candidate'],
                    phase_candidate=task['phase_candidate'],
                    scene_qualification=task['scene_qualification'],
                    map_status='automatic_candidate_not_runtime_approved',
                    frame_path_sha256=sha256(output/image_name),
                    foreground_rule_version='all_actual_droplets_v1',
                    split_protocol='same_capture_internal_research_only',
                    instance_mask_path='', instance_manifest_path='instances_to_review.csv',
                    image_quality_reviewed=False, grouping_verified=False,
                    lighting_condition='not_independently_classified',
                    notes='ALL actual droplets, not just dark pixels. No state/arrival GT.')
                rows.append(row)
                clips.append(dict(clip_id=sample, video_id=vid, batch_id='2026-11-02_shared_or_unknown',
                    source=task['source'], source_sha256=task['source_sha256'],
                    path=task['source'], start_frame=frame, end_frame_exclusive=frame+1,
                    roi_xywh=task['roi_xywh'], preview_only=False,
                    add_frames_supported=False))
                saved = read_image(output/image_name, cv2.IMREAD_COLOR)
                if not np.array_equal(saved, image):
                    raise ValueError('PNG crop pixels differ from native frame')
                extraction_qa.append(dict(sample_id=sample, native_shape=list(image.shape),
                    source_frame_id=frame, png_roundtrip_exact=True,
                    png_sha256=sha256(output/image_name)))
        finally:
            capture.release()
    rows.sort(key=lambda r: r['sample_id'])
    group_qa = validate_proposed_groups(rows)
    # Reviewer GUI edits only semantic masks. Additional approval flags remain false.
    payload = dict(schema='dmf_pilot_review', version=1, dataset=str(dataset),
        clips=clips, references=references, calibrations={}, rows=rows,
        input_sha256=inputs, review_scope='segmentation_only_all_actual_droplets',
        split_status='proposed_internal_only_not_released',
        instances_are_GT=False,
        draft_generation=dict(algorithm='all_foreground_dark_proposal',
            ground_truth=False, component_policy='all_candidate_components'))
    save_json(output/'workspace.json', payload)
    workspace = PilotWorkspace(output)
    workspace.persist()
    write_csv(output/'180张候选ROI_分组与来源清单.csv', rows)
    write_csv(output/'训练验证建议划分_未放行.csv', [dict(sample_id=r['sample_id'],
        parent_video_id=r['parent_video_id'], operation_group=r['operation_group'],
        instance_id_draft=r['instance_id_draft'], capture_group=r['capture_group'],
        proposed_split=r['proposed_split'], actual_split=r['split'],
        grouping_verified=False, formal_test_eligible=False) for r in rows])
    write_csv(output/'instances_to_review.csv', [dict(sample_id=r['sample_id'],
        instance_id='', instance_id_draft=r['instance_id_draft'],
        instance_mask_value='', task_target_instance_id='',
        task_target_electrode_recorded=r['task_target_electrode_recorded'],
        parent_instance_ids='', child_instance_ids='', bridge_status='unreviewed',
        connectivity_reviewed=False, instances_reviewed=False) for r in rows])
    for path, digest in inputs.items():
        if sha256(path) != digest:
            raise ValueError('input changed during extraction')
    audit = dict(candidate_count=len(rows), reviewed_masks=0, actual_split_counts=dict(Counter(r['split'] for r in rows)),
        proposed_split_counts=dict(Counter(r['proposed_split'] for r in rows)),
        categories=dict(Counter(r['category'] for r in rows)),
        per_video=dict(Counter(r['parent_video_id'] for r in rows)),
        extraction_checks=extraction_qa, input_files=len(inputs),
        input_hashes_unchanged=True, proposed_group_check=group_qa,
        training_readiness=training_readiness(rows), formal_test_released=False,
        simulation=False, models_trained=0)
    save_json(output/'准备核验.json', audit)
    overview(output, rows)
    print(json.dumps({k:v for k,v in audit.items() if k not in ['extraction_checks','training_readiness']}, ensure_ascii=False, indent=2))
    return output


def overview(output, rows):
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    font = ImageFont.truetype(str(font_path), 17) if font_path.exists() else ImageFont.load_default()
    for page, start in enumerate(range(0, len(rows), 20), 1):
        sheet = Image.new('RGB', (1400, 1200), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(rows[start:start+20]):
            image = read_image(output/row['frame_path'], cv2.IMREAD_COLOR)
            thumb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            thumb.thumbnail((260, 245))
            x, y = (i % 5)*280, (i//5)*300
            sheet.paste(thumb, (x+(280-thumb.width)//2, y))
            draw.text((x+8, y+248), f'{row["sample_id"]}  f{row["source_frame_id"]}', fill='#17395a', font=font)
            draw.text((x+8, y+273), '候选 / 未审核', fill='#8a4f35', font=font)
        sheet.save(output/'previews'/f'候选总览_{page:02d}.jpg', quality=95)


def verify_native(output):
    """Independent capture pass: compare all saved ROIs with original AVI pixels."""
    payload = json.loads((output/'workspace.json').read_text(encoding='utf-8'))
    clips = {r['clip_id']: r for r in payload['clips']}
    by_video = defaultdict(list)
    for row in payload['rows']:
        by_video[row['parent_video_id']].append(row)
    checks = []
    for vid, rows in by_video.items():
        cap = cv2.VideoCapture(clips[rows[0]['video_id']]['source'])
        try:
            for row in rows:
                frame = int(row['source_frame_id'])
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
                ok, full = cap.read()
                if not ok or int(round(cap.get(cv2.CAP_PROP_POS_FRAMES)))-1 != frame:
                    raise ValueError('independent decoder frame identity mismatch')
                roi = [int(row[k]) for k in ['roi_x','roi_y','width','height']]
                saved = read_image(output/row['frame_path'], cv2.IMREAD_COLOR)
                exact = np.array_equal(saved, native_crop(full, roi))
                if not exact:
                    raise ValueError('independent native crop mismatch')
                checks.append(dict(sample_id=row['sample_id'], native_redecode_exact=True))
        finally:
            cap.release()
    result = dict(samples=len(checks), all_native_redecode_exact=True, checks=checks,
        source_audit=PilotWorkspace(output).audit_inputs())
    save_json(output/'原视频独立重解码核验.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'checks'}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        verify_native(args.output.resolve())
    else:
        if args.dataset is None:
            parser.error('--dataset is required for preparation')
        extract(args.dataset.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
