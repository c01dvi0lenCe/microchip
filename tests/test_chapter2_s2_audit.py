import unittest
try:
    from dmf.chapter2_sim.s2.audit import compare_signatures
except ModuleNotFoundError:
    compare_signatures=None


class S2AuditTests(unittest.TestCase):
    def test_event_ids_do_not_create_method_difference(self):
        self.assertIsNotNone(compare_signatures,'read-only S2 audit missing')
        a=[dict(step_id=0,target=191,timestamp_s=1.,event_id='a')]
        b=[dict(step_id=0,target=191,timestamp_s=1.,event_id='b')]
        self.assertTrue(compare_signatures(a,b))
        b[0]['timestamp_s']=1.01
        self.assertFalse(compare_signatures(a,b))


if __name__=='__main__':unittest.main()
