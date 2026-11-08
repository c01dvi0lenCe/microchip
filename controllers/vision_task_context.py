"""Read-only command context for sensing. No transaction or arrival decisions."""
import hashlib
import json
from pathlib import Path

from dmf.vision.task_regions import TaskBinding,TaskRegion


def regions_from_open_loop(plan,sequence,binding,packet,*,epoch,margin_px=64):
    if plan is None:return ()
    if sequence is not None and sequence.plan is plan:
        index=sequence.index if sequence.pending is not None else max(0,sequence.index-1)
    else:index=1
    result=[]
    for group,route in plan.routes.items():
        target_index=min(index,len(route)-1)
        source_index=max(0,target_index-1) if index<len(route) else target_index
        identity='task_'+hashlib.sha256(group.encode('utf8')).hexdigest()[:12]
        result.append(binding.region(identity,route[source_index],route[target_index],epoch=epoch,
            frame_shape=packet.image_bgr.shape,acquisition_id=packet.video_id,margin_px=margin_px))
    return tuple(result)


def load_observation_setup(path,packet):
    path=Path(path);config=json.loads(path.read_text(encoding='utf8'))
    if config.get('schema')!='dmf_priority_regions_v1':raise ValueError('unsupported observation setup')
    regions=[]
    for entry in config.get('pixel_regions',[]):
        if set(entry)-{'region_id','roi','epoch'}:raise ValueError('pixel region cannot claim electrode or droplet identity')
        region=TaskRegion(entry['region_id'],tuple(entry['roi']),entry.get('epoch',0))
        region.validate_packet(packet);regions.append(region)
    if len(regions)>8 or len({r.region_id for r in regions})!=len(regions):raise ValueError('invalid pixel region count/IDs')
    binding=None
    if config.get('calibration') is not None:
        values=config['calibration']
        def file(name):
            candidate=Path(values[name]);return candidate if candidate.is_absolute() else path.parent/candidate
        binding=TaskBinding.load(file('design_map'),file('manifest'),file('reference_image'),values['current_conditions'])
        if binding.acquisition_id!=packet.video_id or binding.image_size!=(packet.image_bgr.shape[1],packet.image_bgr.shape[0]):
            raise ValueError('current acquisition/full image is not bound to this calibration')
    follow=config.get('follow_open_loop',binding is not None)
    margin=config.get('margin_px',64)
    if type(follow) is not bool or type(margin) is not int or margin<0:raise ValueError('invalid observation setup parameters')
    if follow and binding is None:raise ValueError('automatic task regions require accepted current calibration')
    return dict(regions=tuple(regions),binding=binding,follow_open_loop=follow,margin_px=margin)
