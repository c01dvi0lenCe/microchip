"""Independent native-PNG arithmetic and immutable input audit; no inference."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def audit(root, run):
    samples={s['sample_id']:s for s in rows(root/'G2/frozen_samples.csv')}
    records=rows(run/'evaluation/per_image.csv')
    checked=[]
    for row in records:
        if row['eligible']!='True':
            assert row['method']=='background'
            assert all(row.get(k,'')=='' for k in ('dice','iou','precision','recall','fp','tp','fn','tn','prediction_path'))
            continue
        sample=samples[row['sample_id']]
        base=root/'G3_initial_baselines_v1' if row['method'] in ('otsu','background') else run/'evaluation'
        path=base/row['prediction_path']
        assert sha(path)==row['prediction_sha256']
        load=lambda p: cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),cv2.IMREAD_UNCHANGED)
        pred=load(path)
        gt=load(root/'G2'/sample['mask_path'])
        ignore=load(root/'G2'/sample['exclusion_mask_path'])
        assert pred.shape==gt.shape==ignore.shape
        assert np.isin(pred,[0,255]).all()
        valid=ignore==0
        p=(pred>0)&valid
        t=(gt>0)&valid
        tp=int((p&t).sum()); fp=int((p&~t).sum()); fn=int((~p&t).sum()); tn=int(valid.sum())-tp-fp-fn
        assert all(int(row[k])==v for k,v in dict(tp=tp,fp=fp,fn=fn,tn=tn).items())
        denominator=2*tp+fp+fn
        result=dict(dice=2*tp/denominator if denominator else 1.,
                    iou=tp/(tp+fp+fn) if tp+fp+fn else 1.,
                    precision=tp/(tp+fp) if tp+fp else (0. if t.any() else 1.),
                    recall=tp/(tp+fn) if tp+fn else 1.)
        assert all(abs(float(row[k])-v)<1e-12 for k,v in result.items())
        checked.append(dict(sample_id=row['sample_id'],method=row['method'],tp=tp,fp=fp,fn=fn,tn=tn,**result))
    assert len(records)==144 and len(checked)==114
    assert sum(r['method'] in ('unet','deeplabv3plus') for r in checked)==72
    ledgers={}
    for name in ('frozen_inputs_before.json','protected_sources_before.json'):
        ledger=json.loads((run/name).read_text(encoding='utf-8'))
        assert all(Path(p).is_file() and sha(p)==h for p,h in ledger.items())
        ledgers[name]=len(ledger)
    logs={m:rows(run/m/'epochs.csv') for m in ('unet','deeplabv3plus')}
    assert len(logs['unet'])==len(logs['deeplabv3plus'])==28
    assert [r['order_sha256'] for r in logs['unet']]==[r['order_sha256'] for r in logs['deeplabv3plus']]
    manifests=[]
    for name,log in logs.items():
        manifest=json.loads((run/name/'training_manifest.json').read_text(encoding='utf-8'))
        assert sha(run/name/'best.pt')==manifest['best_checkpoint_sha256']
        assert sha(run/name/'last.pt')==manifest['last_checkpoint_sha256']
        best=max(float(r['native_val_dice']) for r in log)
        assert abs(best-manifest['best_native_val_dice'])<1e-12
        assert int(log[-1]['stale_epochs'])==12
        assert all(int(r['optimizer_steps'])==36 for r in log)
        assert int(log[manifest['best_epoch']-1]['epoch'])==manifest['best_epoch']
        manifests.append(manifest)
    assert manifests[0]['initial_encoder_sha256']==manifests[1]['initial_encoder_sha256']
    output=run/'independent_native_scores.csv'
    with output.open('w',encoding='utf-8-sig',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(checked[0])); w.writeheader(); w.writerows(checked)
    result=dict(passed=True,native_predictions_checked=72,all_predictions_checked=114,
                planned_method_val_rows=144,unavailable_background_rows=30,
                source_ledgers_checked=ledgers,paired_epoch_orders_identical=True,
                common_encoder_initialization_identical=True,
                early_stop_and_best_weight_rules_passed=True,
                formal_independent_test_samples=0)
    (run/'independent_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--run',type=Path,required=True)
    args=p.parse_args(); audit(args.root,args.run)
