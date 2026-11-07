"""Report software/model/SDK paths without opening camera or serial hardware."""
import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def make_report(repo=ROOT,model_folder=None,query_cuda=True):
    repo=Path(repo);versions={};warnings=[]
    for dist in ('numpy','opencv-python','Pillow','pyserial','PyYAML','matplotlib',
                 'torch','torchvision','segmentation-models-pytorch'):
        try:versions[dist]=importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:versions[dist]=None
    base_modules=('tkinter','numpy','cv2','PIL','serial','yaml','matplotlib')
    missing=[name for name in base_modules if importlib.util.find_spec(name) is None]
    result=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),
        dependencies=versions,base_gui_ready=not missing,missing_base_modules=missing,
        cuda_available=None,backend='not_queried',model_ready=False,sdk_bindings_present=False,
        camera_opened=False,serial_opened=False,warnings=warnings)
    if query_cuda and versions['torch'] is not None:
        try:
            import torch
            result['cuda_available']=torch.cuda.is_available()
            result['backend']='cuda' if result['cuda_available'] else 'cpu'
            result['gpu_name']=torch.cuda.get_device_name(0) if result['cuda_available'] else None
        except Exception as exc:warnings.append('Torch/CUDA check: '+str(exc))
    if versions['segmentation-models-pytorch'] is None:warnings.append('Vision dependencies missing; raw GUI remains available')
    model_folder=Path(model_folder) if model_folder else repo/'models/g4_unet'
    try:
        from dmf.vision.g4_model import load_package_manifest
        meta=load_package_manifest(model_folder)
        result.update(model_ready=True,model_package=str(model_folder),model_weights_sha256=meta['weights_sha256'])
    except Exception as exc:warnings.append('Model package not ready: '+str(exc))
    try:
        import yaml
        local=repo/'configs/camera_mvs.local.yaml';base=repo/'configs/camera_mvs.yaml'
        path=local if local.exists() else base
        config=yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
        parameters=(config or {}).get('source',{}).get('parameters',{})
        sdk=parameters.get('sdk_python_path') or os.environ.get('MVS_SDK_PYTHON')
        if not sdk and os.environ.get('MVCAM_COMMON_RUNENV'):
            sdk=str(Path(os.environ['MVCAM_COMMON_RUNENV'])/'Samples/Python/MvImport')
        result['sdk_bindings_present']=bool(sdk and (Path(sdk)/'MvCameraControl_class.py').is_file())
    except Exception as exc:warnings.append('Camera configuration check: '+str(exc))
    if not result['sdk_bindings_present']:warnings.append('SDK path is configured on the camera computer; replay/GUI do not require it')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-package',type=Path)
    parser.add_argument('--require-model',action='store_true')
    args=parser.parse_args(argv)
    report=make_report(model_folder=args.model_package)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['base_gui_ready'] and (not args.require_model or report['model_ready']) else 1


if __name__=='__main__':raise SystemExit(main())
