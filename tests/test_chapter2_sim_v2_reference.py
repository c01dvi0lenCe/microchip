from types import SimpleNamespace
import unittest

from dmf.chapter2_sim.v2.reference import derive_reference
from dmf.chapter2_sim.v2.spec import ReferenceSpec


class ReferenceContinuityTests(unittest.TestCase):
    def setUp(self):
        self.geometry=SimpleNamespace(centers={191:(0.,0.)})
        self.spec=ReferenceSpec(dwell_s=.15)

    def row(self,t,phase='transport',epoch=1):
        return dict(step=0,target=191,time_s=t,phase=phase,epoch=epoch,
                    x=0.,y=0.,true_speed=0.)

    def reference(self,rows):
        return derive_reference(rows,self.geometry,self.spec,.01,1)

    def test_recovery_cannot_bridge_short_transport_segments(self):
        rows=[self.row(i*.01) for i in range(10)]
        rows += [self.row(.1+i*.01,'recovering') for i in range(30)]
        rows += [self.row(.4+i*.01,epoch=3) for i in range(10)]
        self.assertEqual(self.reference(rows),[])

    def test_gap_and_epoch_reset_independent_reference_dwell(self):
        first=[self.row(i*.01) for i in range(10)]
        self.assertEqual(self.reference(first+[self.row(.3+i*.01) for i in range(10)]),[])
        self.assertEqual(self.reference(first+[self.row(.1+i*.01,epoch=2) for i in range(10)]),[])

    def test_contiguous_new_epoch_can_establish_its_own_reference(self):
        rows=[self.row(i*.01) for i in range(10)]
        rows += [self.row(.1+i*.01,epoch=2) for i in range(16)]
        reference=self.reference(rows)
        self.assertEqual(len(reference),1)
        self.assertAlmostEqual(reference[0]['dwell_begin_s'],.1)
        self.assertAlmostEqual(reference[0]['upper_s'],.25)


if __name__=='__main__':unittest.main()
