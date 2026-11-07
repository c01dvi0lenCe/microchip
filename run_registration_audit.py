"""Offline research audit / blinded repeats; no runtime configuration mutation."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from dmf.vision.registration_audit import audit_workspace, audit_dataset, final_manifest_template
from dmf.vision.registration_repeatability import load_review, prepare_repeatability, summarize


def write_json(path, value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def write_rows(path, rows):
    if not rows: return
    with Path(path).open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Independent photo pre-experiment audit; no hardware')
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare'); prepare.add_argument('--workspace',type=Path,required=True)
    prepare.add_argument('--previous-result',type=Path,required=True); prepare.add_argument('--output',type=Path,required=True)
    prepare.add_argument('--resources',type=Path,required=True); prepare.add_argument('--reviewed',type=Path,required=True)
    prepare.add_argument('--groups',type=Path,required=True); prepare.add_argument('--no-figures',action='store_true')
    assisted=commands.add_parser('prepare-assisted',help='new non-blind coarse-region review; never overwrite blind records')
    assisted.add_argument('--workspace',type=Path,required=True);assisted.add_argument('--output',type=Path,required=True)
    review=commands.add_parser('review'); review.add_argument('path',type=Path)
    report=commands.add_parser('repeat-report'); report.add_argument('path',type=Path); report.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    if args.command=='review':
        from dmf.vision.registration_repeatability_gui import run_review
        run_review(args.path); return
    if args.command=='repeat-report' and args.output is None:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f')+'_'+uuid.uuid4().hex[:6]
        args.output=args.path.resolve().parent/'reports'/stamp
    if args.output.exists(): raise FileExistsError('choose a new output directory; earlier results never overwritten')
    if args.command=='prepare-assisted':
        from dmf.vision.registration_guidance import prepare_assisted
        print(prepare_assisted(args.workspace,args.output));return
    if args.command=='repeat-report':
        data=load_review(args.path); result=summarize(data)
        args.output.mkdir(parents=True)
        write_json(args.output/'repeatability_result.json',result)
        write_json(args.output/'raw_review_snapshot.json',{k:v for k,v in data.items() if not k.startswith('_')})
        write_rows(args.output/'paired_clicks.csv',result['pairs'])
        print(args.output); return
    result=audit_workspace(args.workspace,args.previous_result)
    if not result['previous_comparison']['matches']: raise ValueError('independent arithmetic differs; investigate before delivery')
    dataset=audit_dataset(args.resources,args.reviewed,args.groups)
    args.output.mkdir(parents=True)
    write_json(args.output/'independent_registration_audit.json',result)
    write_rows(args.output/'independent_points.csv',result['points'])
    write_rows(args.output/'region_statistics.csv',[dict(region=k,**v) for k,v in result['region_statistics_px'].items()])
    write_json(args.output/'dataset_audit.json',dataset)
    write_rows(args.output/'video_resources.csv',dataset['videos']); write_rows(args.output/'reviewed_masks.csv',dataset['samples'])
    write_json(args.output/'calibration_manifest_TEMPLATE_NOT_VALID.json',final_manifest_template())
    repeat_path=prepare_repeatability(args.workspace,args.output/'盲法重复点选')
    write_json(args.output/'repeatability_result_PENDING.json',summarize(load_review(repeat_path)))
    if not args.no_figures:
        from dmf.vision.registration_audit_plotting import render_audit
        w=json.loads(args.workspace.read_text(encoding='utf-8'))
        render_audit(result,args.output,image_size=w['image_size'])
    write_json(args.output/'manifest.json',dict(schema='dmf_registration_independent_review_package_v1',
        created_at=datetime.now(timezone.utc).isoformat(),simulation=False,use_scope='pre_experiment_only',
        source_workspace=str(args.workspace.resolve()),source=result['source'],
        original_observations_modified=False,repeatability_status='pending_human_rounds',
        final_calibration_status='template_only_not_valid',data_audit_video_count=dataset['video_count']))
    print(args.output)


if __name__=='__main__':main()
