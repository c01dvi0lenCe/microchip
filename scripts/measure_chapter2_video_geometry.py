"""Rough video-frame size estimation from reviewed masks and grid periodicity.

The design pitch is a nominal ruler, not an independently validated metric
calibration. No photograph homography, recognition GT or simulated mask is used.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
SKILL=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
if str(SKILL) not in sys.path:
    sys.path.insert(0,str(SKILL))
from audit_panel_alignment import require_matplotlib_panel_alignment

CHAPTER=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
SNAPSHOT=CHAPTER/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot'
REGISTRATION=CHAPTER/'图像—电极配准/2026-10-22_工业相机视频帧_点位核对_v1'
DEFAULT_OUT=CHAPTER/'真实分割研究/2026-10-28_视频液滴尺寸粗估_v1'
GRID_PATCHES={
    'camera_20261013_152806_975638':[(1650,850,1000,650),(1750,950,1000,650),(1850,1050,1000,650)],
    'camera_20261013_154518_384889':[(1350,1000,1000,650),(1450,1100,1000,650),(1550,1200,1000,650)],
    'camera_20261014_112318_257662':[(1900,1300,1000,650),(2000,1500,1000,650),(2100,1700,1000,650)],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_image(path,mode=cv2.IMREAD_COLOR):
    a=cv2.imdecode(np.fromfile(path,np.uint8),mode)
    if a is None:
        raise ValueError(f'unreadable image: {path}')
    return a


def grid_period(gray):
    """High-pass axis profiles, autocorrelation peaks in broad80–160px band.

    The search band reflects the visible grid scale; peaks and all patch choices
    are retained. Scores describe periodicity, not calibration confidence.
    """
    a=np.asarray(gray,dtype=float)
    if a.ndim!=2 or min(a.shape)<325 or not np.isfinite(a).all():
        raise ValueError('finite 2D grid patch at least325px required')
    high=a-cv2.GaussianBlur(a,(0,0),10)
    out=[]
    for axis in (0,1):
        v=high.mean(axis=axis); v-=v.mean()
        ac=np.correlate(v,v,'full')[len(v)-1:]
        if ac[0]<=1e-10:
            raise ValueError('no grid periodicity')
        peaks=[k for k in range(80,161) if ac[k]>=ac[k-1] and ac[k]>ac[k+1]]
        if not peaks:
            raise ValueError('no grid peak')
        k=max(peaks,key=lambda n:ac[n])
        out.append(dict(period_px=k,autocorrelation_score=float(ac[k]/ac[0]),
                        candidates=[dict(period_px=n,score=float(ac[n]/ac[0])) for n in peaks]))
    return tuple(out)


def mask_dimensions(mask,pitch_x_px,pitch_y_px,pitch_mm):
    binary=np.asarray(mask)>0
    ys,xs=np.nonzero(binary)
    if len(xs)==0 or min(pitch_x_px,pitch_y_px,pitch_mm)<=0:
        raise ValueError('nonempty mask and positive pitch required')
    sx,sy=pitch_mm/pitch_x_px,pitch_mm/pitch_y_px
    area=len(xs)*sx*sy
    points=np.c_[xs*sx,ys*sy].astype(np.float32)
    (_, _),(w,h),_=cv2.minAreaRect(points)
    major,minor=sorted((float(w+min(sx,sy)),float(h+min(sx,sy))),reverse=True)
    return dict(area_px=int(len(xs)),equivalent_diameter_px=math.sqrt(4*len(xs)/math.pi),
                area_mm2=area,equivalent_diameter_mm=math.sqrt(4*area/math.pi),
                bbox_width_mm=(int(xs.max())-int(xs.min())+1)*sx,
                bbox_height_mm=(int(ys.max())-int(ys.min())+1)*sy,
                major_extent_mm=major,minor_extent_mm=minor,
                aspect_ratio=major/minor,
                compact_descriptive=major/minor<=1.3)


def _figure(rows,output):
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
                         'font.size':12,'svg.fonttype':'none','pdf.fonttype':42})
    fig,axes=plt.subplots(2,3,figsize=(12.6,7.6))
    fig.subplots_adjust(left=.03,right=.985,bottom=.09,top=.92,wspace=.12,hspace=.42)
    indices=(0,3,7,1,4,16)
    for ax,index in zip(axes.flat,indices):
        r=rows[index]; image=read_image(SNAPSHOT/r['frame_path']); mask=read_image(SNAPSHOT/r['mask_path'],0)
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        canvas=np.full((430,650,3),255,np.uint8)
        h,w=mask.shape; ox=(650-w)//2; oy=(400-h)//2
        canvas[oy:oy+h,ox:ox+w]=rgb
        ax.imshow(canvas)
        contours,_=cv2.findContours((mask>0).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            q=contour[:,0,:]
            ax.plot(q[:,0]+ox,q[:,1]+oy,color='#39dcdf',lw=1.2)
        bar=r['pitch_x_px']
        ax.plot([25,25+bar],[407,407],color='#173a53',lw=3)
        ax.text(25+bar/2,440,'3.2 mm (approx.)',ha='center',va='top',color='#173a53',fontsize=10)
        ax.set(xlim=(0,650),ylim=(480,0))
        ax.set_title(f'Video {r["video_number"]} | frame {r["source_frame_id"]}',fontsize=12,pad=8)
        ax.text(.5,-.08,f'Equivalent D ≈ {r["equivalent_diameter_mm"]:.1f} mm',transform=ax.transAxes,ha='center',fontsize=13)
        ax.set_axis_off()
    fig.suptitle('REAL VIDEO | rough size estimate, not a validated calibration',fontsize=14)
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(output/'video_size_preview.alignment.json'),strict=True,tolerance_pt=1.5)
    fig.savefig(output/'video_size_preview.svg')
    fig.savefig(output/'video_size_preview.pdf')
    fig.savefig(output/'video_size_preview.png',dpi=600)
    plt.close(fig)


def measure(output=DEFAULT_OUT):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    samples=list(csv.DictReader((SNAPSHOT/'samples.csv').open(encoding='utf-8-sig')))
    pitch_records=[]; scales={}; video_evidence=[]
    for number,(video,patches) in enumerate(GRID_PATCHES.items(),1):
        workspace=json.loads((REGISTRATION/video/'workspace.json').read_text(encoding='utf-8'))
        source=workspace['source']; cap=cv2.VideoCapture(source['source_video'])
        cap.set(cv2.CAP_PROP_POS_FRAMES,source['source_frame_id'])
        ok,frame=cap.read(); cap.release()
        if not ok:
            raise ValueError('video frame decode failed')
        reference=read_image(REGISTRATION/video/'original.png')
        if not np.array_equal(frame,reference):
            raise ValueError('decoded video differs from reference frame')
        px=[];py=[]
        for j,(x,y,w,h) in enumerate(patches):
            gray=cv2.cvtColor(frame[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY)
            xx,yy=grid_period(gray); px.append(xx['period_px']);py.append(yy['period_px'])
            pitch_records.append(dict(video_id=video,patch_index=j,roi_xywh=[x,y,w,h],x=xx,y=yy))
        scales[video]=(number,float(np.median(px)),float(np.median(py)))
        video_evidence.append(dict(video_id=video,source_video=source['source_video'],
            source_frame_id=source['source_frame_id'],reference_image_sha256=sha(REGISTRATION/video/'original.png'),
            reference_pixel_identical_to_current_video_decode=True,
            pitch_x_px=float(np.median(px)),pitch_y_px=float(np.median(py)),
            patch_x_range_px=[min(px),max(px)],patch_y_range_px=[min(py),max(py)],
            source_video_sha256_from_existing_inventory=source['source_video_sha256'],
            original_file_rehashed_this_run=False))
    rows=[]
    for s in samples:
        if s['mask_reviewed']!='True':
            raise ValueError('unreviewed mask')
        for path_col,hash_col in (('frame_path','frame_path_sha256'),('mask_path','mask_path_sha256')):
            if sha(SNAPSHOT/s[path_col])!=s[hash_col]:
                raise ValueError('snapshot hash mismatch')
        number,px,py=scales[s['parent_video_id']]
        mask=read_image(SNAPSHOT/s['mask_path'],0)
        r=dict(video_number=number,video_id=s['parent_video_id'],source_frame_id=int(s['source_frame_id']),
               frame_path=s['frame_path'],mask_path=s['mask_path'],frame_sha256=s['frame_path_sha256'],
               mask_sha256=s['mask_path_sha256'],pitch_x_px=px,pitch_y_px=py,design_pitch_mm=3.2,
               measurement_status='rough_grid_period_estimate_not_validated_registration',
               **mask_dimensions(mask,px,py,3.2))
        rows.append(r)
    with (output/'per_mask_size_estimates.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (output/'grid_period_evidence.json').write_text(json.dumps(pitch_records,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=[]
    for video in scales:
        r=[x for x in rows if x['video_id']==video]
        summary.append(dict(video_id=video,reviewed_masks=len(r),
            equivalent_diameter_range_mm=[min(x['equivalent_diameter_mm'] for x in r),max(x['equivalent_diameter_mm'] for x in r)],
            equivalent_diameter_median_mm=float(np.median([x['equivalent_diameter_mm'] for x in r])),
            major_extent_range_mm=[min(x['major_extent_mm'] for x in r),max(x['major_extent_mm'] for x in r)],
            minor_extent_range_mm=[min(x['minor_extent_mm'] for x in r),max(x['minor_extent_mm'] for x in r)]))
    manifest=dict(schema='rough_video_droplet_geometry_v1',simulation=False,independent_acquisition_groups=1,
        reviewed_masks=18,representative_videos=3,nominal_design_pitch_mm=3.2,
        homography_used=False,photo_H_used=False,video_gt_or_state_labels_created=False,
        method='High-pass grayscale axis-profile autocorrelation; median3 nearby grid patches per video; reviewed binary Mask pixel counts.',
        search_lag_px=[80,160],video_evidence=video_evidence,summary=summary,
        limits=['Grid patches are not independently surveyed reference points.',
                'Patch variation is not a95% confidence interval and does not cover systematic perspective/distortion error.',
                'One frame per video sets the approximate scale for its6 reviewed masks; stable camera geometry over each clip is assumed.',
                'Video3 grid is above the droplet: extrapolation to the bottom of the array is approximate.',
                'Masks are18 non-independent selected frames, not18 independent droplets or trials.',
                'Compact is a descriptive aspect-ratio flag, not a Stationary/Arrived GT label.',
                'If pitch is3.3mm rather than design3.2mm all linear estimates increase by3.125%.'])
    (output/'measurement_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    _figure(rows,output)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=DEFAULT_OUT)
    measure(parser.parse_args().output)
