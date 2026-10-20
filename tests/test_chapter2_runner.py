import csv
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
import yaml
import time
from unittest.mock import Mock

from dmf.experiment.runner import run_experiment
from dmf.experiment.config import load_config
from dmf.experiment.perception import PriorFeatures
from dmf.experiment.config import StateConfig
from dmf.vision.config import load_electrode_map
from dmf.vision.electrode_map import ElectrodeMap
from dmf.vision.contracts import FramePacket, VisionResult
from dmf.vision.algorithms.threshold import ThresholdSegmenter, ThresholdConfig


def read_rows(path):
    with path.open(encoding='utf8') as handle:return list(csv.DictReader(handle))


def make_inputs(root,points,**overrides):
    video=root/'sample.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(400,400))
    assert writer.isOpened()
    for point in points:
        frame=np.full((400,400,3),255,np.uint8)
        if point is not None:
            x,y,rx,ry=point;cv2.ellipse(frame,(x,y),(rx,ry),0,0,360,(0,0,0),-1)
        writer.write(frame)
    writer.release()
    (root/'map.yaml').write_text(yaml.safe_dump({'rows':20,'cols':20,'pitch_mm':1.,
       'core_corners_px':[[0,0],[400,0],[400,400],[0,400]]}),encoding='utf8')
    c={'experiment_id':'test','mode':'offline','route':[190,191],
       'synthetic_test_only':True,'source':{'video':'sample.avi'},'electrode_map':'map.yaml',
       'output_dir':'results','segmentation':{'name':'threshold','parameters':{'color_space':'gray','lower':[0],
       'upper':[100],'min_area_px':3,'morphology_kernel':1}},
       'state':{'min_area_px':3,'consistency_frames':1,'arrival_frames':2,'arrival_duration_s':.1,
       'eta_arr':.7,'eta_release':.12,'v_th_mm_s':.1,'position_tolerance_mm':.05},
       'control':{'source_frames':1,'source_duration_s':0,'wait_s':.3,'max_retries':1,'max_recoveries':1},
       'recording':{'raw':False,'mask':True,'overlay':True}}
    c.update(overrides)
    config=root/'experiment.yaml';config.write_text(yaml.safe_dump(c),encoding='utf8')
    return config


class RunnerTests(unittest.TestCase):
    def test_offline_video_features_actions_and_logs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            points=[(190,190,6,6)]*3+[(193,190,6,6),(195,190,6,6)]+[(200,190,12,6)]*2+[(210,190,6,6)]*3
            config=make_inputs(root,points)
            report=run_experiment(config)
            self.assertEqual(report['status'],'complete')
            rows=read_rows(root/'results/frames.csv')
            states={r['recognized_state'] for r in rows}
            self.assertTrue({'Stationary','Moving','Partial','Arrived'}<=states,states)
            self.assertTrue(all(r['command_sent']=='False' for r in rows))
            self.assertIn('predicted_position',rows[0]);self.assertIn('eta_source',rows[0])
            step=read_rows(root/'results/steps.csv')[0]
            self.assertEqual(step['success'],'True')
            self.assertTrue((root/'results/config_snapshot.yaml').is_file())
            self.assertTrue(list((root/'results/overlay').glob('*.png')))

    def test_retries_recovery_and_deviation_are_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            points=[(190,190,6,6)]*9+[(215,160,6,6)]*2
            report=run_experiment(make_inputs(root,points))
            rows=read_rows(root/'results/frames.csv')
            self.assertTrue({'Hold','Retry','Recovery'}<={r['event_action'] for r in rows})
            self.assertIn('Deviation',{r['recognized_state'] for r in rows})
            self.assertNotEqual(report['status'],'complete')

    def test_invalid_video_never_starts_and_logs_every_frame(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);run_experiment(make_inputs(root,[None]*5))
            rows=read_rows(root/'results/frames.csv')
            self.assertEqual(len(rows),5)
            self.assertEqual({r['event_action'] for r in rows},{'Hold'})

    def test_modes_and_threshold_protection(self):
        with tempfile.TemporaryDirectory() as td:
            config=make_inputs(Path(td),[(190,190,6,6)])
            with self.assertRaises(ValueError):load_config(config,mode='experiment')
            with self.assertRaises(ValueError):load_config(config,mode='dry_run')

    def test_prior_is_causal_and_rejected_points_do_not_poison_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);make_inputs(root,[])
            prior=PriorFeatures(load_electrode_map(root/'map.yaml'),StateConfig(position_tolerance_mm=.05))
            def point(x,y,t):
                frame=np.zeros((400,400,3),np.uint8);mask=np.zeros((400,400),np.uint8)
                cv2.circle(mask,(x,y),5,255,-1)
                return prior.extract(FramePacket('x',int(t*10),t,'test',frame),VisionResult(mask,(x,y),80,1,0,True),190,191,[])
            self.assertIsNone(point(187,190,0).predicted_position)
            point(189,190,.1)
            f=point(191,190,.2)
            self.assertAlmostEqual(f.predicted_position[0],191/20,places=4)
            self.assertFalse(point(300,300,.3).spatial_ok)
            f=point(195,190,.4)
            self.assertAlmostEqual(f.predicted_position[0],195/20,places=4)

    def test_stale_live_frame_cannot_start_a_command(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            config=make_inputs(root,[(190,190,6,6)],mode='dry_run',source={'backend':'opencv','frame_timeout_s':.01},
                segmentation={'name':'unet','model_path':'unused-test-only.onnx'})
            image=np.full((400,400,3),255,np.uint8);cv2.circle(image,(190,190),6,(0,0,0),-1)
            packet=FramePacket('test',0,time.monotonic()-1,'test',image)
            class Source:
                def __iter__(self):return iter([packet])
                def close(self):pass
            from dmf.experiment.actuator import AMActuator
            factory=Mock(side_effect=AssertionError('dry run must not open transport'))
            report=run_experiment(config,source_factory=lambda c:Source(),
                segmenter_factory=lambda c:ThresholdSegmenter(ThresholdConfig(color_space='gray',lower=(0,),upper=(100,))),
                actuator_factory=lambda mode,c:AMActuator(mode,c,transport_factory=factory))
            self.assertEqual(report['status'],'stopped')
            rows=read_rows(root/'results/frames.csv')
            self.assertEqual(rows[0]['event_action'],'Stop');factory.assert_not_called()

    def test_invalid_config_rejects_fractional_retry_limit_and_nan(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for settings in ({'control':{'max_retries':1.5}},{'state':{'eta_arr':float('nan')}}):
                with self.assertRaises(ValueError):load_config(make_inputs(root,[],**settings))

    def test_pre_recovery_frame_does_not_confirm_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            config=make_inputs(root,[],mode='dry_run',source={'backend':'opencv','frame_timeout_s':60},
                segmentation={'name':'unet','model_path':'unused-test-only.onnx'})
            captured_before_recovery_apply=[]
            start_apply_time=[]
            def frame(x,y,index,t):
                image=np.full((400,400,3),255,np.uint8);cv2.circle(image,(x,y),6,(0,0,0),-1)
                return FramePacket('test',index,t,'test',image)
            class Source:
                def __iter__(self):
                    yield frame(190,190,0,time.monotonic())
                    while not start_apply_time or time.monotonic()<=start_apply_time[0]+.005:
                        time.sleep(.001)
                    t=time.monotonic()
                    yield frame(215,160,1,t)
                    yield frame(190,190,2,captured_before_recovery_apply[0])
                def close(self):pass
            from dmf.experiment.actuator import AMActuator
            class Actuator(AMActuator):
                def execute(self,d):
                    if d.action=='Recovery':
                        captured_before_recovery_apply.append(time.monotonic())
                        time.sleep(.05)
                    result=super().execute(d)
                    if d.action=='Start':start_apply_time.append(time.monotonic())
                    return result
            run_experiment(config,source_factory=lambda c:Source(),
                segmenter_factory=lambda c:ThresholdSegmenter(ThresholdConfig(color_space='gray',lower=(0,),upper=(100,))),
                actuator_factory=Actuator)
            rows=read_rows(root/'results/frames.csv')
            self.assertEqual(rows[1]['event_action'],'Recovery',rows[1])
            self.assertEqual(rows[2]['event_action'],'Hold',rows[2])
            self.assertEqual(rows[2]['error'],'PRE_ACTUATION_FRAME',rows[2])

    def test_visual_step_success_survives_next_target_command_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            cfg=make_inputs(root,[(190,190,6,6)]*2+[(210,190,6,6)]*3,route=[190,191,192])
            from dmf.experiment.actuator import AMActuator,CommandResult
            class FailedUpdate(AMActuator):
                def execute(self,d):
                    if d.action=='Update':return CommandResult(2,False,False,'next-command failure')
                    return super().execute(d)
            report=run_experiment(cfg,actuator_factory=FailedUpdate)
            self.assertEqual(report['status'],'error')
            steps=read_rows(root/'results/steps.csv')
            self.assertEqual(steps[0]['success'],'True')
            self.assertEqual(steps[0]['target_electrode'],'191')
            self.assertEqual(steps[1]['success'],'False')
            self.assertEqual(steps[1]['target_electrode'],'192')

    def test_measured_candidate_polygon_is_used(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);make_inputs(root,[])
            base=load_electrode_map(root/'map.yaml')
            mapped=ElectrodeMap.from_calibration(base.calibration,{405:((280,280),(320,280),(320,320),(280,320))})
            prior=PriorFeatures(mapped,StateConfig(position_tolerance_mm=0))
            mask=np.zeros((400,400),np.uint8);cv2.circle(mask,(300,300),5,255,-1)
            packet=FramePacket('test',0,0,'test',np.zeros((400,400,3),np.uint8))
            result=VisionResult(mask,(300,300),80,1,0,True)
            self.assertTrue(prior.extract(packet,result,190,191,[405]).spatial_ok)


if __name__=='__main__':unittest.main()
