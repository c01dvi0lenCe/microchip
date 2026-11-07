import importlib
import math
import unittest


class TimedMixingTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('controllers.timed_mixing')
        except ModuleNotFoundError:
            self.fail('Independent timed mixing mechanism is not implemented')

    def test_exact_visual_reminders_without_row_wrap(self):
        m=self.module()
        self.assertEqual(m.TESTED_FAULT_IDS,{90,337,393,399,400})
        self.assertEqual(m.reminder_ids(),{70,89,90,91,110,317,336,337,338,357,373,392,393,394,399,400})

    def test_stuck_on_and_stuck_off_have_different_neighbor_rules(self):
        m=self.module()
        self.assertEqual(getattr(m,'STUCK_ON_IDS',None),{90,337,393})
        self.assertEqual(getattr(m,'STUCK_OFF_IDS',None),{399,400})
        self.assertFalse(m.reminder_ids() & {379,380,398})

    def test_square_route_two_cycles(self):
        self.assertEqual(self.module().build_square_route(190,2),(190,191,211,210,190,191,211,210,190))

    def test_invalid_boundary_and_non_integer_inputs(self):
        m=self.module()
        for first,cycles in [(20,1),(381,1),(400,1),(0,1),(401,1),(1,0),(1,1.5),(1,True)]:
            with self.subTest(first=first,cycles=cycles), self.assertRaises(ValueError):
                m.build_square_route(first,cycles)

    def test_no_next_request_before_applied_and_dwell(self):
        s=self.module().TimedMixing(190,1,1.0)
        self.assertEqual(s.next_request(0),190)
        self.assertIsNone(s.next_request(100))
        s.applied(190,100)
        self.assertIsNone(s.next_request(100.999))
        self.assertEqual(s.next_request(101),191)
        self.assertIsNone(s.next_request(103))

    def test_complete_only_after_final_dwell(self):
        s=self.module().TimedMixing(190,1,.1)
        now=0
        for eid in (190,191,211,210,190):
            self.assertEqual(s.next_request(now),eid)
            s.applied(eid,now+.2)
            now+=.31
        self.assertIsNone(s.next_request(now))
        self.assertTrue(s.complete)
        self.assertFalse(s.running)

    def test_stop_cancels_future_requests_but_can_reconcile_pending_applied(self):
        s=self.module().TimedMixing(190,1,1)
        self.assertEqual(s.next_request(0),190)
        s.stop()
        s.applied(190,.5)
        self.assertEqual(s.active_id,190)
        self.assertIsNone(s.next_request(10))
        self.assertFalse(s.complete)

    def test_wrong_ack_and_invalid_time_rejected(self):
        s=self.module().TimedMixing(190,1,1)
        s.next_request(0)
        with self.assertRaises(ValueError):s.applied(191,0)
        with self.assertRaises(ValueError):s.applied(190,float('nan'))
        for t in (-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError):s.next_request(t)

    def test_invalid_dwell_rejected(self):
        for value in (0,.01,61,math.inf,math.nan):
            with self.assertRaises(ValueError):self.module().TimedMixing(1,1,value)


if __name__=='__main__':unittest.main()
