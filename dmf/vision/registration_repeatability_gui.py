"""Display-blinded offline clicks: no H, old positions, suggestions or residuals."""
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import cv2
import numpy as np

from .design_registration import file_hash, load_design_map
from .image_io import read_image
from .pilot_annotation_gui import ImageCanvas
from .registration_gui import RegistrationReviewApp
from .registration_repeatability import (exclude, load_review, record_click,
                                         save_review, seal_round)


def draft_overlay(canvas, scale, draft):
    if draft is None: return
    x, y = [v*scale for v in draft]
    canvas.create_line(x-7, y, x+7, y, fill='#0072b2', width=2)
    canvas.create_line(x, y-7, x, y+7, fill='#0072b2', width=2)


def coarse_region_overlay(canvas,scale,bounds,label):
    if bounds is None:return
    x0,y0,x1,y1=[v*scale for v in bounds]
    canvas.create_rectangle(x0,y0,x1,y1,outline='#ff9f1c',width=3,dash=(9,5),tags=('coarse_region',))
    canvas.create_text(x0+4,y0+4,text=f'定位范围 {label}（需手动点精确顶点）',anchor='nw',
        fill='#ff9f1c',font=('Microsoft YaHei UI',10,'bold'),tags=('coarse_region_label',))


def electrode_location(control_id):
    """Text from user-confirmed IDs; peripheral shapes do not get fake row/col."""
    if not isinstance(control_id,int) or not 1<=control_id<=420:
        raise ValueError('electrode ID must be 1..420')
    if control_id<=400:
        row,column=divmod(control_id-1,20)
        return f'核心阵列：第{row+1}行，第{column+1}列'
    corner={417:'左上',418:'右上',419:'右下',420:'左下'}
    if control_id in corner:return f'{corner[control_id]}角外围电极（L形）'
    return '外围电极：请看全局设计图中的橙色高亮'


def draw_global_reference(canvas, design, control_id, *, width=210, height=210):
    """Design-only orientation aid; deliberately has no image/H/pixel inputs."""
    canvas.delete('all')
    polygons=[np.asarray(e['polygon_map_mm'],float) for e in design['electrodes']]
    all_xy=np.concatenate(polygons);lo=all_xy.min(axis=0);hi=all_xy.max(axis=0)
    scale=min((width-20)/(hi[0]-lo[0]),(height-48)/(hi[1]-lo[1]))
    offset=np.array([(width-scale*(hi[0]-lo[0]))/2,24])
    for electrode,polygon in zip(design['electrodes'],polygons):
        selected=electrode['control_id']==control_id
        coords=((polygon-lo)*scale+offset).ravel().tolist()
        tags=(f'electrode_{electrode["control_id"]}',)+(('current_electrode',) if selected else ())
        canvas.create_polygon(*coords,fill='#e89a32' if selected else '#f2f2f2',
            outline='#222222' if selected else '#999999',width=1.5 if selected else .35,tags=tags)
    canvas.create_text(width/2,9,text='上：1 → 20（左到右）',font=('Microsoft YaHei UI',8))
    canvas.create_text(width/2,height-12,text=f'下：381 → 400  |  橙色：{control_id}',font=('Microsoft YaHei UI',8))


class RepeatabilityApp:
    def __init__(self, root, path):
        self.root=root; self.path=Path(path).resolve(); self.data=load_review(self.path)
        self.assisted=self.data.get('review_mode')=='coarse_region_assisted'
        self.design=load_design_map(self.path.parent/self.data['design_map_path'], self.data['design_map_sha256'])
        image_path=self.path.parent/self.data['image_path']
        if file_hash(image_path) != self.data['image_sha256']: raise ValueError('photo hash mismatch')
        self.image=read_image(image_path, cv2.IMREAD_COLOR)
        if self.image is None or list(self.image.shape[1::-1]) != self.data['image_size']:
            raise ValueError('native photo size mismatch')
        by_id={e['control_id']:e for e in self.design['electrodes']}
        for p in self.data['catalog']:
            if by_id[p['control_id']]['polygon_map_mm'][p['vertex_index']] != p['map_mm']:
                raise ValueError('declared design vertex mismatch')
        self.round_id=1 if not self.data['rounds'][0]['seal'] else 2
        self.current=self.data['rounds'][self.round_id-1]['order'][0]; self.draft=None
        root.title('第二章配准预实验：盲法重复点选（无H或历史点位）')
        if self.assisted:root.title('第二章配准预实验：粗范围辅助点选（非盲法，手动确认精确顶点）')
        root.geometry(f'{min(1400,root.winfo_screenwidth()-60)}x{min(940,root.winfo_screenheight()-100)}')
        root.option_add('*Font',('Microsoft YaHei UI',10))
        bar=ttk.Frame(root); bar.pack(fill='x', padx=8, pady=5)
        ttk.Label(bar,text='审核人').pack(side='left'); self.reviewer=tk.StringVar()
        ttk.Entry(bar,textvariable=self.reviewer,width=16).pack(side='left',padx=6)
        self.round_choice=tk.StringVar(value=str(self.round_id))
        control=ttk.Combobox(bar,textvariable=self.round_choice,values=('1','2'),state='readonly',width=3)
        control.pack(side='left'); control.bind('<<ComboboxSelected>>',self.change_round)
        ttk.Button(bar,text='封存本轮（16点都已处理后）',command=self.seal).pack(side='left',padx=6)
        ttk.Label(root,text=('右图橙色虚线框只提示大概范围；请按左侧局部图重新点精确顶点，不自动吸附或确认。' if self.assisted else
            '左侧全局图帮助找电极，局部图帮助找顶点；右侧原照片不显示H、导航点、旧坐标或误差。')).pack(fill='x',padx=8)
        ttk.Label(root,text='这是同一张照片的人工点选重复性，不是新增独立实验；只作预实验。',foreground='#9c4f19').pack(fill='x',padx=8)
        body=ttk.Panedwindow(root,orient='horizontal'); body.pack(fill='both',expand=True,padx=8,pady=5)
        left=ttk.Frame(body); right=ttk.Frame(body); body.add(left,weight=0); body.add(right,weight=1)
        table_frame=ttk.Frame(left);table_frame.pack(fill='both',expand=True)
        self.table=ttk.Treeview(table_frame,columns=('electrode','status'),show='tree headings',height=4,selectmode='browse')
        for key,title,width in (('#0','检查点',65),('electrode','电极',65),('status','本轮状态',95)):
            self.table.heading(key,text=title); self.table.column(key,width=width,stretch=False)
        self.table.pack(side='left',fill='both',expand=True); self.table.bind('<<TreeviewSelect>>',self.select)
        scroll=ttk.Scrollbar(table_frame,command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scroll.set)
        self.location=tk.StringVar()
        ttk.Label(left,textvariable=self.location,wraplength=430,
                  font=('Microsoft YaHei UI',11,'bold')).pack(fill='x',pady=(6,3))
        ttk.Label(left,text='从上往下数行，从左往右数列；C名不是电极号。').pack(fill='x')
        references=ttk.Frame(left);references.pack(fill='x',pady=5)
        global_frame=ttk.Frame(references);global_frame.pack(side='left',padx=(0,5))
        detail_frame=ttk.Frame(references);detail_frame.pack(side='left')
        ttk.Label(global_frame,text='全局设计图：找对应电极').pack()
        self.global_canvas=tk.Canvas(global_frame,width=210,height=210,bg='white',highlightthickness=0)
        self.global_canvas.pack()
        ttk.Label(detail_frame,text='局部设计图：找蓝色十字顶点').pack()
        self.map_canvas=tk.Canvas(detail_frame,width=210,height=210,bg='white',highlightthickness=0)
        self.map_canvas.pack()
        self.definition=tk.StringVar(); ttk.Label(left,textvariable=self.definition,wraplength=430).pack(fill='x')
        actions=ttk.Frame(right); actions.pack(fill='x')
        if self.assisted:ttk.Button(actions,text='回到当前粗范围',command=self.locate_region).pack(side='left',padx=3)
        ttk.Button(actions,text='确认刚点击的实际顶点（自动保存）',command=self.confirm).pack(side='left')
        ttk.Button(actions,text='不可见（填写原因）',command=self.mark_excluded).pack(side='left',padx=6)
        self.canvas=ImageCanvas(right,self.clicked); self.canvas.pack(fill='both',expand=True)
        self.status=tk.StringVar(); ttk.Label(root,textvariable=self.status,wraplength=1200).pack(fill='x',padx=8,pady=5)
        self.refresh(); self.table.selection_set(self.current); self.select()

    def point(self): return next(p for p in self.data['catalog'] if p['point_id']==self.current)

    def refresh(self):
        self.table.delete(*self.table.get_children())
        r=self.data['rounds'][self.round_id-1]
        features={p['point_id']:p for p in self.data['catalog']}
        for name in r['order']:
            status=r['observations'].get(name,{}).get('status','pending')
            self.table.insert('', 'end',iid=name,text=name,values=(features[name]['control_id'],
                {'pending':'未点选','confirmed':'已保存','excluded':'不可见'}[status]))
        self.status.set(f'第{self.round_id}轮：已处理{len(r["observations"])}/16；确认后自动保存，历史坐标不显示。')

    def select(self,event=None):
        selected=self.table.selection()
        if selected:self.current=selected[0]
        self.draft=None; p=self.point()
        self.location.set(f'检查点 {p["point_id"]} → 电极 {p["control_id"]}\n{electrode_location(p["control_id"])}')
        self.definition.set(f'当前顶点索引：{p["vertex_index"]}\n'+(
            '在右图粗范围内按左图蓝色十字找实际顶点；粗框不是边界或GT。非盲法辅助版本。' if self.assisted else
            '按设计蓝色十字所指的实际顶点点击；自行在原照片定位，不显示H预测或历史坐标。'))
        draw_global_reference(self.global_canvas,self.design,p['control_id'])
        # Reuse the existing design-only reference renderer, never its image overlay.
        RegistrationReviewApp.draw_design(self)
        self.map_canvas.scale('all',0,0,210/300,210/300)
        self.canvas.show(self.image,self.photo_overlay)
        if self.assisted:self.root.after_idle(self.locate_region)

    def photo_overlay(self,canvas,scale):
        if self.assisted:
            coarse_region_overlay(canvas,scale,self.data['guidance']['regions'][self.current]['bounds_px'],
                                  f'{self.current} / 电极{self.point()["control_id"]}')
        draft_overlay(canvas,scale,self.draft)

    def locate_region(self):
        if not self.assisted:return
        x0,y0,x1,y1=self.data['guidance']['regions'][self.current]['bounds_px']
        self.canvas.zoom.set('100%');self.canvas.redraw();canvas=self.canvas.canvas
        canvas.xview_moveto(max(0,((x0+x1)/2-canvas.winfo_width()/2)/self.image.shape[1]))
        canvas.yview_moveto(max(0,((y0+y1)/2-canvas.winfo_height()/2)/self.image.shape[0]))
        self.canvas.redraw()

    def clicked(self,x,y,drag):
        if not drag:
            self.draft=[float(x),float(y)]; self.canvas.redraw()
            self.status.set('刚点击的位置仅为本次草稿；确认后保存原始像素坐标，不作自动修正。')

    def change_round(self,event=None):
        requested=int(self.round_choice.get())
        if requested==2 and not self.data['rounds'][0]['seal']:
            messagebox.showinfo('先完成第一轮','第一轮全部处理并封存后，才可进入第二轮。',parent=self.root)
            self.round_choice.set(str(self.round_id)); return
        self.round_id=requested; self.current=self.data['rounds'][requested-1]['order'][0]
        self.refresh(); self.table.selection_set(self.current); self.select()

    def _persist_and_next(self):
        save_review(self.path,self.data)
        r=self.data['rounds'][self.round_id-1]
        remaining=[name for name in r['order'] if name not in r['observations']]
        if remaining:self.current=remaining[0]
        self.refresh(); self.table.selection_set(self.current); self.select()

    def confirm(self):
        try:
            if self.draft is None: raise ValueError('请先重新点击实际顶点')
            record_click(self.data,self.round_id,self.current,self.draft,self.reviewer.get())
            self._persist_and_next()
        except (ValueError,OSError) as exc:messagebox.showerror('未保存',str(exc),parent=self.root)

    def mark_excluded(self):
        reason=simpledialog.askstring('不可见原因','该点仍保留在16点分母；请说明原因。',parent=self.root)
        if not reason:return
        try:
            exclude(self.data,self.round_id,self.current,reason,self.reviewer.get()); self._persist_and_next()
        except (ValueError,OSError) as exc:messagebox.showerror('未保存',str(exc),parent=self.root)

    def seal(self):
        try:
            seal_round(self.data,self.round_id); save_review(self.path,self.data)
            messagebox.showinfo('本轮已封存','不能再改本轮。建议休息后再做下一轮；完成两轮后另行导出重复性报告。',parent=self.root)
            if self.round_id==1:self.round_choice.set('2'); self.change_round()
        except (ValueError,OSError) as exc:messagebox.showerror('未封存',str(exc),parent=self.root)


def run_review(path):
    root=tk.Tk(); RepeatabilityApp(root,path); root.mainloop()
