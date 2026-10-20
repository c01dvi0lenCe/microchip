"""Prepare/open an offline review workspace without accessing AM or the camera."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from dmf.vision.pilot_annotation import PilotWorkspace, prepare_pilot


def main(argv=None):
    parser=argparse.ArgumentParser(description='Chapter 2 offline Pilot annotation')
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare')
    prepare.add_argument('--dataset',type=Path,required=True)
    prepare.add_argument('--output',type=Path,required=True)
    gui=commands.add_parser('gui');gui.add_argument('--workspace',type=Path,required=True)
    report=commands.add_parser('report');report.add_argument('--workspace',type=Path,required=True)
    refresh=commands.add_parser('refresh-drafts');refresh.add_argument('--workspace',type=Path,required=True)
    layout=commands.add_parser('confirm-layout');layout.add_argument('--workspace',type=Path,required=True)
    layout.add_argument('--pitch-mm',type=float,required=True)
    audit=commands.add_parser('audit');audit.add_argument('--workspace',type=Path,required=True)
    extra=commands.add_parser('add-frames');extra.add_argument('--workspace',type=Path,required=True)
    extra.add_argument('--clip-id',required=True);extra.add_argument('--frames',type=int,nargs='+',required=True)
    args=parser.parse_args(argv)
    if args.command=='gui':
        from dmf.vision.pilot_annotation_gui import launch
        launch(args.workspace);return
    if args.command=='prepare':
        result=prepare_pilot(args.dataset,args.output)
        launcher=args.output/'启动标注.cmd'
        interpreter=Path(sys.executable).with_name('pythonw.exe')
        if not interpreter.exists():interpreter=Path(sys.executable)
        launcher.write_text(f'@echo off\r\nchcp 65001 >nul\r\nstart "" "{interpreter}" "{Path(__file__).resolve()}" gui --workspace "%~dp0."\r\n',encoding='utf-8',newline='')
    else:
        workspace=PilotWorkspace(args.workspace)
        if args.command=='audit':
            print(json.dumps(workspace.audit_inputs(),indent=2));return
        if args.command=='confirm-layout':workspace.confirm_layout(args.pitch_mm)
        if args.command=='refresh-drafts':workspace.refresh_drafts()
        if args.command=='add-frames':
            for frame in args.frames:workspace.add_frame(args.clip_id,frame)
        result=workspace.report()
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
