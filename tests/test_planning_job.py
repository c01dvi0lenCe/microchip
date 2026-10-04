import threading
import time
import unittest

from controllers.planning_job import PlanningJobRunner


class PlanningJobRunnerTests(unittest.TestCase):
    def test_submit_returns_immediately_and_rejects_duplicate_job(self):
        release = threading.Event()
        runner = PlanningJobRunner()

        started_at = time.perf_counter()
        accepted = runner.submit(
            work=lambda: release.wait(1.0) or "done",
            on_success=lambda _result: None,
            on_error=lambda _error: None,
        )
        elapsed = time.perf_counter() - started_at

        self.assertTrue(accepted)
        self.assertLess(elapsed, 0.1)
        self.assertFalse(
            runner.submit(
                work=lambda: "second",
                on_success=lambda _result: None,
                on_error=lambda _error: None,
            )
        )
        release.set()
        runner.join_for_test(1.0)

    def test_drain_delivers_success_on_the_calling_thread(self):
        runner = PlanningJobRunner()
        callback_threads = []
        results = []
        caller_thread = threading.get_ident()

        runner.submit(
            work=lambda: 42,
            on_success=lambda result: (callback_threads.append(threading.get_ident()), results.append(result)),
            on_error=lambda _error: None,
        )
        runner.join_for_test(1.0)
        runner.drain()

        self.assertEqual(results, [42])
        self.assertEqual(callback_threads, [caller_thread])
        self.assertFalse(runner.is_active)

    def test_drain_delivers_worker_exception_and_restores_idle_state(self):
        runner = PlanningJobRunner()
        errors = []

        def fail():
            raise RuntimeError("planning failed")

        runner.submit(work=fail, on_success=lambda _result: None, on_error=errors.append)
        runner.join_for_test(1.0)
        runner.drain()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(str(errors[0]), "planning failed")
        self.assertFalse(runner.is_active)


if __name__ == "__main__":
    unittest.main()
