import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    from dmf.vision.g4_model import load_package_manifest, package_contract
except ImportError:
    load_package_manifest=package_contract=None


class ModelPackageTests(unittest.TestCase):
    def package(self, folder):
        self.assertIsNotNone(package_contract,'Portable G4 package contract missing')
        path=Path(folder); (path/'unet_state.pt').write_bytes(b'only-for-metadata-test')
        meta=package_contract()
        meta.update(weights_file='unet_state.pt',weights_sha256=hashlib.sha256((path/'unet_state.pt').read_bytes()).hexdigest())
        (path/'manifest.json').write_text(json.dumps(meta),encoding='utf-8')
        return path,meta

    def test_valid_contract_and_hash(self):
        with tempfile.TemporaryDirectory() as t:
            p,m=self.package(t); self.assertEqual(load_package_manifest(p)['threshold'],.5)

    def test_weight_change_rejected_before_model_load(self):
        with tempfile.TemporaryDirectory() as t:
            p,m=self.package(t); (p/'unet_state.pt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash'): load_package_manifest(p)

    def test_preprocessing_change_rejected(self):
        for key,value in [('threshold',.6),('input_hw',[256,256]),('mean',[0,0,0]),('encoder','resnet18')]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as t:
                p,m=self.package(t); m[key]=value; (p/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
                with self.assertRaises(ValueError): load_package_manifest(p)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p,m=self.package(t); m['weights_file']='../outside.pt'; (p/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'path'): load_package_manifest(p)

    def test_batch_fallback_does_not_skip_remaining_images(self):
        from types import SimpleNamespace
        import numpy as np
        from dmf.vision.g4_model import G4UNetPredictor
        p=G4UNetPredictor.__new__(G4UNetPredictor)
        p.batch_size=4; p.batch_parity_checked=False; p.batch_parity_different_pixels=0
        p.torch=SimpleNamespace(cuda=SimpleNamespace(OutOfMemoryError=MemoryError))
        def infer(images):
            return [np.full((2,2),int(image)+(1 if len(images)>1 else 0),np.uint8) for image in images]
        p._infer=infer
        results=p.predict_batch(list(range(9)))
        self.assertEqual([int(r[0,0]) for r in results],list(range(9)))
        self.assertEqual(p.batch_size,1)


if __name__=='__main__': unittest.main()
