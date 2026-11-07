"""Only finalize the clean overview/player from the existing one-trial logs."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.render import load_trial,_style,_electrodes,_save,write_player
import matplotlib.pyplot as plt

OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-28_实验一_真实几何4mm到达识别_v1')
data=load_trial(OUT/'trial');_style()
fig,ax=plt.subplots(figsize=(8,8));fig.subplots_adjust(left=.1,right=.97,bottom=.09,top=.94)
_electrodes(ax,data,full=True);fig.suptitle('SIMULATION',fontsize=11)
_save(fig,OUT/'visualization_clean_v2/figures_final/map_full_clean');plt.close(fig)
write_player(data,OUT/'visualization_clean_v2/开始回放.html','figures_final','map_full_clean.pdf')
files=[OUT/'visualization_clean_v2/开始回放.html']
for name in ('map_full_clean','static_geometry','movement_keyframes','feature_timeline','arrival_timeline'):
    files.extend(OUT/'visualization_clean_v2/figures_final'/(name+ext) for ext in ('.svg','.pdf','.png'))
manifest=dict(new_simulation_runs=0,trial_id=data['manifest']['trial_id'],
              renderer_sha256=hashlib.sha256((ROOT/'dmf/chapter2_geometry_sim/render.py').read_bytes()).hexdigest(),
              final_files={p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              movie='visualization_clean_v2/single_step.mp4',
              superseded_visual_only=['visualization','visualization_clean_v2/figures','visualization_clean_v2/figures_final/map_full.pdf'],
              revision='Overview keeps corner/peripheral IDs;190/191 are labeled in local panels, not crowded in overview. No data exclusion.')
(OUT/'final_figure_index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
