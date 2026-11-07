"""Independent point-review window, reusing the existing native-image canvas."""
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import cv2
import numpy as np

from .design_registration import freeze_fit, load_design_map, record_observation
from .image_io import read_image
from .pilot_annotation_gui import ImageCanvas
from .registration_workspace import load_workspace, save_workspace, build_report


class RegistrationReviewApp:
    def __init__(self, root, path):
        self.root=root;self.path=Path(path).resolve();self.workspace=load_workspace(self.path)
        self.design=load_design_map(self.path.parent/self.workspace['design_map_path'],
                                    self.workspace['design_map_sha256'])
        self.image=read_image(self.path.parent/self.workspace['image_path'],cv2.IMREAD_COLOR)
        self.current='F1';self.draft=None;self.dirty=False
        root.title('第二章 图像—电极配准：独立点位核对')
        if self.workspace.get('use_scope')=='pre_experiment_only':
            root.title('第二章 图像—电极配准：预实验，非最终标定')
        root.geometry(f'{min(1400,root.winfo_screenwidth()-60)}x{min(940,root.winfo_screenheight()-100)}')
        root.option_add('*Font',('Microsoft YaHei UI',10))
        top=ttk.Frame(root);top.pack(fill='x',padx=8,pady=5)
        ttk.Label(top,text='审核人').pack(side='left')
        self.reviewer=tk.StringVar();ttk.Entry(top,textvariable=self.reviewer,width=15).pack(side='left',padx=6)
        ttk.Button(top,text='保存核对记录',command=self.save).pack(side='left',padx=4)
        ttk.Button(top,text='冻结拟合 → 核对检查点',command=self.freeze).pack(side='left',padx=4)
        ttk.Button(top,text='导出新版本报告',command=self.export).pack(side='left',padx=4)
        ttk.Label(root,text='先核对 F1–F8 并冻结；再核对 C1–C16。空心圆仅是导航位置，必须重新点击实际电极顶点。').pack(fill='x',padx=8)
        if self.workspace.get('use_scope')=='pre_experiment_only':
            ttk.Label(root,text='预实验：不适用于最终实验或旧视频。最终芯片高度/装配与光学条件确定后需另行配准。',
                      foreground='#9c4f19').pack(fill='x',padx=8)
        body=ttk.Panedwindow(root,orient='horizontal');body.pack(fill='both',expand=True,padx=8,pady=5)
        left=ttk.Frame(body);right=ttk.Frame(body);body.add(left,weight=0);body.add(right,weight=1)
        self.table=ttk.Treeview(left,columns=('role','id','status'),show='tree headings',height=12,selectmode='browse')
        for key,label,width in (('#0','点',45),('role','用途',45),('id','电极',45),('status','核对',70)):
            self.table.heading(key,text=label);self.table.column(key,width=width,stretch=False)
        scroll=ttk.Scrollbar(left,command=self.table.yview);self.table.configure(yscrollcommand=scroll.set)
        self.table.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
        self.table.bind('<<TreeviewSelect>>',self._select)
        self.map_canvas=tk.Canvas(left,width=300,height=300,bg='white',highlightthickness=0)
        self.map_canvas.grid(row=1,column=0,columnspan=2,pady=6)
        self.definition=tk.StringVar();ttk.Label(left,textvariable=self.definition,wraplength=300).grid(row=2,column=0,columnspan=2)
        left.rowconfigure(0,weight=1)
        bar=ttk.Frame(right);bar.pack(fill='x')
        ttk.Button(bar,text='定位当前点（200%）',command=self.locate).pack(side='left')
        ttk.Button(bar,text='确认刚点击的实际顶点',command=self.confirm).pack(side='left',padx=6)
        ttk.Button(bar,text='检查点不可见 / 排除原因',command=self.exclude).pack(side='left')
        self.canvas=ImageCanvas(right,self._clicked);self.canvas.pack(fill='both',expand=True)
        self.status=tk.StringVar(value='请选择拟合点；输入审核人，再在真实图像中点击。')
        ttk.Label(root,textvariable=self.status,wraplength=1200).pack(fill='x',padx=8,pady=5)
        self.refresh();self.table.selection_set('F1');self._select()
        root.protocol('WM_DELETE_WINDOW',self.close)

    def point(self):
        return next(p for p in self.workspace['points'] if p['point_id']==self.current)

    def refresh(self):
        for point in self.workspace['points']:
            values=('拟合' if point['role']=='fit' else '检查',point['control_id'],
                    {'pending':'未核对','confirmed':'已核对','excluded':'不可见'}[point['status']])
            if self.table.exists(point['point_id']):self.table.item(point['point_id'],values=values)
            else:self.table.insert('', 'end',iid=point['point_id'],text=point['point_id'],values=values)

    def _select(self,event=None):
        selected=self.table.selection()
        if selected:self.current=selected[0]
        self.draft=None;point=self.point()
        self.definition.set(f'{point["point_id"]} / 电极 {point["control_id"]} / 顶点索引 {point["vertex_index"]}\n'
            f'设计坐标 {point["map_mm"][0]:.5f}, {point["map_mm"][1]:.5f} mm\n'
            '左图蓝色十字是所指顶点；右图需重新点选。不得点击液滴、反光或气泡边界。')
        self.draw_design();self.canvas.show(self.image,self.overlay)

    def draw_design(self):
        canvas=self.map_canvas;canvas.delete('all');point=self.point()
        electrode=next(e for e in self.design['electrodes'] if e['control_id']==point['control_id'])
        polygon=np.array(electrode['polygon_map_mm']);lo=polygon.min(axis=0)-.7;hi=polygon.max(axis=0)+.7
        scale=260/max(hi-lo);offset=(np.array([300,300])-scale*(hi-lo))/2
        convert=lambda xy:tuple((np.asarray(xy)-lo)*scale+offset)
        for other in self.design['electrodes']:
            poly=np.array(other['polygon_map_mm'])
            if np.all(poly.max(axis=0)>=lo) and np.all(poly.min(axis=0)<=hi):
                coords=[v for xy in poly for v in convert(xy)]
                canvas.create_polygon(coords,fill='#f0ede8' if other is electrode else '',
                    outline='#555555' if other is electrode else '#cccccc',width=1)
        x,y=convert(point['map_mm'])
        canvas.create_line(x-8,y,x+8,y,fill='#0072b2',width=2)
        canvas.create_line(x,y-8,x,y+8,fill='#0072b2',width=2)

    def overlay(self, canvas, scale):
        point=self.point();x,y=point['suggested_px'];x*=scale;y*=scale
        canvas.create_oval(x-8,y-8,x+8,y+8,outline='#ffe08a',width=2)
        actual=self.draft or point.get('observed_px')
        if actual:
            x,y=[v*scale for v in actual]
            canvas.create_line(x-8,y,x+8,y,fill='#55e2ff',width=2)
            canvas.create_line(x,y-8,x,y+8,fill='#55e2ff',width=2)

    def _clicked(self,x,y,drag):
        if drag:return
        self.draft=[float(x),float(y)];self.canvas.redraw()
        self.status.set(f'待确认点击：u={x:.2f}, v={y:.2f} px；此时尚未写入观测点。')

    def locate(self):
        self.canvas.zoom.set('200%');self.canvas.redraw();self.root.update_idletasks()
        x,y=self.point()['suggested_px'];canvas=self.canvas.canvas
        canvas.xview_moveto(max(0,(x*2-canvas.winfo_width()/2)/(self.image.shape[1]*2)))
        canvas.yview_moveto(max(0,(y*2-canvas.winfo_height()/2)/(self.image.shape[0]*2)))
        self.canvas.redraw()

    def confirm(self):
        try:
            if self.draft is None:raise ValueError('请先在真实图像中点击实际可见顶点，不能直接确认导航圆。')
            record_observation(self.workspace,self.current,self.draft,self.reviewer.get())
            self.dirty=True;self.draft=None;self.refresh();self.canvas.redraw()
            self.status.set(f'{self.current} 已确认。请保存；检查点误差不在核对期间显示。')
        except ValueError as exc:messagebox.showerror('未确认',str(exc),parent=self.root)

    def exclude(self):
        point=self.point()
        if self.workspace.get('evaluation_freeze'):
            messagebox.showerror('评价已封存','不能在查看结果后继续调整检查点；请另建预声明核对版本。',parent=self.root)
            return
        if point['role']!='check' or not self.workspace.get('fit_freeze'):
            messagebox.showinfo('保留拟合定义','拟合点需要全部可见；先完成并冻结拟合，再核对检查点。若拟合点被遮挡，请换帧或建立新的预声明点集。',parent=self.root)
            return
        if not self.reviewer.get().strip():
            messagebox.showerror('缺少审核人','请填写审核人。',parent=self.root);return
        reason=simpledialog.askstring('不可见检查点','请说明遮挡、反光等原因；该点仍保留在总分母。',parent=self.root)
        if reason and reason.strip():
            point.update(status='excluded',observed_px=None,reviewer=self.reviewer.get().strip(),
                         reviewed_utc=datetime.now(timezone.utc).isoformat(),exclusion_reason=reason.strip())
            self.dirty=True;self.refresh();self.draft=None;self.canvas.redraw()

    def save(self):
        try:
            save_workspace(self.path,self.workspace);self.dirty=False
            self.status.set('核对记录已保存；原视频、原地图和旧标注包未改。');return True
        except (ValueError,OSError) as exc:
            messagebox.showerror('未保存',str(exc),parent=self.root);return False

    def freeze(self):
        try:
            freeze_fit(self.workspace)
            if self.save():
                self.table.selection_set('C1');self._select()
                self.status.set('拟合已冻结，不能再修改。现在独立点击检查点；不显示残差以免反复调点。')
        except ValueError as exc:messagebox.showerror('未冻结',str(exc),parent=self.root)

    def export(self):
        if not self.save():return
        try:
            output=build_report(self.path)
            self.workspace=load_workspace(self.path)
            messagebox.showinfo('已生成新报告',str(output),parent=self.root)
        except (ValueError,OSError) as exc:messagebox.showerror('未导出',str(exc),parent=self.root)

    def close(self):
        if self.dirty:
            answer=messagebox.askyesnocancel('未保存','保存当前核对记录？',parent=self.root)
            if answer is None or (answer and not self.save()):return
        self.root.destroy()


def run_review(path):
    root=tk.Tk();RegistrationReviewApp(root,path);root.mainloop()
