import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np

from dmf.experiment.actuator import AMActuator, SerialTransport
from dmf.experiment.sources import LiveSource
from dmf.experiment.segmenter import UNetSegmenter
from dmf.experiment.policy import Decision
from dmf.vision.contracts import FramePacket


class AdapterTests(unittest.TestCase):
    def test_offline_and_dry_run_never_construct_transport(self):
        for mode in ('offline','dry_run'):
            factory=Mock(side_effect=AssertionError('hardware must not be opened'))
            a=AMActuator(mode,{},transport_factory=factory)
            first=a.execute(Decision('Start',2))
            self.assertFalse(first.sent);self.assertTrue(first.accepted)
            self.assertFalse(a.execute(Decision('Hold')).sent)
            self.assertFalse(a.execute(Decision('Retry',2)).sent)
            a.close();factory.assert_not_called()

    def test_hold_is_suppressed_retry_reasserts_target_and_failed_ack_not_accepted(self):
        transport=Mock();transport.apply.return_value=(123,True,'')
        a=AMActuator('experiment',{'enable_am_output':True},transport_factory=lambda _:transport)
        self.assertTrue(a.execute(Decision('Start',2)).accepted)
        a.execute(Decision('Hold'));self.assertEqual(transport.apply.call_count,1)
        a.execute(Decision('Retry',2));self.assertEqual(transport.apply.call_count,2)
        self.assertEqual(transport.apply.call_args.args[0],{2:1})
        transport.apply.return_value=(125,False,'ACK timeout')
        self.assertFalse(a.execute(Decision('Update',3)).accepted)
        self.assertEqual(a.active,2)
        a.close()

    def test_hardware_requires_explicit_enable(self):
        factory=Mock()
        with self.assertRaises(ValueError):AMActuator('experiment',{},transport_factory=factory)
        factory.assert_not_called()

    def test_blocking_camera_is_bounded_by_frame_timeout(self):
        class Slow:
            def read(self,timeout_s):time.sleep(.2);return np.zeros((8,8,3),np.uint8)
            def close(self):pass
        started=time.monotonic()
        source=LiveSource({'frame_timeout_s':.03},factory=lambda:Slow())
        with self.assertRaises(TimeoutError):next(iter(source))
        source.close();self.assertLess(time.monotonic()-started,.15)

    def test_torchscript_binary_mask_has_original_shape(self):
        import torch
        class Binary(torch.nn.Module):
            def forward(self,x):return x[:,:1]*20-10
        with tempfile.TemporaryDirectory() as td:
            model=Path(td)/'test.pt'
            torch.jit.trace(Binary(),torch.zeros(1,3,16,16)).save(str(model))
            segmenter=UNetSegmenter({'model_path':str(model),'backend':'torchscript',
                'input_size':[16,16],'mean':[0,0,0],'std':[1,1,1],'output':'logits','threshold':.5})
            frame=np.zeros((24,32,3),np.uint8);frame[4:18,6:22]=255
            result=segmenter.process(FramePacket('test',0,0,'test',frame))
            self.assertEqual(result.mask.shape,(24,32))
            self.assertEqual(set(np.unique(result.mask)),{0,255})
            self.assertTrue(result.detected)

    def test_serial_total_deadline_bounds_ack_wait(self):
        from collections import deque
        class Port:
            def __init__(self,*a,**kw):self.is_open=True;self.lines=deque()
            def write(self,data):
                if data==b'ALL_OFF\n':self.lines.append(b'ACK:ALL_OFF\n')
                return len(data)
            def readline(self):
                if self.lines:return self.lines.popleft()
                time.sleep(.001);return b''
            def close(self):self.is_open=False
        cfg={'serial':{'port':'FAKE','baudrate':115200,'ack_timeout_s':.25,'command_timeout_s':.03,'max_retries':0}}
        with patch('serial.Serial',Port):
            transport=SerialTransport(cfg)
            start=time.monotonic();_,applied,_=transport.apply({2:1});elapsed=time.monotonic()-start
            transport.close()
        self.assertFalse(applied);self.assertLess(elapsed,.10)

    def test_serial_total_deadline_also_bounds_blocked_write(self):
        from collections import deque
        class Port:
            def __init__(self,*a,**kw):self.is_open=True;self.lines=deque();self.write_timeout=kw['write_timeout']
            def write(self,data):
                if data==b'ALL_OFF\n':self.lines.append(b'ACK:ALL_OFF\n');return len(data)
                time.sleep(self.write_timeout);raise TimeoutError('blocked write')
            def readline(self):
                if self.lines:return self.lines.popleft()
                time.sleep(.001);return b''
            def close(self):self.is_open=False
        cfg={'serial':{'port':'FAKE','baudrate':115200,'ack_timeout_s':.25,'command_timeout_s':.03,'max_retries':0}}
        with patch('serial.Serial',Port):
            transport=SerialTransport(cfg)
            start=time.monotonic();_,applied,_=transport.apply({2:1});elapsed=time.monotonic()-start
            transport.close()
        self.assertFalse(applied);self.assertLess(elapsed,.10)


if __name__=='__main__':unittest.main()
