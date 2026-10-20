"""Offline Pilot preparation and explicit human review; never synthesize GT."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

import cv2
import numpy as np

from .algorithms.threshold import ThresholdConfig, ThresholdSegmenter
from .calibration import ArrayGridCalibration
from .config import load_yaml
from .contracts import DropletState, FramePacket
from .dataset import read_csv_rows, write_csv_rows
from .electrode_map import ElectrodeMap
from .image_io import read_image, write_image


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _id(value):
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError(f'Unsafe input identifier: {value}')
    return value


def _image(path, flags=cv2.IMREAD_COLOR):
    image = read_image(Path(path), flags)
    if image is None:
        raise ValueError(f'Cannot read image: {path}')
    return image


def _write_image(path, image):
    if not write_image(Path(path), image):
        raise OSError(f'Cannot save image: {path}')


def _json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def draft_mask(image, threshold=55):
    threshold=int(threshold)
    if not 0<=threshold<=255:raise ValueError('Draft threshold must be 0..255')
    algorithm = ThresholdSegmenter(ThresholdConfig(color_space='bgr', lower=(0,0,0),
        upper=(threshold,threshold,threshold), min_area_px=40, morphology_kernel=3))
    working=image
    # Dark orange background is not dark in all channels. Border components are
    # excluded only from proposals; source pixels and human GT are never changed.
    for _ in range(5):
        mask=algorithm.process(FramePacket('draft',0,0,'draft_only',working)).mask
        if not (mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any()):return mask
        working=working.copy();working[mask>0]=255
    return np.zeros(image.shape[:2],np.uint8)


def translated_map(config, roi_x, roi_y):
    corners = tuple((float(x)-roi_x, float(y)-roi_y) for x, y in config['core_corners_px'])
    calibration = ArrayGridCalibration(corners, pitch_mm=float(config['pitch_mm']))
    overrides = {int(key): tuple((float(x)-roi_x, float(y)-roi_y) for x,y in polygon)
        for key, polygon in config.get('pixel_overrides', {}).items()}
    return ElectrodeMap.from_calibration(calibration, overrides)


def _new_row(original, clip, frame_path, mask_path):
    return dict(video_id=clip['clip_id'], experiment_id=clip['clip_id'], batch_id=clip['batch_id'],
        frame_id=int(original['frame_id']), timestamp_s=float(original['timestamp_s']),
        timestamp_source='container_fps_unverified', frame_path=frame_path, mask_path='',
        source_electrode='', target_electrode='', state_gt='Unknown', state_draft='Unknown',
        lighting_condition='', notes='', parent_video_id=clip['video_id'],
        source_frame_id=int(original['source_frame_id']), roi_x=int(original['roi_x']),
        roi_y=int(original['roi_y']), draft_mask_path=mask_path, working_mask_path='',
        mask_reviewed=False, state_reviewed=False, map_version='', split='unassigned')


def prepare_pilot(dataset, output):
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError('Review workspace must not be inside the original dataset')
    if output.exists():
        raise FileExistsError('Review output already exists; open it instead of overwriting')
    clips = json.loads((dataset/'clips_manifest.json').read_text(encoding='utf-8'))
    originals = read_csv_rows(dataset/'annotations_to_label.csv')
    if not clips or not originals:
        raise ValueError('No accepted clips or annotation frames')
    lookup = {_id(clip['clip_id']): clip for clip in clips}
    if len(lookup) != len(clips):
        raise ValueError('Duplicate clip IDs')
    output.mkdir(parents=True)
    references, inputs, rows, keys = {}, {}, [], set()
    for path in (dataset/'clips_manifest.json', dataset/'annotations_to_label.csv'):
        inputs[str(path)] = sha256(path)
    for original in originals:
        clip = lookup[original['video_id']]
        parent = _id(clip['video_id'])
        index = int(original['frame_id'])
        if (clip['clip_id'], index) in keys:
            raise ValueError('Duplicate annotation frame')
        keys.add((clip['clip_id'], index))
        if int(original['source_frame_id']) != int(clip['start_frame']) + index:
            raise ValueError('Original/clip frame correspondence is inconsistent')
        if [int(original['roi_x']), int(original['roi_y'])] != list(clip['roi_xywh'][:2]):
            raise ValueError('Annotation ROI offset differs from clip manifest')
        source_image = Path(original['image_path'])
        image = _image(source_image)
        if image.shape[:2] != (int(clip['roi_xywh'][3]), int(clip['roi_xywh'][2])):
            raise ValueError('Annotation image dimensions differ from fixed clip ROI')
        name = f'{clip["clip_id"]}_{index:06d}.png'
        frame_path = 'frames/' + name
        draft_path = 'masks_draft/' + name
        (output/'frames').mkdir(exist_ok=True)
        shutil.copy2(source_image, output/frame_path)
        inputs[str(source_image)] = sha256(source_image)
        if sha256(output/frame_path) != inputs[str(source_image)]:
            raise OSError('Annotation frame copy failed hash verification')
        _write_image(output/draft_path, draft_mask(image))
        rows.append(_new_row(original, clip, frame_path, draft_path))
        if parent not in references:
            source = Path(clip['source'])
            digest = sha256(source)
            if clip.get('source_sha256') and digest != clip['source_sha256']:
                raise ValueError('Original video hash differs from accepted dataset')
            inputs[str(source)] = digest
            capture = cv2.VideoCapture(str(source))
            try:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(original['source_frame_id']))
                ok, full_frame = capture.read()
                if not ok:
                    raise ValueError(f'Cannot decode calibration reference from {source}')
            finally:
                capture.release()
            if not np.array_equal(full_frame[int(original['roi_y']):int(original['roi_y'])+image.shape[0],
                    int(original['roi_x']):int(original['roi_x'])+image.shape[1]], image):
                raise ValueError('Cropped annotation pixels do not match the original video frame')
            reference_path = f'references/{parent}.png'
            _write_image(output/reference_path, full_frame)
            references[parent] = dict(image=reference_path, source_video=str(source),
                source_frame_id=int(original['source_frame_id']), width=full_frame.shape[1],
                height=full_frame.shape[0], image_sha256=sha256(output/reference_path))
    for path, digest in inputs.items():
        if sha256(path) != digest:
            raise ValueError(f'Input changed during preparation: {path}')
    payload = dict(schema='dmf_pilot_review', version=1, dataset=str(dataset),
        clips=clips, references=references, calibrations={}, rows=rows, input_sha256=inputs,
        draft_generation=dict(algorithm='ThresholdSegmenter',color_space='bgr',upper=[55,55,55],
            border_components='excluded_from_proposals',ground_truth=False))
    _json(output/'workspace.json', payload)
    workspace = PilotWorkspace(output)
    workspace.persist()
    workspace.contact_sheet()
    return workspace.report()


class PilotWorkspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        raw=(self.root/'workspace.json').read_bytes()
        self.data = json.loads(raw.decode('utf-8'))
        self.loaded_hash=hashlib.sha256(raw).hexdigest()
        if self.data.get('schema') != 'dmf_pilot_review' or self.data.get('version') != 1:
            raise ValueError('Unsupported Pilot review workspace')
        self.rows = self.data['rows']
        self.clips = {clip['clip_id']: clip for clip in self.data['clips']}

    def images(self, index):
        row = self.rows[index]
        image = _image(self.root/row['frame_path'])
        path = row['working_mask_path'] or row['mask_path'] or row['draft_mask_path']
        return image, _image(self.root/path, cv2.IMREAD_GRAYSCALE)

    def map_config(self, parent):
        entry = self.data['calibrations'].get(parent)
        return load_yaml(self.root/entry['path']) if entry else None

    def confirm_layout(self, pitch):
        pitch=float(pitch)
        if not math.isfinite(pitch) or pitch<=0:raise ValueError('Measured pitch must be positive')
        self.data['physical_layout']=dict(pitch_mm=pitch,numbering='matches_upper_computer',
            core_corner_ids=[1,20,400,381],confirmation='explicit_user_confirmation',
            image_registration_confirmed=False)
        self.persist()

    def crop_map(self, index):
        row = self.rows[index]
        config = self.map_config(row['parent_video_id'])
        return translated_map(config, row['roi_x'], row['roi_y']) if config else None

    def save_calibration(self, parent, corners, pitch, *, confirmed=False):
        reference = self.data['references'][parent]
        points = np.asarray(corners, np.float32)
        if points.shape != (4,2) or not np.isfinite(points).all():
            raise ValueError('Provide four finite outer corners: ID1, ID20, ID400, ID381')
        if abs(cv2.contourArea(points)) <= 1 or not cv2.isContourConvex(points):
            raise ValueError('Corners must form a nondegenerate convex quadrilateral')
        if np.any(points[:,0]<0) or np.any(points[:,0]>reference['width']) or \
                np.any(points[:,1]<0) or np.any(points[:,1]>reference['height']):
            raise ValueError('Corners must be inside the full reference image')
        if not math.isfinite(float(pitch)) or float(pitch) <= 0:
            raise ValueError('Measured centre-to-centre pitch must be positive')
        version = uuid.uuid4().hex
        config = dict(rows=20, cols=20, pitch_mm=float(pitch), core_corners_px=points.tolist(),
            pixel_overrides={}, calibration_confirmed=bool(confirmed), map_version=version,
            reference_image=reference['image'], reference_sha256=reference['image_sha256'],
            corner_order='logical ID1 / ID20 / ID400 / ID381 outer boundary corners')
        old = self.map_config(parent)
        if old:
            config['pixel_overrides'] = old.get('pixel_overrides', {})
        import yaml
        path = f'maps/{parent}_{version[:12]}.yaml'
        (self.root/'maps').mkdir(exist_ok=True)
        (self.root/path).write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
        self.data['calibrations'][parent] = dict(path=path, confirmed=bool(confirmed), version=version)
        self.persist()
        return self.root/path

    def review(self, index, mask, *, mask_reviewed=False, state_reviewed=False,
               source='', target='', state='Unknown', notes=''):
        row = self.rows[index]
        image = _image(self.root/row['frame_path'])
        if mask.dtype != np.uint8 or mask.shape != image.shape[:2] or not set(np.unique(mask)).issubset({0,255}):
            raise ValueError('Mask must be same-size uint8 binary PNG (0/255)')
        if state not in {value.value for value in DropletState}:
            raise ValueError('Invalid state label')
        source, target = (int(value) if str(value).strip() else '' for value in (source,target))
        if any(value != '' and not 1<=value<=420 for value in (source,target)):
            raise ValueError('Source/target must be electrode IDs 1..420 or blank')
        entry = self.data['calibrations'].get(row['parent_video_id'], {})
        if state_reviewed:
            if not mask_reviewed or not entry.get('confirmed') or source == '' or target == '':
                raise ValueError('State GT requires reviewed mask, confirmed map and explicit source/target')
            if state != 'Unknown' and not mask.any():
                raise ValueError('A known droplet state requires a visible droplet mask')
            electrode_map = self.crop_map(index)
            if any(value>400 and electrode_map[value].geometry_source!='calibrated' for value in (source,target)):
                raise ValueError('Peripheral source/target needs a measured pixel_overrides polygon')
        name = f'{row["video_id"]}_{row["frame_id"]:06d}_{uuid.uuid4().hex[:12]}.png'
        path = ('masks/' if mask_reviewed else 'working_masks/') + name
        _write_image(self.root/path, mask)
        row.update(working_mask_path=path, mask_path=path if mask_reviewed else '',
            mask_reviewed=bool(mask_reviewed), state_reviewed=bool(state_reviewed),
            source_electrode=source, target_electrode=target, state_draft=state,
            state_gt=state if state_reviewed else 'Unknown',
            map_version=entry.get('version',''), notes=str(notes))
        self.persist()

    def add_frame(self, clip_id, frame_id):
        clip = self.clips[clip_id]
        frame_id = int(frame_id)
        if any(row['video_id']==clip_id and row['frame_id']==frame_id for row in self.rows):
            raise ValueError('This frame is already in the review workspace')
        if not 0<=frame_id<int(clip['end_frame_exclusive'])-int(clip['start_frame']):
            raise ValueError('Frame index is outside this clip')
        if clip.get('clip_sha256') and sha256(clip['path']) != clip['clip_sha256']:
            raise ValueError('Lossless clip changed since preparation')
        capture = cv2.VideoCapture(str(clip['path']))
        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES,frame_id)
            ok,image=capture.read()
            if not ok:raise ValueError('Cannot decode requested clip frame')
        finally:capture.release()
        if image.shape[:2] != (int(clip['roi_xywh'][3]),int(clip['roi_xywh'][2])):
            raise ValueError('Use the lossless cropped clip, not the original full video or viewing MP4')
        name=f'{_id(clip_id)}_{frame_id:06d}.png';frame_path='frames/'+name;mask_path='masks_draft/'+name
        _write_image(self.root/frame_path,image);_write_image(self.root/mask_path,draft_mask(image))
        self.rows.append(_new_row(dict(frame_id=frame_id,timestamp_s=frame_id/float(clip['fps']),
            source_frame_id=int(clip['start_frame'])+frame_id,roi_x=clip['roi_xywh'][0],roi_y=clip['roi_xywh'][1]),
            clip,frame_path,mask_path))
        self.persist()
        return len(self.rows)-1

    def _effective(self, row):
        record=dict(row)
        entry=self.data['calibrations'].get(row['parent_video_id'],{})
        valid=row['state_reviewed'] and entry.get('confirmed') and row['map_version']==entry.get('version')
        if not valid:record['state_gt']='Unknown';record['state_reviewed']=False
        return record

    def report(self):
        effective=[self._effective(row) for row in self.rows]
        counts={state.value:sum(row['state_reviewed'] and row['state_gt']==state.value for row in effective)
            for state in DropletState if state is not DropletState.UNKNOWN}
        return dict(frames=len(self.rows), clips=len(self.clips),
            physical_layout=self.data.get('physical_layout'),
            reference_videos=len(self.data['references']),
            confirmed_maps=sum(bool(entry['confirmed']) for entry in self.data['calibrations'].values()),
            mask_reviewed_frames=sum(row['mask_reviewed'] for row in self.rows),
            state_reviewed_frames=sum(row['state_reviewed'] for row in effective),
            state_counts=counts, states_without_reviewed_gt=[key for key,value in counts.items() if not value],
            measured_timing_available=False, real_command_logs_available=False,
            trained_model_available=False, hardware_closed_loop_verified=False)

    def audit_inputs(self):
        changed=[path for path,digest in self.data['input_sha256'].items()
            if not Path(path).is_file() or sha256(path)!=digest]
        if changed:raise ValueError('Original inputs changed: '+', '.join(changed))
        return dict(input_files=len(self.data['input_sha256']),original_inputs_unchanged=True)

    def persist(self):
        if sha256(self.root/'workspace.json') != self.loaded_hash:
            raise OSError('Workspace changed in another window; reopen before saving')
        _json(self.root/'workspace.json',self.data)
        self.loaded_hash=sha256(self.root/'workspace.json')
        effective=[self._effective(row) for row in self.rows]
        write_csv_rows(self.root/'annotations.csv',effective)
        reviewed=[row for row in effective if row['mask_reviewed']]
        write_csv_rows(self.root/'segmentation_reviewed.csv',reviewed, list(self.rows[0]))
        state_rows=[row for row in effective if row['state_reviewed']]
        write_csv_rows(self.root/'state_reviewed.csv',state_rows,list(self.rows[0]))
        write_csv_rows(self.root/'dataset_manifest.csv',[dict(video_id=clip['clip_id'],batch_id=clip['batch_id'],
            video_path=clip['path'],split='unassigned',parent_video_id=clip['video_id']) for clip in self.clips.values()])
        for parent, entry in self.data['calibrations'].items():
            config=self.map_config(parent)
            for clip in self.clips.values():
                if clip['video_id']!=parent:continue
                shifted=dict(config)
                x,y=clip['roi_xywh'][:2]
                shifted['core_corners_px']=[[a-x,b-y] for a,b in config['core_corners_px']]
                shifted['pixel_overrides']={key:[[a-x,b-y] for a,b in polygon]
                    for key,polygon in config.get('pixel_overrides',{}).items()}
                shifted['roi_xywh']=clip['roi_xywh']
                import yaml
                folder=self.root/'maps_roi';folder.mkdir(exist_ok=True)
                (folder/f'{_id(clip["clip_id"])}.yaml').write_text(yaml.safe_dump(shifted,sort_keys=False),encoding='utf-8')
        _json(self.root/'review_status.json',self.report())

    def contact_sheet(self):
        width,height=240,210;cols=5
        sheet=np.full((math.ceil(len(self.rows)/cols)*height,cols*width,3),255,np.uint8)
        for index,row in enumerate(self.rows):
            image,mask=self.images(index)
            overlay=image.copy();overlay[mask>0]=(.65*image[mask>0]+.35*np.array([70,170,225])).astype(np.uint8)
            scale=min((width-8)/image.shape[1],(height-45)/image.shape[0])
            picture=cv2.resize(overlay,(max(1,round(image.shape[1]*scale)),max(1,round(image.shape[0]*scale))),interpolation=cv2.INTER_AREA)
            left=(index%cols)*width;top=(index//cols)*height
            sheet[top+4:top+4+picture.shape[0],left+4:left+4+picture.shape[1]]=picture
            cv2.putText(sheet,f'{index+1}: {row["video_id"][-18:]} / f{row["frame_id"]}',
                (left+4,top+height-25),cv2.FONT_HERSHEY_SIMPLEX,.34,(55,45,35),1,cv2.LINE_AA)
            cv2.putText(sheet,'DRAFT / GT NOT CONFIRMED',(left+4,top+height-9),
                cv2.FONT_HERSHEY_SIMPLEX,.34,(35,80,120),1,cv2.LINE_AA)
        _write_image(self.root/'draft_masks_overview.png',sheet)

    def refresh_drafts(self):
        for row in self.rows:
            if row['mask_reviewed'] or row['working_mask_path']:continue
            path=f'masks_draft/{row["video_id"]}_{row["frame_id"]:06d}_{uuid.uuid4().hex[:8]}.png'
            _write_image(self.root/path,draft_mask(_image(self.root/row['frame_path'])))
            row['draft_mask_path']=path
        self.data['draft_generation']=dict(algorithm='ThresholdSegmenter',color_space='bgr',upper=[55,55,55],
            border_components='excluded_from_proposals',ground_truth=False)
        self.persist();self.contact_sheet()
