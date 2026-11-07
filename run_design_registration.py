"""Independent offline registration commands; does not open a camera or serial port."""
import argparse
from pathlib import Path

from dmf.vision.registration_workspace import prepare_workspace, build_report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Real-video frame / confirmed electrode-design registration')
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare',help='create a new review package without observations')
    prepare.add_argument('--design-dir',type=Path,required=True)
    prepare.add_argument('--pilot-workspace',type=Path,required=True)
    prepare.add_argument('--resource-manifest',type=Path,required=True)
    prepare.add_argument('--output',type=Path,required=True)
    prepare.add_argument('--no-figures',action='store_true')
    photos=commands.add_parser('prepare-photos',help='native photo pre-experiment; not final calibration')
    photos.add_argument('--design-dir',type=Path,required=True)
    photos.add_argument('--inputs',type=Path,required=True)
    photos.add_argument('--output',type=Path,required=True)
    photos.add_argument('--no-figures',action='store_true')
    build=commands.add_parser('build',help='export a new version, never overwrite previous reports')
    build.add_argument('workspace',type=Path)
    build.add_argument('--no-figures',action='store_true')
    review=commands.add_parser('review',help='manually click and confirm visible actual vertices')
    review.add_argument('workspace',type=Path)
    args=parser.parse_args(argv)
    if args.command=='prepare':
        paths=prepare_workspace(args.design_dir,args.pilot_workspace,args.resource_manifest,args.output)
        for path in paths:
            print(build_report(path,figures=not args.no_figures))
    elif args.command=='prepare-photos':
        from dmf.vision.registration_photos import prepare_photo_workspace
        paths=prepare_photo_workspace(args.design_dir,args.inputs,args.output)
        for path in paths:print(build_report(path,figures=not args.no_figures))
    elif args.command=='build':print(build_report(args.workspace,figures=not args.no_figures))
    else:
        from dmf.vision.registration_gui import run_review
        run_review(args.workspace)


if __name__=='__main__':main()
