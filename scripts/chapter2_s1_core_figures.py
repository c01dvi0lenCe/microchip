"""Two SIMULATION n=1 mechanism figures, read only from frozen trial records."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon, Rectangle, Patch
import numpy as np
from PIL import Image

from scripts.chapter2_process_figures_revision import (
    BLUE, ORANGE, GREEN, PURPLE, INK, GRAY, QA, TRIAL,
    load_plot_source, panel_records, style,
)
from scripts.audit_chapter2_v2_stage import write_csv, write_json


EXPECTED_TIMES = [.50, .81, 1.06, 1.46, 1.92, 1.96]
SOURCE_COLOR = '#DFEBF3'
TARGET_COLOR = '#F9E8D7'


def s1_panels(replay):
    rows = panel_records(replay)
    if [round(r['time_s'], 2) for r in rows] != EXPECTED_TIMES:
        raise ValueError('Approved six persisted times are not available')
    return rows


def route_geometry(replay):
    route = list(replay.config['environment']['route'])
    if route != [190, 191, 192, 172]:
        raise ValueError('Only the approved route is in scope')
    return route, {i: replay.geometry['polygons'][str(i)] for i in route}


def phase_intervals(replay):
    route, _ = route_geometry(replay)
    applied = [e for e in replay.events if e['event'] == 'Applied'
               and e.get('action') in ('Start', 'Update')]
    if len(applied) != 3 or [e['target'] for e in applied] != route[1:]:
        raise ValueError('Cannot determine three tasks from persisted Applied events')
    return [dict(step=i + 1, source=route[i], target=route[i+1],
                 start_s=e['time_s'],
                 end_s=applied[i+1]['time_s'] if i < 2 else replay.times[-1],
                 boundary_origin='logged_simulation_Applied_not_world_activation',
                 event_csv_line=e['csv_line'])
            for i, e in enumerate(applied)]


def spatial_segments(rows, field, *, transport_only=True):
    """Preserve logged values; break at missing fields, frame gaps and task changes."""
    segments, current, previous = [], [], None
    for row in rows:
        eligible = (row.get('processing_s') is not None and row.get(field) is not None
                    and (not transport_only or row.get('phase') == 'transport'))
        continuous = (eligible and previous is not None
                      and row.get('epoch') == previous.get('epoch')
                      and row.get('step') == previous.get('step')
                      and row.get('phase') == previous.get('phase')
                      and row['frame_id'] == previous['frame_id'] + 1)
        if not eligible or not continuous:
            if current:
                segments.append(current)
            current = []
        if eligible:
            current.append(dict(time_s=row['processing_s'], value=row[field],
                                frame_id=row['frame_id'], epoch=row['epoch'],
                                step=row['step'], source_csv_line=row.get('csv_line')))
        previous = row if eligible else None
    if current:
        segments.append(current)
    return segments


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_figure(fig, output, name, excluded=()):
    sys.path.insert(0, str(QA))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(
        fig, json_out=output/(name+'.alignment.json'),
        overlay_svg=output/(name+'.alignment.svg'),
        exclude_axes=excluded, tolerance_pt=1.5, gutter_tolerance_pt=1.5, strict=True)
    fig.savefig(output/(name+'.svg'), facecolor='white')
    fig.savefig(output/(name+'.pdf'), facecolor='white')
    fig.savefig(output/(name+'.png'), dpi=600, facecolor='white')
    with Image.open(output/(name+'.png')) as im:
        im.thumbnail((1800, 1600))
        im.save(output/(name+'.preview.png'))
    plt.close(fig)


def common_heading(fig, title):
    fig.text(.055, .969, title, fontsize=11.5, fontweight='bold', va='top')
    fig.text(.95, .969, 'SIMULATION', fontsize=8.5, color=BLUE,
             fontweight='bold', ha='right', va='top')
    fig.text(.055, .928, 'normal:262000:F:end_to_end  |  n=1 机制示例',
             fontsize=6.7, color=GRAY, va='top')


def draw_route(fig, replay):
    ax = fig.add_axes([.715, .766, .235, .125], label='route_inset')
    route, polygons = route_geometry(replay)
    centers = {i: np.asarray(polygons[i], float).mean(axis=0) for i in route}
    for i in route:
        ax.add_patch(Polygon(polygons[i], fc=SOURCE_COLOR if i == 190 else TARGET_COLOR
                             if i == 191 else '#F0F3F6', ec='#A8BDCD', lw=.7))
        ax.text(*centers[i], str(i), fontsize=6.8, ha='center', va='center')
    for j, (a, b) in enumerate(zip(route, route[1:])):
        delta = centers[b] - centers[a]
        start = centers[a] + .28*delta
        end = centers[b] - .28*delta
        ax.annotate('', xy=end, xytext=start,
                    arrowprops=dict(arrowstyle='-|>', lw=1.3 if j == 0 else .7,
                                    color=BLUE if j == 0 else GRAY, mutation_scale=7))
    ax.set(xlim=(8.92, 12.08), ylim=(10.06, 7.94), xticks=[], yticks=[])
    ax.set_aspect('equal')
    ax.axis('off')
    fig.text(.705, .902, '完整路线（首段放大）', fontsize=7.0, color=GRAY)
    return ax


def local_snapshot(ax, replay, snapshot):
    for i, color in ((190, SOURCE_COLOR), (191, TARGET_COLOR)):
        polygon = np.asarray(replay.geometry['polygons'][str(i)], float)
        ax.add_patch(Polygon(polygon, fc=color, ec='#A6B9C8', lw=.75))
        ax.text(polygon[:,0].mean(), 9.10, str(i), color=GRAY,
                ha='center', va='center', fontsize=7.7)
        if i == snapshot['truth']['world_active']:
            ax.add_patch(Polygon(polygon, fc='none', ec=GREEN, lw=1.6))
    truth = snapshot['truth']
    ax.plot(truth['x'], truth['y'], 'o', color=BLUE, ms=4.8,
            markeredgecolor='white', markeredgewidth=.35, zorder=8)
    mask = snapshot['overlay_mask']
    if mask is not None:
        lo, scale = replay.geometry['lower'], replay.geometry['scale']
        ax.contour(lo[0]+np.arange(mask.shape[1])/scale,
                   lo[1]+np.arange(mask.shape[0])/scale, mask,
                   levels=[127], colors=[ORANGE], linewidths=1.1)
        frame = snapshot['frame']
        ax.plot(frame['x'], frame['y'], 'x', color=ORANGE, ms=4.8, mew=1.1)
    ax.set(xlim=(8.95,11.05), ylim=(10.02,8.98), xticks=[], yticks=[])
    ax.set_aspect('equal', adjustable='box')
    for spine in ax.spines.values():
        spine.set_visible(False)


def figure_a(replay, output):
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 6.3))
    fig.subplots_adjust(left=.055, right=.95, top=.700, bottom=.25,
                        wspace=.22, hspace=.88)
    common_heading(fig, 'S1-A  单液滴迁移的空间观测')
    fig.text(.055, .849, '局部：Step 1，源190 → 目标191', fontsize=7.7, color=INK)
    inset = draw_route(fig, replay)
    titles = ['源准备确认', '已观测运动', '跨电极迁移',
              '独立参考到达', '算法确认与Update', '下一任务模拟Applied']
    records = s1_panels(replay)
    for i, (ax, record) in enumerate(zip(axes.flat, records)):
        snapshot = replay.snapshot(record['time_s'])
        local_snapshot(ax, replay, snapshot)
        ax.set_title(f"{chr(97+i)}  {titles[i]}\n{record['time_s']:.2f} s",
                     fontsize=8.0, loc='left', pad=6,
                     color=PURPLE if i == 3 else GREEN if i == 4 else INK)
        text = f"{snapshot['state']} / {snapshot['action']}"
        if i == 3:
            text += '\n参考区间 [1.45, 1.46] s'
        if i == 5:
            text += '\n新任务191→192；旧Mask拒绝'
        ax.text(0, -.09, text, transform=ax.transAxes, fontsize=6.9,
                va='top', linespacing=1.5)
    handles = [
        Line2D([],[],marker='o',color=BLUE,ls='none',ms=4,label='模拟内部位置'),
        Line2D([],[],color=ORANGE,lw=1.1,label='已处理模拟Mask'),
        Line2D([],[],marker='x',color=ORANGE,ls='none',ms=4,label='观测质心'),
        Patch(fc=SOURCE_COLOR,ec='#A6B9C8',label='首段源电极190'),
        Patch(fc=TARGET_COLOR,ec='#A6B9C8',label='首段目标电极191'),
        Patch(fc='none',ec=GREEN,lw=1.5,label='world.active'),
    ]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.5,.095),
               ncol=3, fontsize=6.8, columnspacing=1.8, handlelength=1.7,
               labelspacing=.8)
    fig.text(.055,.052,'单位pitch；模拟观测，非真实U-Net结果；预测状态不是GT。',
             fontsize=6.2,color=GRAY)
    fig.text(.055,.027,'1.96 s新任务切换，旧Mask不复用；该tick的world.active仍为191。',
             fontsize=6.2,color=GRAY)
    export_figure(fig, output, 'S1-A_六阶段空间观测', excluded=[inset])


def plot_recorded(ax, replay, field, color, label, *, transport_only=False):
    segments = spatial_segments(replay.frames, field, transport_only=transport_only)
    for j, segment in enumerate(segments):
        ax.plot([p['time_s'] for p in segment], [p['value'] for p in segment],
                color=color, lw=.95, marker='.', ms=2.2,
                label=label if j == 0 else None)
    return segments


def figure_b(replay, output):
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.3), sharex=True)
    fig.subplots_adjust(left=.13, right=.965, top=.785, bottom=.145, hspace=.65)
    common_heading(fig, 'S1-B  同一trial的任务空间特征变化')
    phases = phase_intervals(replay)
    for field, color, label in [('x',BLUE,'内部x'),('y','#62A6C5','内部y')]:
        axes[0].step(replay.times, [r[field] for r in replay.truth],
                     where='post',color=color,lw=.9,label=label)
    for field,color,label in [('x',ORANGE,'观测x'),('y','#965B26','观测y')]:
        rows=[f for f in replay.processed if f.get(field) is not None]
        axes[0].plot([f['processing_s'] for f in rows],[f[field] for f in rows],
                     ls='none',marker='x',ms=2.6,color=color,label=label)
    axes[0].set_ylabel('位置 / pitch',fontsize=7.6)
    plot_recorded(axes[1],replay,'eta_source',BLUE,'η_source（源区残留）')
    plot_recorded(axes[1],replay,'eta_target',ORANGE,'η_target（目标覆盖）')
    axes[1].set(ylim=(-.04,1.07),yticks=[0,.5,1],ylabel='面积比例')
    axes[1].set_ylabel('面积比例',fontsize=7.6)
    plot_recorded(axes[2],replay,'distance_pitch',GREEN,'目标距离',transport_only=True)
    plot_recorded(axes[2],replay,'progress_pitch',PURPLE,'方向进展',transport_only=True)
    axes[2].set_ylabel('任务空间量 / pitch',fontsize=7.6)
    for i,ax in enumerate(axes):
        ax.set_xlim(0,4.20)
        ax.tick_params(labelsize=7)
        ax.grid(axis='x',color='#E7EDF2',lw=.45)
        ax.text(-.11,1.10,chr(97+i),transform=ax.transAxes,
                fontsize=8.3,fontweight='bold',va='bottom')
        ax.legend(loc='lower left',bbox_to_anchor=(0,1.03),
                  ncol=4 if i==0 else 2,fontsize=7,borderaxespad=0,
                  columnspacing=1.7,handlelength=2.0)
        for phase in phases:
            ax.axvline(phase['start_s'],color='#A9B7C2',lw=.65,ls='--',zorder=0)
        ax.axvspan(0,phases[0]['start_s'],color='#EFF2F4',alpha=.7,zorder=-2)
    axes[-1].set_xlabel('simulation时间 / s',fontsize=8)
    # One compact task band; boundaries use logged Applied, not physical activation.
    band=[dict(start_s=0,end_s=phases[0]['start_s'],label='源准备',color='#EFF2F4')]
    band += [dict(start_s=p['start_s'],end_s=p['end_s'],
                  label=f"Step {p['step']} · {p['source']}→{p['target']}",
                  color=['#E6EFF5','#EFF3F7','#E6EFF5'][j]) for j,p in enumerate(phases)]
    x0=axes[0].get_position().x0;width=axes[0].get_position().width
    for block in band:
        left=x0+block['start_s']/4.20*width;right=x0+block['end_s']/4.20*width
        fig.add_artist(Rectangle((left,.843),right-left,.036,transform=fig.transFigure,
                                 fc=block['color'],ec='white',lw=.5))
        fig.text((left+right)/2,.861,block['label'],fontsize=6.6,ha='center',va='center')
    fig.text(.13,.815,'任务阶段按日志模拟Applied划分；观测量按处理时刻显示。',fontsize=6.4,color=GRAY)
    fig.text(.055,.071,'单位pitch；n=1机制示例；模拟观测，非真实U-Net结果。η分母为液滴Mask面积。',
             fontsize=6.2,color=GRAY)
    fig.text(.055,.044,'目标距离/方向进展取自原日志；缺失、丢帧及任务切换断线；源准备不展示运输特征。',
             fontsize=6.2,color=GRAY)
    export_figure(fig,output,'S1-B_分阶段空间特征')


def source_points(replay):
    points=[]
    for row in replay.truth:
        for field in ('x','y'):
            points.append(dict(series='internal_'+field,time_s=row['time_s'],
                               value=row[field],unit='pitch',source='evaluation/truth_ticks.csv',
                               csv_line=row['csv_line'],frame_id=None,step=row['step'],epoch=row['epoch']))
    for field in ('x','y','eta_source','eta_target','distance_pitch','progress_pitch'):
        spatial=field in ('distance_pitch','progress_pitch')
        for segment in spatial_segments(replay.frames,field,transport_only=spatial):
            for p in segment:
                points.append(dict(series='observed_'+field,time_s=p['time_s'],
                                   value=p['value'],unit='ratio' if field.startswith('eta') else 'pitch',
                                   source='observations/frames.csv',csv_line=p['source_csv_line'],
                                   frame_id=p['frame_id'],step=p['step'],epoch=p['epoch']))
    return points


def main(trial, output):
    if output.exists():
        raise FileExistsError('New candidate output directory required')
    replay=load_plot_source(trial)
    inputs={str(p):sha(p) for p in trial.rglob('*') if p.is_file()}
    output.mkdir(parents=True)
    style()
    plt.rcParams.update({'font.family':'sans-serif',
                         'font.sans-serif':['Microsoft YaHei','Arial','DejaVu Sans'],
                         'svg.fonttype':'none','pdf.fonttype':42})
    figure_a(replay,output)
    figure_b(replay,output)
    data=output/'source_data';data.mkdir()
    shutil.copytree(trial,data/'original_trial')
    write_csv(data/'S1_A_panel_sources.csv',s1_panels(replay))
    write_csv(data/'task_stages.csv',phase_intervals(replay))
    write_csv(data/'S1_B_plot_points.csv',source_points(replay))
    shutil.copy2(__file__,data/Path(__file__).name)
    write_json(output/'figure_manifest.json',dict(
        simulation=True,trial_id=replay.trial_id,source_trial=str(trial),coordinate_unit='pitch',
        n=1,purpose='mechanism_example_not_performance_statistics',new_simulation_runs=0,
        new_algorithm_runs=0,source_hashes=inputs,plot_source_sha256=sha(__file__),
        figures=['S1-A_六阶段空间观测','S1-B_分阶段空间特征'],
        absent_states_actions=['Stationary','Deviation','Retry','Recovery'],
        phase_boundaries='logged_simulation_Applied_not_world_active',
        optional_features={key:sum(len(s) for s in spatial_segments(replay.frames,key))
                           for key in ('distance_pitch','progress_pitch')},
        alignment_exclusions={'S1-A':['route_inset: explanatory schematic not comparable to six equal crop panels']},
        source_changes=[p for p,h in inputs.items() if sha(p)!=h]))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    main(args.trial,args.output)
