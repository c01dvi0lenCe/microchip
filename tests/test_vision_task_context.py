import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from controllers.open_loop_sequence import compile_routes,TimedPlanSequence
from dmf.vision.contracts import FramePacket
from dmf.vision.task_regions import TaskBinding
from tests import test_task_regions as fixtures

try:
    from controllers.vision_task_context import regions_from_open_loop,load_observation_setup
except ImportError:
    regions_from_open_loop=load_observation_setup=None


class VisionTaskContextTests(unittest.TestCase):
    def test_applied_step_and_pending_request_are_read_only_task_context(self):
        self.assertIsNotNone(regions_from_open_loop,'Read-only open-loop observation adapter missing')
        with tempfile.TemporaryDirectory() as t:
            design,manifest,reference,conditions,_=fixtures.TaskRegionTests().fixture(t)
            binding=TaskBinding.load(design,manifest,reference,conditions)
            plan=compile_routes({'移动':(190,191,192)},forbidden_ids=())
            sequence=TimedPlanSequence(plan,1.)
            packet=FramePacket('fixture_capture',1,.1,'fixture',np.zeros((100,100,3),np.uint8))
            request=sequence.next_request(0.);sequence.applied(request,.04)
            r=regions_from_open_loop(plan,sequence,binding,packet,epoch=3,margin_px=2)[0]
            self.assertEqual((r.source_electrode,r.target_electrode),(190,190))
            sequence.next_request(1.04)
            r=regions_from_open_loop(plan,sequence,binding,packet,epoch=4,margin_px=2)[0]
            self.assertEqual((r.source_electrode,r.target_electrode),(190,191))
            self.assertEqual(sequence.index,1);self.assertIsNotNone(sequence.pending)

    def test_pixel_setup_cannot_claim_electrode_ids_or_change_control(self):
        self.assertIsNotNone(load_observation_setup,'Observation configuration loader missing')
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'watch.json'
            path.write_text(json.dumps(dict(schema='dmf_priority_regions_v1',
                pixel_regions=[dict(region_id='watch',roi=[1,2,30,40])])),encoding='utf8')
            packet=FramePacket('fixture',0,0.,'fixture',np.zeros((100,100,3),np.uint8))
            setup=load_observation_setup(path,packet)
            self.assertIsNone(setup['binding']);self.assertFalse(setup['regions'][0].control_eligible)
            self.assertIsNone(setup['regions'][0].target_electrode)


if __name__=='__main__':unittest.main()
