"""Style-only thesis candidates from saved SIMULATION evidence; no dmf imports."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import chapter2_paper_figure_closeout as p

PREVIOUS=p.OUT
OUT=p.BASE/'2026-10-27_仿真论文图_学术整理候选_v2'
WIDTH_MM=160
COLORS=('#687681','#B77C4B','#5C8FA6','#173F60')
XCOLOR='#204E70';YCOLOR='#806B92';OX='#C1874D';OY='#719080'
STATE_MARKERS=('x','s','o','v','D','^')
ACTIONS={
    'Prepare':('#89959E','v','准备'), 'Start':('#648C9F','>','启动'),
    'Update':('#173F60','v','Update'), 'Retry':('#B07C4B','^','Retry'),
    'Recovery':('#A86059','<','Recovery'), 'resend':('#806B92','>','resend'),
    'Complete':('#398B75','D','完成'), 'Stop':('#263A48','x','停止')}
PLOT_ROWS=[]
DRAWN_SERIES=[]
DRAWN_STATES=[]
DRAWN_EVENTS=[]

def action_kind(row):
    applied=row.get('event')=='Applied'
    action=row.get('action') if applied else row.get('event')
    phase=row.get('origin_phase') if applied else row.get('phase')
    if action=='Retry' and phase=='recovering':return 'resend'
    return action if action in ACTIONS else None

def wilson_check(k,n):
    z=1.959963984540054;f=k/n;den=1+z*z/n
    mid=(f+z*z/(2*n))/den;half=z*math.sqrt(f*(1-f)/n+z*z/(4*n*n))/den
    return max(0.,mid-half),min(1.,mid+half)

def group_description(values):
    a=[float(v) for v in values]
    return dict(n=len(a),mean=sum(a)/len(a),minimum=min(a),maximum=max(a),unique=len(set(a)))

def expected_cost(row):return float(row['execution_time_s']) if row['path_complete']=='True' else 24.
def state_points(rows,state):return [float(r['processing_s']) for r in rows if r.get('processing_s') and r['state']==state]
def method_x_positions(category):return [category+(i-1.5)*.20 for i in range(4)]

def record_series(trial,kind,field,x,y):
    DRAWN_SERIES.append(dict(trial_id=trial,kind=kind,field=field,
        points=[[float(a) if np.isfinite(a) else None,float(b) if np.isfinite(b) else None] for a,b in zip(x,y)]))

def write_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def style():
    p.style()
    import matplotlib as mpl
    from matplotlib import font_manager
    for filename in ('simsun.ttc','times.ttf','timesbd.ttf','timesi.ttf'):
        font_manager.fontManager.addfont('C:/Windows/Fonts/'+filename)
    mpl.rcParams.update({'font.family':['Times New Roman','SimSun'],'font.size':9,
        'font.weight':'normal','axes.titleweight':'normal','axes.labelsize':9,
        'figure.facecolor':'white','axes.facecolor':'white','lines.linewidth':.9,
        'svg.fonttype':'none','pdf.fonttype':42})

def save(fig,name):
    import matplotlib.pyplot as plt
    skill=Path.home()/'.agents/skills/nature-figure/scripts'
    if str(skill) not in sys.path:sys.path.insert(0,str(skill))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=OUT/'QA'/f'{name}.alignment.json',
        overlay_svg=OUT/'QA'/f'{name}.alignment.svg',tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(OUT/'figures'/f'{name}.svg')
    fig.savefig(OUT/'figures'/f'{name}.pdf')
    fig.savefig(OUT/'figures'/f'{name}.png',dpi=600)
    fig.savefig(OUT/'previews'/f'{name}.png',dpi=300)
    plt.close(fig)

def tag(fig):fig.text(.98,.99,'SIMULATION',ha='right',va='top',fontsize=8.5,color='#526879')
def draw_refs(ax,rows):p.references(ax,rows)
def limits(data):return (-.15,max(float(d['metric']['execution_time_s']) for d in data)+.20)

def motion(data):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig,axes=plt.subplots(4,2,figsize=(WIDTH_MM/25.4,205/25.4),sharex=True)
    fig.subplots_adjust(left=.13,right=.975,top=.875,bottom=.075,wspace=.28,hspace=.43);tag(fig)
    positions=[p.value(t,k) for d in data for t in d['truth'] for k in ('x','y')]
    for i,d in enumerate(data):
        row=(i//2)*2;col=i%2;a,b=axes[row,col],axes[row+1,col]
        ts=[p.value(t,'time_s') for t in d['truth']]
        for field,color,ls in (('x',XCOLOR,'-'),('y',YCOLOR,'--')):
            ys=[p.value(t,field) for t in d['truth']]
            a.plot(ts,ys,color=color,lw=1.15,ls=ls,zorder=4)
            record_series(d['metric']['trial_id'],'truth',field,ts,ys)
        for field,color,marker in (('x',OX,'o'),('y',OY,'+')):
            x,y=p.observed_series(d['frames'],field)
            a.plot(x,y,lw=0,color=color,marker=marker,ms=2.5,mfc='none',mew=.55,alpha=.8,zorder=3)
            record_series(d['metric']['trial_id'],'observation',field,x,y)
        a.set_title(('A / P_B','B / P_B','BTQ / P_B','F / P_F')[i],pad=9,fontsize=10)
        a.set_ylim(min(positions)-.15,max(positions)+.15);a.set_ylabel('位置 / pitch' if col==0 else '')
        for field,color,ls in (('eta_target',XCOLOR,'-'),('eta_source',OX,'--')):
            x,y=p.observed_series(d['frames'],field);b.plot(x,y,color=color,lw=1,ls=ls)
            record_series(d['metric']['trial_id'],'observation',field,x,y)
        b.set(ylim=(-.04,1.07),ylabel='面积比例' if col==0 else '',xlabel='simulation时间 / s' if row==2 else '')
        for ax in (a,b):draw_refs(ax,d['refs'])
    for letter,ax in zip('abcdefgh',axes.flat):
        p.label(ax,letter);ax.set_xlim(*limits(data));ax.set_xticks([0,4,8,12]);ax.tick_params(labelbottom=True)
    handles=[Line2D([],[],color=XCOLOR,lw=1.15,label='内部 x'),Line2D([],[],color=YCOLOR,ls='--',label='内部 y'),
        Line2D([],[],color=OX,marker='o',mfc='none',lw=0,label='观测 x'),Line2D([],[],color=OY,marker='+',lw=0,label='观测 y'),
        Line2D([],[],color=OX,ls='--',label='源区残留'),Line2D([],[],color=XCOLOR,label='目标覆盖'),
        Line2D([],[],color=p.GOLD,ls=':',label='参考到达')]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.53,.967),ncol=4,
               fontsize=8.5,handlelength=1.5,columnspacing=1,handletextpad=.4)
    save(fig,'S3-A1_运动与覆盖_学术候选v2')

def control(data):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,175/25.4),sharex=True)
    fig.subplots_adjust(left=.15,right=.975,top=.90,bottom=.25,wspace=.35,hspace=.38);tag(fig)
    for i,(ax,d) in enumerate(zip(axes.flat,data)):
        for j,state in enumerate(p.STATES):
            times=state_points(d['frames'],state)
            ax.scatter(times,[j]*len(times),s=6 if j else 4.5,color=p.STATE_COLORS[j],marker=STATE_MARKERS[j],
                       alpha=.85 if j else .55,linewidths=.55 if j==0 else 0,zorder=3)
            DRAWN_STATES.extend(dict(trial_id=d['metric']['trial_id'],state=state,time_s=t) for t in times)
        dropped=[float(r['available_s']) for r in d['frames'] if not r.get('processing_s') and r.get('reason')=='CAMERA_DROPPED']
        ax.scatter(dropped,[-.25]*len(dropped),s=9,marker='|',color='#242B31',linewidths=.75,zorder=4)
        for event in d['events']:
            if event['event']=='Applied':
                ax.plot(float(event['time_s']),7,'|',color=p.GREEN,ms=6,mew=1)
                DRAWN_EVENTS.append(dict(trial_id=d['metric']['trial_id'],event='Applied',kind=action_kind(event),time_s=float(event['time_s'])))
            elif action_kind(event):
                color,marker,_=ACTIONS[action_kind(event)]
                ax.plot(float(event['time_s']),6,marker=marker,color=color,ms=4,lw=0,mew=.7 if marker=='x' else 0)
                DRAWN_EVENTS.append(dict(trial_id=d['metric']['trial_id'],event=event['event'],kind=action_kind(event),time_s=float(event['time_s'])))
        draw_refs(ax,d['refs']);ax.set_title(('A / P_B','B / P_B','BTQ / P_B','F / P_F')[i],pad=10,fontsize=10)
        ax.set_yticks(range(8),['Unknown','静止','运动','部分','到达','偏离','请求','Applied'])
        ax.set(ylim=(-.45,7.6),xlim=limits(data),xlabel='simulation时间 / s')
        ax.set_xticks([0,4,8,12]);ax.tick_params(labelbottom=True);p.label(ax,chr(97+i))
    handles=[Line2D([],[],color=c,marker=m,lw=0,label=t) for c,m,t in ACTIONS.values()]
    handles.extend([Line2D([],[],color=p.GREEN,marker='|',lw=0,label='模拟Applied'),
        Line2D([],[],color=p.GOLD,ls=':',label='参考到达'),Line2D([],[],color='#242B31',marker='|',lw=0,label='丢帧')])
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.53,.035),ncol=3,fontsize=8.5,
               handlelength=1.5,columnspacing=1.1,labelspacing=.5)
    save(fig,'S3-A2_状态与控制_学术候选v2')

def point(ax,figure,panel,category,method,protection,metric,x,y,lo,hi,**kwargs):
    ax.errorbar(x,y,yerr=[[max(0,y-lo)],[max(0,hi-y)]],**kwargs)
    PLOT_ROWS.append(dict(figure=figure,panel=panel,category=category,method=method,protection=protection,
                          metric=metric,x=x,estimate=y,lower=lo,upper=hi))

def comparison():
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    summary=p.validate_summary(p.read(p.S3/'formal_summary.csv'))
    intervals=p.read(p.S3FINAL/'tables/time_and_action_intervals.csv')
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,175/25.4))
    fig.subplots_adjust(left=.14,right=.98,top=.91,bottom=.13,hspace=.60,wspace=.42);tag(fig)
    for i,m in enumerate(p.METHODS):
        for j,scenario in enumerate(p.SCENARIOS):
            r=next(r for r in summary if r['scenario']==scenario and r['method']==m)
            xx=method_x_positions(j)[i]
            kw=dict(fmt=p.MARKERS[i],ms=3.5,color=COLORS[i],mfc=COLORS[i] if i==3 else 'white',
                    mew=.9,elinewidth=.8,capsize=1.2,lw=0,zorder=3+i)
            for ax,panel,key in ((axes[0,0],'a','path'),(axes[0,1],'b','unsafe')):
                y,lo,hi=[float(r[key+k])*100 for k in ('_rate','_ci_low','_ci_high')]
                point(ax,'S3-B',panel,scenario,m,r['protection'],key,xx,y,lo,hi,**kw)
            t=next(r for r in intervals if r['cohort']=='main' and r['scenario']==scenario and r['method']==m and r['metric']=='budgetized_completion_s')
            y,lo,hi=p.interval_values(t)
            point(axes[1,0],'S3-B','c',scenario,m,r['protection'],'budgetized_completion_s',xx,y,lo,hi,**kw)
    names=('正常','延迟','停滞','抖动','丢帧','偏离','故障')
    for ax in (axes[0,0],axes[0,1],axes[1,0]):
        ax.set_xticks(range(7),names);ax.set_xlim(-.65,6.65);ax.tick_params(axis='x',labelsize=8.5)
    for ax in axes[0]:ax.set_ylim(-5,105);ax.set_yticks([0,20,40,60,80,100])
    axes[0,0].set_ylabel('独立参考支持路径完成率 / %')
    axes[0,1].set_ylabel('含无支持推进请求的\ntrial比例 / %')
    axes[1,0].set(ylabel='预算化时间代价 / s',ylim=(0,25.5))
    cells=(('BTQ','P_B'),('BTQ','P_F'),('F_full','P_B'),('F_full','P_F'))
    actions=(('retries',XCOLOR,'o','Retry'),('recoveries','#A86059','s','Recovery'),('recovery_resends',YCOLOR,'^','resend'))
    for k,(field,color,marker,_) in enumerate(actions):
        for i,(method,protection) in enumerate(cells):
            r=next(r for r in intervals if r['scenario']=='deviation' and r['method']==method and r['protection']==protection and r['metric']==field)
            y,lo,hi=p.interval_values(r)
            point(axes[1,1],'S3-B','d','deviation',method,protection,field,i+(k-1)*.18,y,lo,hi,
                  fmt=marker,ms=4,color=color,mfc='white',mew=.9,elinewidth=.8,capsize=1.2,lw=0)
    axes[1,1].set_xticks(range(4),['BTQ\nP_B','BTQ\nP_F','F\nP_B','F\nP_F'])
    axes[1,1].set(ylabel='每trial额外控制动作\nApplied次数',ylim=(-.15,5.1),xlim=(-.5,3.5))
    axes[1,1].legend(handles=[Line2D([],[],color=c,marker=m,mfc='white',lw=0,label=t) for _,c,m,t in actions],
                      loc='upper center',fontsize=8.5,handlelength=1)
    titles=('独立参考支持路径','无支持推进请求风险','预算化路径完成时间代价','偏离场景：到达门×保护策略')
    for letter,ax,title in zip('abcd',axes.flat,titles):p.label(ax,letter);ax.set_title(title,pad=13,fontsize=9)
    fig.legend(handles=[Line2D([],[],color=COLORS[i],marker=p.MARKERS[i],mfc=COLORS[i] if i==3 else 'white',lw=0,label=n)
                        for i,n in enumerate(('A','B','BTQ','F'))],loc='lower center',bbox_to_anchor=(.54,.025),ncol=4,fontsize=9)
    save(fig,'S3-B_控制性能_学术候选v2')

def audit_statistics(data):
    """Independent saved-data arithmetic only; frozen bootstrap is not rerun."""
    metrics=p.read(p.S3/'formal_trials.csv');summary=p.read(p.S3/'formal_summary.csv')
    intervals=p.read(p.S3FINAL/'tables/time_and_action_intervals.csv');errors=[];actions=[];checks=0
    for r in summary:
        rs=[m for m in metrics if all(m[k]==r[k] for k in ('cohort','scenario','method','protection'))]
        if len(rs)!=20:errors.append('planned_n')
        for name,values in (('path',[m['path_complete']=='True' for m in rs]),('unsafe',[int(m['unsupported_requests'])>0 for m in rs])):
            lo,hi=wilson_check(sum(values),len(values))
            for actual,expect in ((r[name+'_rate'],sum(values)/len(values)),(r[name+'_ci_low'],lo),(r[name+'_ci_high'],hi)):
                checks+=1
                if not math.isclose(float(actual),expect,abs_tol=1e-12):errors.append('Wilson:'+name)
        if any(not math.isclose(float(m['budgetized_completion_s']),expected_cost(m),abs_tol=1e-12) for m in rs):errors.append('budgetized_cost')
    for method,protection in (('BTQ','P_B'),('BTQ','P_F'),('F_full','P_B'),('F_full','P_F')):
        rs=[m for m in metrics if m['scenario']=='deviation' and m['phase_mode']=='end_to_end' and m['method']==method and m['protection']==protection]
        for field in ('retries','recoveries','recovery_resends'):
            d=group_description([m[field] for m in rs]);actions.append(dict(method=method,protection=protection,metric=field,**d))
            frozen=next(r for r in intervals if r['scenario']=='deviation' and r['method']==method and r['protection']==protection and r['metric']==field)
            if d['n']!=20 or not math.isclose(d['mean'],float(frozen['mean']),abs_tol=1e-12):errors.append('action_mean')
    for row in PLOT_ROWS:
        if row['panel'] in ('a','b'):
            r=next(r for r in summary if r['cohort']=='main' and r['scenario']==row['category'] and r['method']==row['method'])
            expected=[float(r[row['metric']+s])*100 for s in ('_rate','_ci_low','_ci_high')]
        else:
            r=next(r for r in intervals if r['scenario']==row['category'] and r['method']==row['method'] and r['protection']==row['protection'] and r['metric']==row['metric'])
            expected=[float(r[k]) for k in ('mean','ci_low','ci_high')]
        if any(not math.isclose(row[k],v,abs_tol=1e-12) for k,v in zip(('estimate','lower','upper'),expected)):errors.append('plot_mapping')
    if len({d['metric']['exogenous_hash'] for d in data})!=1:errors.append('exogenous_mismatch')
    if len({d['metric']['p0_prefix_hash'] for d in data})!=1:errors.append('P0_mismatch')
    event_checks=[]
    for d in data:
        counts={a:sum(e['event']=='Applied' and action_kind(e)==a for e in d['events']) for a in ('Retry','Recovery','resend')}
        for a,k in (('Retry','retries'),('Recovery','recoveries'),('resend','recovery_resends')):
            if counts[a]!=int(d['metric'][k]):errors.append('Applied_action_count')
        event_checks.append(dict(trial_id=d['metric']['trial_id'],counts=counts,processed_frames=sum(bool(r.get('processing_s')) for r in d['frames'])))
    return dict(passed=not errors,errors=errors,wilson_scalar_checks=checks,plot_points_checked=len(PLOT_ROWS),
                action_groups=actions,events=event_checks,new_simulations=0,new_predictions=0,bootstrap_recomputed=False)

def captions():
    return '''# 论文图题与图注（图内不堆放长说明）

所有图均为SIMULATION。模型为二维点运动与简化SyntheticCamera Mask，空间单位pitch；不是CFD、物理电润湿计算、真实U-Net分割或实物试验。

## S1-A / S1-B

沿用原定稿图及其图注，两图未重新绘制。n=1机制示例，normal:262000:F:end_to_end；距离和方向投影源于处理后的模拟Mask质心，不是世界真值输入。

## S2-A 同一模拟视觉缓存下的到达确认时序

沿用原图、四层结构和全部数据。A_normal_263000，n=1。金色区域为独立参考到达区间，虚线为其上界加H=1s的主确认窗口终点。原始门的方块/叉号分别为通过/拒绝。单帧及BTQ、BTQ+S、BTQ+K、F_arrival均使用同一缓存；四强方法的曲线及确认时间在此例重合。

## S2-B 到达判据对比与失效边界

沿用原图和所有数值。M表示model-generated，X表示synthetic stress，不是实际液滴形变。NA表示相应条件没有独立参考到达，相关比例不定义，不等于0。(a)主窗口内支持确认数/独立参考到达数；(b)每格依次为提前确认数/无支持确认数，两者是独立的计数而非分数，planned=20；(c)F−BTQ的配对比例差及冻结的95%逐点区间；(d)主窗口漏确认数及主窗口后晚支持确认数，均以参考到达数为分母，晚支持属于主窗口漏确认的子集，不相加。完整13条件、五方法和延迟附表保留。图中只显示六个既定代表条件，不改变正式评价范围。

## S3-A1 四种闭环控制策略的模拟液滴位置与空间覆盖特征

预览第5页，deviation场景、正式seed265000，每策略n=1。A_fixed/P_B、B_single/P_B、BTQ/P_B、F_full/P_F共享相同外生世界扰动和相机随机数组，且P0源准备前缀相同。各自控制动作反作用于运动，因此闭环轨迹、后续Mask及终止时间不同，不是共同Mask输入的S2试验。实线/虚线为World内部x/y；空心圆/加号为全部实际处理Mask的观测x/y，不作为真值替代。覆盖率源/目标eta均以液滴Mask面积为分母。金色点线为独立参考到达区间上界。缺帧、任务/epoch切换断线，无插值补帧。两张S3-A图使用完全相同的四trial、方法顺序、时间范围和参考线；具体trial身份及hash见独立来源索引。

## S3-A2 四种闭环控制策略的状态与控制事件

预览第6页，与S3-A1同一批四trial，未拼接不同场景或seed。状态符号逐帧取自已处理观测，不补造状态。P_B在运输阶段不向控制器提供非到达五状态标签，日志中的Unknown因而也包含被该研究接口屏蔽的非到达标签，并不等于所有这些图像均无效，更不能视为液滴物理状态“未知”。P_F显示实际识别标签；Unknown还可来自真实观测拒绝。黑色短竖线显示原日志丢帧，不伪造预测状态。请求与模拟Applied分行显示；Retry指普通同目标重试，resend指恢复阶段确认后返回目标的重新施加（原始事件名仍为Retry），Recovery指回到局部源区。F示例实际为3次Recovery与3次resend、0次普通Retry；B与BTQ各3次普通Retry。Complete/Stop为终止事件，不画成有电极Applied的事务。未出现新请求的区间为Hold或pending；不为展示效果新增事件。模拟Applied既非串口ACK，也非实测高压。

## S3-B 事件驱动闭环策略的路径完成、安全性与预算化时间代价

7场景×4主策略，每条件每组n=20个配对simulation trial（seed265000–265019），共560主trial。配对单位为外生随机seed，非视频帧或实物重复；桥接单独分析不混池。

(a)独立参考支持路径完成率；(b)含至少一次无支持推进请求的trial比例，包括请求Update或终止推进Complete，分母为全部20个计划trial，而非推进请求总数。a/b点为二项比例，误差棒为双侧Wilson 95%置信区间；0%和100%点及相应非零区间保留。

(c)预算化路径完成时间代价。严格独立参考支持路径成功的trial使用实际模拟完成时间，其余trial按已冻结协议赋24s惩罚；24s是预算化指标定义，不是失败trial的实际运行耗时，也不是RMST。点为20个计划trial的算术均值，误差棒复用冻结的seed级2000次有放回bootstrap百分位95%逐点区间（分析随机源SeedSequence[20261026,303]），本轮未重新bootstrap。

(d)偏离场景：到达门×保护策略。四单元BTQ/P_B、BTQ/P_F、F_arrival/P_B和F_arrival/P_F（日志方法名F_full），每单元n=20。展示每trial额外控制动作实际模拟Applied次数的均值及同类bootstrap区间，不是总量或请求次数。三类动作是普通Retry、Recovery及恢复后返回目标resend，互不重复计数；不计常规Prepare、Start或Update。P_B两单元20个trial均为3/0/0次，P_F两单元均为0/3/3次，因此本场景每项组内无变化，区间退化为点，不是遗漏误差棒。该保护行为差异不能归因于S/K到达门的独立收益。主组F/BTQ的不同保护组合也不能直接解释为到达门消融。

全部区间为逐点描述，不是同时置信区间；未新增显著性检验或优越性结论。jitter源准备失败、dropout完成下降、持续故障及未尝试步骤保留在计划分母。零无支持请求不等于成功完成。
'''

def main():
    args=argparse.ArgumentParser();args.add_argument('--revise',action='store_true');ns=args.parse_args()
    if OUT.exists() and not ns.revise:raise FileExistsError(OUT)
    for name in ('figures','previews','QA','tables','source_data','绘图来源'): (OUT/name).mkdir(parents=True,exist_ok=True)
    previous_manifest=p.load(PREVIOUS/'source_manifest.json')
    protected={**previous_manifest['source_files'],**previous_manifest['protected_original_sha256']}
    protected.update({str(q):p.sha(q) for q in PREVIOUS.rglob('*') if q.is_file()})
    for old in (p.ROOT/'scripts/chapter2_paper_figure_closeout.py',p.ROOT/'scripts/plot_chapter2_s3_final.py'):
        protected[str(old)]=p.sha(old)
    copied=[]
    for pattern,folder in (('S1-*',PREVIOUS/'S1_原样参照'),('S2-*',PREVIOUS/'figures')):
        for q in folder.glob(pattern):
            if q.suffix in ('.pdf','.svg','.png'):
                dest=OUT/'figures'/q.name;shutil.copy2(q,dest);copied.append(dict(source=str(q),output=str(dest),sha256=p.sha(q)))
    for q in (PREVIOUS/'previews').glob('S2-*.png'):shutil.copy2(q,OUT/'previews'/q.name)
    for q in (PREVIOUS/'tables').iterdir():
        if q.is_file():shutil.copy2(q,OUT/'tables'/q.name)
    data=p.trial_data();p.OUT=OUT;style();motion(data);control(data);comparison()
    audit=audit_statistics(data);p.write_json(OUT/'QA/independent_data_check.json',audit)
    if not audit['passed']:raise AssertionError(audit['errors'])
    write_csv(OUT/'source_data/S3-B_实际绘制数值.csv',PLOT_ROWS)
    p.write_json(OUT/'source_data/S3-A_实际绘制序列.json',dict(series=DRAWN_SERIES,states=DRAWN_STATES,events=DRAWN_EVENTS))
    source_index={}
    a_sources=[]
    for d in data:
        copied_dir=OUT/'source_data'/d['metric']['method'];copied_dir.mkdir(exist_ok=True)
        paths=[]
        for sub in ('observations/frames.csv','observations/events.csv','evaluation/truth_ticks.csv','evaluation/reference_intervals.csv','trial_manifest.json'):
            q=p.remember(d['path']/sub);dest=copied_dir/q.name;shutil.copy2(q,dest);paths.append(dict(path=str(q),sha256=p.sha(q),local_copy=str(dest)))
        a_sources.append(dict(trial_id=d['metric']['trial_id'],scenario=d['metric']['scenario'],seed=d['metric']['seed'],
                             method=d['metric']['method'],protection=d['metric']['protection'],exogenous_hash=d['metric']['exogenous_hash'],files=paths))
    for name in ('S1-A','S1-B'):
        original=p.S1/(name+('_六阶段空间观测' if name=='S1-A' else '_分阶段空间特征')+'.pdf')
        inputs=(p.S1/'source_data/figure_manifest.json',p.S1/'source_data/S1_A_panel_sources.csv',
                p.S1/'source_data/S1_B_plot_points.csv',p.S1/'source_data/task_stages.csv')
        source_index[name]=dict(status='unchanged_frozen_figure',source_pdf=str(original),sha256=p.sha(original),
            frozen_input_index={str(q):p.sha(p.remember(q)) for q in inputs})
    for name in ('S2-A','S2-B'):
        source_index[name]=dict(status='unchanged_previous_candidate',copy=[r for r in copied if Path(r['source']).name.startswith(name)],
            official_statistics={str(q):p.sha(q) for q in (p.S2/'statistics').glob('*.csv')},
            trace_manifest=dict(path=str(p.S2FIG/'source_manifest.json'),sha256=p.sha(p.S2FIG/'source_manifest.json')))
    for name in ('S3-A1','S3-A2'):source_index[name]=dict(trials=a_sources,statistics='raw logged values; no aggregation or interpolation')
    for name in ('scripts/analyze_chapter2_s3_final.py','scripts/audit_chapter2_s3_final.py','dmf/chapter2_sim/s3/runner.py','dmf/chapter2_sim/v2/adapter.py'):
        p.remember(p.ROOT/name)
    source_index['S3-B']=dict(source_files={str(q):p.sha(q) for q in (p.S3/'formal_trials.csv',p.S3/'formal_summary.csv',
        p.S3FINAL/'tables/time_and_action_intervals.csv',p.S3FINAL/'QA/independent_final_audit.json')},
        rows_plotted=len(PLOT_ROWS),intervals_reused=True)
    p.write_json(OUT/'每图正式来源与hash索引.json',source_index)
    (OUT/'论文图题与图注_v2.md').write_text(captions(),encoding='utf-8')
    import pymupdf
    merged=pymupdf.open()
    for q in sorted((OUT/'figures').glob('*.pdf')):
        with pymupdf.open(q) as part:merged.insert_pdf(part)
    assert len(merged)==7
    merged.save(OUT/'第二章仿真论文图_学术整理候选v2.pdf');merged.close()
    changed=[name for name,h in {**protected,**p._USED}.items() if p.sha(name)!=h]
    assert not changed
    p.write_json(OUT/'source_manifest.json',dict(status='candidate_pending_user_review',simulation=True,
        new_trials=0,new_predictions=0,bootstrap_rerun=False,source_files=p._USED,protected_files=protected,changes=changed,
        copied_unchanged=copied,script_sha256=p.sha(__file__),source_index_sha256=p.sha(OUT/'每图正式来源与hash索引.json')))
    shutil.copy2(__file__,OUT/'绘图来源'/Path(__file__).name)
    print(json.dumps(dict(new_figure_count=3,combined_pages=7,protected_unchanged=len(protected),errors=changed,audit=audit['passed']),ensure_ascii=False))

if __name__=='__main__':main()
