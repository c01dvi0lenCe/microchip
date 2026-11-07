"""Three paper figures from audited formal CSV only; never simulate or rescore."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.font_manager import fontManager

SKILL=Path.home()/'.agents/skills/nature-figure/scripts'
sys.path.insert(0,str(SKILL))
from audit_panel_alignment import require_matplotlib_panel_alignment

CONDITIONS=['N','V','P','T','J','O','C','R','F','D','L','TF']
ALL_METHODS=['M1','GQ','M2','M2_S','M2_K','M3']
MAIN=['M1','M2','M3']
WIDTH_MM=183
LABELS=dict(N='正常',V='慢速',P='暂停',T='卡滞',J='抖动',O='偏移',C='缺失',R='破碎',F='伪目标',D='丢帧',L='延迟',TF='卡滞伪目标')
COLORS=dict(M1='#77818a',M2='#315f87',M3='#bc8255')
MARKERS=dict(M1='o',M2='s',M3='^')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))


def display_groups():
    return [dict(condition=c,stratum=s,n=20 if s=='base' else 10,
        label=LABELS[c]+('' if s=='base' else '·低' if s=='low' else '·高'))
        for c in CONDITIONS for s in (['base'] if c in ('N','V','P','T') else ['low','high'])]


def validate_primary(rows):
    keys=[]
    for row in rows:
        seed=int(row['seed']);c=row['condition']
        expected='base' if c in ('N','V','P','T') else 'low' if seed<266010 else 'high'
        if row['stratum']!=expected:raise ValueError('Incorrect formal stratum')
        keys.append((seed,c,row['method'],row['reference_id']))
    expected={(s,c,m,'R0') for s in range(266000,266020) for c in CONDITIONS for m in ALL_METHODS}
    if len(keys)!=1440 or len(set(keys))!=1440 or set(keys)!=expected:
        raise ValueError('Incomplete or duplicated formal primary plan')


def interval(row):
    if row.get('ci_lower','') not in ('',None) and row.get('ci_upper','') not in ('',None):
        return float(row['ci_lower']),float(row['ci_upper']),False
    return float(row['ident_lower']),float(row['ident_upper']),True


def joint_times(row):
    values=json.loads(row['raw_differences_json'])
    if len(values)!=int(row['n_joint']) or any(not np.isfinite(float(v)) for v in values):
        raise ValueError('Joint-supported sample count/timing mismatch')
    return [float(v) for v in values]


def one(rows,**key):
    found=[r for r in rows if all(str(r[k])==str(v) for k,v in key.items())]
    if len(found)!=1:raise ValueError('Expected one statistical row: '+str(key))
    return found[0]


def setup():
    for path in ['C:/Windows/Fonts/simsun.ttc','C:/Windows/Fonts/times.ttf']:
        if Path(path).is_file():fontManager.addfont(path)
    plt.rcParams.update({'font.family':['Times New Roman','SimSun','Arial'],'font.size':8.5,
        'axes.labelsize':9,'axes.titlesize':9,'xtick.labelsize':8.5,'ytick.labelsize':8.5,
        'pdf.fonttype':42,'svg.fonttype':'none','axes.unicode_minus':False,
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.65,
        'legend.frameon':False,'legend.fontsize':8.5,'figure.facecolor':'white','axes.facecolor':'white'})


def panel(ax,label,title):
    ax.set_title(title,pad=8)
    ax.annotate(label,xy=(0,1),xycoords='axes fraction',xytext=(-28,8),textcoords='offset points',
        fontsize=10,fontweight='bold',annotation_clip=False)


def method_legend(fig,methods=MAIN,y=.98):
    fig.text(.018,.986,'SIMULATION',fontsize=9,ha='left',va='top')
    fig.legend(handles=[Line2D([],[],color=COLORS[m],marker=MARKERS[m],ls='none',label=m,
        markerfacecolor='white',markersize=4) for m in methods],ncol=len(methods),
        loc='upper right',bbox_to_anchor=(.985,y),columnspacing=1.2,handletextpad=.35)


def point(ax,value,lo,hi,y,color,marker,unknown=False):
    ax.plot([100*lo,100*hi],[y,y],color=color,lw=.7,ls='--' if unknown else '-',zorder=2)
    ax.plot([100*lo,100*lo],[y-.045,y+.045],color=color,lw=.7)
    ax.plot([100*hi,100*hi],[y-.045,y+.045],color=color,lw=.7)
    ax.plot(100*value,y,marker=marker,color=color,ls='none',ms=3.3,mfc='white',mew=.8,zorder=3)


def save(fig,path,exclude_axes=None):
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(path)+'.alignment.json',
        overlay_svg=str(path)+'.alignment.svg',strict=True,tolerance_pt=1.5,gutter_tolerance_pt=1.5,
        exclude_axes=exclude_axes or [])
    fig.savefig(str(path)+'.svg')
    fig.savefig(str(path)+'.pdf')
    fig.savefig(str(path)+'.png',dpi=600)
    plt.close(fig)


def forest(ax,rates,groups,endpoint,methods=MAIN,reference='R0'):
    for j,m in enumerate(methods):
        for i,g in enumerate(groups):
            r=one(rates,reference_id=reference,condition=g['condition'],stratum=g['stratum'],method=m,endpoint=endpoint)
            if int(r['n_planned'])!=g['n']:raise ValueError('Figure denominator mismatch')
            lo,hi,unknown=interval(r)
            point(ax,float(r['estimate']),lo,hi,i+(j-(len(methods)-1)/2)*.22,COLORS[m],MARKERS[m],unknown)
    ax.set(ylim=(len(groups)-.5,-.5),xlim=(-4,104),xticks=[0,50,100],xlabel='比例 / %')
    ax.set_yticks(range(len(groups)),[g['label'] for g in groups]);ax.grid(axis='x',color='#e4e7e9',lw=.5)


def family_groups():
    return [dict(condition=c,stratum='base' if c in ('N','V','P','T') else 'mixture',n=20,label=LABELS[c]) for c in CONDITIONS]


def contrast_forest(ax,paired,groups,endpoint,contrasts,colors,markers):
    for j,contrast in enumerate(contrasts):
        for i,g in enumerate(groups):
            r=one(paired,reference_id='R0',condition=g['condition'],stratum=g['stratum'],contrast=contrast,endpoint=endpoint)
            if int(r['n_planned'])!=20:raise ValueError('Contrast must preserve20 planned pairs')
            lo,hi,unknown=interval(r)
            point(ax,float(r['estimate']),lo,hi,i+(j-(len(contrasts)-1)/2)*.22,colors[j],markers[j],unknown)
    ax.set(ylim=(len(groups)-.5,-.5),xlim=(-104,104),xticks=[-100,0,100],xlabel='配对比例差 / 百分点')
    ax.set_yticks(range(len(groups)),[g['label'] for g in groups])
    ax.axvline(0,color='#bdc4ca',ls=':',lw=.7,zorder=1)


def figure_one(rates,out):
    groups=display_groups();fig,axes=plt.subplots(1,3,sharey=True,figsize=(WIDTH_MM/25.4,165/25.4))
    fig.subplots_adjust(left=.145,right=.985,bottom=.09,top=.90,wspace=.19)
    for ax,key,title,label in zip(axes,
        ['before_reference_per_planned','no_reference_confirmation_per_planned','reference_supported_per_planned'],
        ['参考前确认','无参考确认','参考支持确认'],'abc'):
        forest(ax,rates,groups,key);panel(ax,label,title)
    axes[1].tick_params(labelleft=False);axes[2].tick_params(labelleft=False)
    method_legend(fig);save(fig,out/'Exp1B_formal_1_reference_categories')


def figure_two(primary,rates,paired,paired_times,out):
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,175/25.4))
    fig.subplots_adjust(left=.12,right=.985,bottom=.09,top=.90,wspace=.40,hspace=.53)
    a,b,c,d=axes.flat
    for j,m in enumerate(MAIN):
        for i,cid in enumerate(['N','V','P']):
            values=[float(r['signed_deviation_s']) for r in primary if r['method']==m and r['condition']==cid and r.get('signed_deviation_s','')!='']
            x=i+(j-1)*.22
            if values:
                a.scatter(x+np.linspace(-.045,.045,len(values)),values,s=7,color=COLORS[m],marker=MARKERS[m],alpha=.65,linewidths=.45)
                a.plot([x-.065,x+.065],[np.median(values)]*2,color=COLORS[m],lw=1.2)
    a.axhline(0,color='#bdc4ca',ls=':',lw=.7);a.set(xticks=[0,1,2],xticklabels=['正常','慢速','暂停'],ylabel='确认时刻 - 参考时刻 / s')
    panel(a,'a','相对参考的时间偏差')
    contrasts=['M2_minus_M1','M3_minus_M2'];colors=[COLORS['M2'],COLORS['M3']];markers=['s','^']
    differences=[]
    for j,contrast in enumerate(contrasts):
        for i,cid in enumerate(['N','V','P']):
            r=one(paired_times,reference_id='R0',condition=cid,stratum='base',contrast=contrast)
            x=i+(j-.5)*.24;values=joint_times(r)
            if not values:
                b.text(x,.12,'NA',ha='center',va='center',fontsize=8,rotation=90,rotation_mode='anchor');continue
            differences.extend(values)
            b.scatter(x+np.linspace(-.035,.035,len(values)),values,s=7,color=colors[j],marker=markers[j],alpha=.5,linewidths=.45)
            if r.get('ci_lower','')!='':
                b.plot([x,x],[float(r['ci_lower']),float(r['ci_upper'])],color=colors[j],lw=1)
            b.plot(x,float(r['median_difference_s']),marker=markers[j],color=colors[j],ms=4,mfc='white')
    lower=min(differences+[-.04])-.025;upper=max(differences+[.16])+.025
    b.axhline(0,color='#bdc4ca',ls=':',lw=.7)
    b.set(xticks=[0,1,2],xticklabels=['正常','慢速','暂停'],xlim=(-.4,2.4),ylim=(lower,upper),ylabel='配对确认时差 / s')
    panel(b,'b','共同支持子集的时间代价')
    contrast_forest(c,paired,family_groups(),'before_reference_per_planned',contrasts,colors,markers)
    contrast_forest(d,paired,family_groups(),'reference_supported_per_planned',contrasts,colors,markers)
    panel(c,'c','参考前确认的配对变化');panel(d,'d','参考支持产出的配对变化')
    method_legend(fig)
    fig.legend(handles=[Line2D([],[],color=co,marker=ma,mfc='white',ls='-',lw=.7,label=label)
        for co,ma,label in zip(colors,markers,['M2 - M1','M3 - M2'])],ncol=2,loc='lower center',bbox_to_anchor=(.55,.005))
    save(fig,out/'Exp1B_formal_2_reliability_and_time')


def figure_three(rates,paired,out):
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,180/25.4),gridspec_kw={'height_ratios':[1.3,1.]})
    fig.subplots_adjust(left=.13,right=.985,bottom=.13,top=.82,wspace=.45,hspace=.52)
    a,b,c,d=axes.flat
    qcolors=['#77818a','#315f87'];scolors=['#77818a','#668e93','#bc8255']
    contrast_forest(a,paired,family_groups(),'reference_supported_per_planned',
        ['GQ_minus_M1','M2_minus_GQ'],qcolors,['o','s'])
    contrast_forest(b,paired,family_groups(),'reference_supported_per_planned',
        ['M2_S_minus_M2','M2_K_minus_M2','M3_minus_M2'],scolors,['o','s','^'])
    panel(a,'a','Q/W：参考支持增量');panel(b,'b','S/K：参考支持增量')
    selection=[('N','base'),('V','base'),('C','high'),('F','high'),('D','high'),('TF','high')]
    refs=['R0','R_dist_low','R_dist_high','R_speed_low','R_speed_high','R_dwell_low','R_dwell_high']
    m2=np.array([[float(one(rates,reference_id=rid,condition=cid,stratum=st,method='M2',endpoint='reference_supported_per_planned')['estimate'])*100 for rid in refs] for cid,st in selection])
    delta=np.array([[float(one(rates,reference_id=rid,condition=cid,stratum=st,method='M3',endpoint='reference_supported_per_planned')['estimate'])*100 for rid in refs] for cid,st in selection])-m2
    colorbars=[]
    for ax,values,cmap,limits,title,label in [(c,m2,'Blues',(0,100),'M2：参考敏感性','c'),(d,delta,'RdBu_r',(-100,100),'M3 - M2：参考敏感性','d')]:
        im=ax.imshow(values,cmap=cmap,vmin=limits[0],vmax=limits[1],aspect='auto',interpolation='nearest')
        ax.set(xticks=range(7),xticklabels=['R0','d-','d+','v-','v+','t-','t+'],
            yticks=range(6),yticklabels=[LABELS[cid]+('·高' if st=='high' else '') for cid,st in selection])
        for i in range(6):
            for j in range(7):
                v=values[i,j];text=f'{v:.0f}'
                ax.text(j,i,text,ha='center',va='center',fontsize=8,color='white' if (limits[0]==0 and v>60) else '#172e40')
        ax.tick_params(length=0);panel(ax,label,title)
        bar=fig.colorbar(im,ax=ax,orientation='horizontal',fraction=.06,pad=.23,ticks=[limits[0],0 if limits[0]<0 else 50,limits[1]])
        bar.set_label('比例 / %' if limits[0]==0 else '配对比例差 / 百分点',fontsize=8.5)
        colorbars.append(bar.ax)
    fig.text(.018,.986,'SIMULATION',fontsize=9,ha='left',va='top')
    for xs,colors,markers,labels in [(.29,qcolors,['o','s'],['GQ - M1','M2 - GQ']),
        (.79,scolors,['o','s','^'],['M2+S - M2','M2+K - M2','M3 - M2'])]:
        fig.legend(handles=[Line2D([],[],color=co,marker=ma,mfc='white',ls='-',lw=.7,label=label)
            for co,ma,label in zip(colors,markers,labels)],loc='upper center',bbox_to_anchor=(xs,.96),
            ncol=1,handlelength=1.4,labelspacing=.2)
    save(fig,out/'Exp1B_formal_3_ablation_and_reference',exclude_axes=colorbars)


def plot(data,output):
    data,output=Path(data).resolve(),Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    if not load(data/'independent_audit.json')['passed']:raise ValueError('Formal saved-data audit must pass first')
    primary=read(data/'planned_method_results.csv');validate_primary(primary)
    rates=read(data/'statistics_rates.csv');paired=read(data/'paired_binary.csv');paired_times=read(data/'paired_latency.csv')
    output.mkdir(parents=True);setup()
    figure_one(rates,output);figure_two(primary,rates,paired,paired_times,output);figure_three(rates,paired,output)
    joint=[]
    for cid in ['N','V','P']:
        joint.append(LABELS[cid]+': '+', '.join(contrast.replace('_minus_','-')+' n_joint='+one(paired_times,
            reference_id='R0',condition=cid,stratum='base',contrast=contrast)['n_joint'] for contrast in ['M2_minus_M1','M3_minus_M2']))
    captions=[
        '图1 不同条件下的参考相对确认类别。SIMULATION；三方法读取同一Mask缓存。4个base各n=20，8个压力条件低/高各n=10；点为计划分母上的比例，线为双侧CP95%区间，0%和100%仍保留完整区间。若有未知则以识别范围替代CI，完整未知/未执行数在源表。参考前只表示早于所设模拟参考，不是实物危险切换。',
        '图2 可靠性与确认时间代价。SIMULATION；(a)正常、慢速、暂停每条件20个配对seed，显示全部已定义带符号时差及中位线，横向固定错位仅避重叠；(b)同seed双方都参考支持的配对确认时差、原值、中位数及条件bootstrap95%区间，至少5对才计算区间；NA不是零延迟。'+
        '；'.join(joint)+'。(c)(d)M2-M1、M3-M2的逐家族配对比例差。base n=20；压力为两层各n=10的等权差，CP不一致格Bonferroni界组合；不是低/高间的配对。没有跨工况合池或整体显著性主张。',
        '图3 模块消融与独立参考敏感性。SIMULATION；(a)(b)逐家族参考支持比例配对差及保守95%界，base20对、压力低/高各10对等权组合；(c)M2的7参考支持比例描述矩阵；(d)相同输入M3-M2支持比例差。矩阵N/V各n=20，C/F/D/TF高强度各n=10；六行在正式运行前固定。d/v为距离/速度阈值±20%，t为驻留0.10/0.20s，R0=0.288mm、0.192mm/s、0.15s。矩阵不逐格叠加CI，完整区间及全部12条件6方法见CSV；7参考重评分不增加独立重复。'
    ]
    (output/'图注草稿.md').write_text('\n\n'.join(captions),encoding='utf-8')
    sources=['planned_method_results.csv','reference_sensitivity_results.csv','statistics_rates.csv','paired_binary.csv',
             'latency_summary.csv','paired_latency.csv','independent_audit.json','manifest.json']
    source={str(data/name):sha(data/name) for name in sources}
    (output/'figure_manifest.json').write_text(json.dumps(dict(plot_source=str(Path(__file__).resolve()),
        plot_source_sha256=sha(__file__),source_files=source,new_simulation_runs=0,
        display_omissions='No planned outcome discarded; no-event delays remain NA, full counts/CI in source CSV.',
        heatmap_selection_predeclared=['N/base','V/base','C/high','F/high','D/high','TF/high'],
        heatmap_uncertainty='Descriptive sensitivity matrix; complete intervals supplied in statistics_rates.csv, not independent repeats.',
        files={p.name:sha(p) for p in output.iterdir() if p.is_file()}),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(output),figure_count=3,new_simulation_runs=0),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('data');parser.add_argument('output')
    args=parser.parse_args();plot(args.data,args.output)
