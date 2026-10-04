import unittest
from dataclasses import replace

from dmf.experiment.config import StateConfig, ControlConfig
from dmf.experiment.perception import Observation, StateRecognizer
from dmf.experiment.policy import EventController
from dmf.vision.contracts import DropletState as S


def observation(**kwargs):
    values=dict(valid=True, centroid=(1., 1.), area=100., eta_source=.9,
                eta_target=0., distance=3.2, velocity=0., predicted_position=None,
                spatial_ok=True, temporal_ok=True)
    values.update(kwargs)
    return Observation(**values)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.config=StateConfig(consistency_frames=1, arrival_frames=1, arrival_duration_s=0)

    def state(self, **kwargs):
        return StateRecognizer(self.config).recognize(observation(**kwargs), 1.)

    def test_all_five_states(self):
        self.assertEqual(self.state(), S.STATIONARY)
        self.assertEqual(self.state(velocity=2), S.MOVING)
        self.assertEqual(self.state(eta_target=.35, eta_source=.5), S.PARTIAL)
        self.assertEqual(self.state(eta_target=.9, eta_source=.02), S.ARRIVED)
        self.assertEqual(self.state(spatial_ok=False), S.DEVIATION)

    def test_invalid_is_unknown_not_arrived(self):
        self.assertEqual(self.state(valid=False, eta_target=1), S.UNKNOWN)

    def test_arrival_requires_frames_and_elapsed_time_and_resets_on_miss(self):
        r=StateRecognizer(replace(self.config,arrival_frames=3,arrival_duration_s=.25))
        arrived=observation(eta_target=.9,eta_source=0)
        self.assertNotEqual(r.recognize(arrived,0), S.ARRIVED)
        self.assertNotEqual(r.recognize(arrived,.1), S.ARRIVED)
        self.assertNotEqual(r.recognize(observation(valid=False),.2), S.ARRIVED)
        self.assertNotEqual(r.recognize(arrived,.3), S.ARRIVED)
        self.assertNotEqual(r.recognize(arrived,.4), S.ARRIVED)
        self.assertEqual(r.recognize(arrived,.6), S.ARRIVED)

    def test_deviation_overrides_arrived_geometry(self):
        self.assertEqual(self.state(eta_target=.9,eta_source=0,temporal_ok=False),S.DEVIATION)


class PolicyTests(unittest.TestCase):
    def make(self,route=(1,2,3)):
        c=EventController(route, ControlConfig(wait_s=1,max_retries=1,source_frames=1,
            source_duration_s=0,max_recoveries=1))
        initial=c.decide(S.STATIONARY,0,source_confirmed=True)
        self.assertEqual(initial.action,'Start')
        c.accept(initial,0)
        return c

    def test_holds_do_not_reissue_and_stationary_not_unconditional_retry(self):
        c=self.make()
        for state in (S.MOVING,S.PARTIAL,S.STATIONARY,S.UNKNOWN):
            self.assertEqual(c.decide(state,.5).action,'Hold')
        self.assertEqual(c.retry_count,0)

    def test_retry_increment_on_accept_only_and_recovery_resets_after_source_confirmation(self):
        c=self.make()
        retry=c.decide(S.STATIONARY,1)
        self.assertEqual(retry.action,'Retry');self.assertEqual(c.retry_count,0)
        c.accept(retry,1);self.assertEqual(c.retry_count,1)
        self.assertEqual(c.decide(S.STATIONARY,1.5).action,'Hold')
        recovery=c.decide(S.STATIONARY,2)
        self.assertEqual(recovery.action,'Recovery');self.assertEqual(recovery.target,1)
        c.accept(recovery,2)
        self.assertEqual(c.retry_count,1)
        self.assertEqual(c.decide(S.ARRIVED,2.1,source_confirmed=False).action,'Hold')
        again=c.decide(S.STATIONARY,2.2,source_confirmed=True)
        self.assertEqual(again.action,'Retry');c.accept(again,2.2)
        self.assertEqual(c.retry_count,0)

    def test_update_and_final_complete(self):
        c=self.make()
        update=c.decide(S.ARRIVED,1)
        self.assertEqual((update.action,update.target),('Update',3));c.accept(update,1)
        self.assertEqual(c.source,2);self.assertEqual(c.retry_count,0)
        done=c.decide(S.ARRIVED,2)
        self.assertEqual(done.action,'Complete');self.assertIsNone(done.target)
        c.accept(done,2);self.assertTrue(c.complete)

    def test_deviation_recovery_is_bounded(self):
        c=self.make()
        recovery=c.decide(S.DEVIATION,.5);c.accept(recovery,.5)
        retry=c.decide(S.STATIONARY,.6,source_confirmed=True);c.accept(retry,.6)
        self.assertEqual(c.decide(S.DEVIATION,.8).action,'Stop')

    def test_no_start_without_confirmed_source(self):
        c=EventController((1,2),ControlConfig())
        self.assertEqual(c.decide(S.ARRIVED,0,source_confirmed=False).action,'Hold')


if __name__=='__main__':unittest.main()
