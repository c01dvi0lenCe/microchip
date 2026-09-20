import threading
import unittest

from controllers.electrode_transaction import ElectrodeTransactionClient


class ElectrodeTransactionClientTests(unittest.TestCase):
    def make_loopback(self, *, drop_first_commit=False):
        sent = []
        state = {"commit_count": 0, "sequence": ""}
        client = None

        def send_line(line):
            sent.append(line)
            sequence = line.split(":", 1)[1] if ":" in line else ""
            if line.startswith("BEGIN:"):
                state["sequence"] = sequence
                if drop_first_commit and state["commit_count"] == 1:
                    client.feed_line(f"ACK:{sequence}:APPLIED")
                else:
                    client.feed_line(f"ACK:{sequence}:BEGIN")
            elif line.startswith("COMMIT:"):
                state["commit_count"] += 1
                client.feed_line(f"ACK:{sequence}:QUEUED")
                if not drop_first_commit or state["commit_count"] > 1:
                    client.feed_line(f"ACK:{sequence}:APPLIED")
            elif line.startswith("SET:"):
                parts = line.split(":")
                client.feed_line(f"ACK:{state['sequence']}:SET:{parts[1]}")
            elif line == "ALL_OFF":
                client.feed_line("ACK:ALL_OFF")
            return True

        client = ElectrodeTransactionClient(
            send_line,
            ack_timeout_s=0.002,
            max_retries=2,
            initial_sequence=1,
        )
        return client, sent

    def test_builds_one_atomic_delta_transaction(self):
        client, sent = self.make_loopback()

        result = client.apply_changes({24: 1, 23: 0})

        self.assertTrue(result.applied)
        self.assertEqual(result.sequence, 1)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(
            sent,
            ["BEGIN:1", "SET:23:0", "SET:24:1", "COMMIT:1"],
        )

    def test_sequences_are_monotonic_between_successful_transactions(self):
        client, sent = self.make_loopback()

        first = client.apply_changes({1: 1})
        second = client.apply_changes({1: 0, 420: 1})

        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertIn("BEGIN:2", sent)
        self.assertIn("SET:420:1", sent)

    def test_timeout_retries_the_same_sequence_and_accepts_idempotent_applied(self):
        client, sent = self.make_loopback(drop_first_commit=True)

        result = client.apply_changes({7: 1})

        self.assertTrue(result.applied)
        self.assertEqual(result.sequence, 1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sent.count("BEGIN:1"), 2)
        self.assertEqual(sent.count("COMMIT:1"), 1)

    def test_timeout_after_two_retries_reports_failure(self):
        sent = []
        client = ElectrodeTransactionClient(
            lambda line: sent.append(line) or True,
            ack_timeout_s=0.001,
            max_retries=2,
            initial_sequence=1,
        )

        result = client.apply_changes({9: 1})

        self.assertFalse(result.applied)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(sent, ["BEGIN:1", "BEGIN:1", "BEGIN:1"])

    def test_waits_for_set_ack_before_commit(self):
        sent = []
        commit_before_set_ack = False
        set_ack_sent = False
        client = None

        def send_set_ack():
            nonlocal set_ack_sent
            set_ack_sent = True
            client.feed_line("ACK:1:SET:5")

        def send_line(line):
            nonlocal commit_before_set_ack
            sent.append(line)
            if line == "BEGIN:1":
                client.feed_line("ACK:1:BEGIN")
            elif line == "SET:5:1":
                timer = threading.Timer(0.01, send_set_ack)
                timer.daemon = True
                timer.start()
            elif line == "COMMIT:1":
                commit_before_set_ack = not set_ack_sent
                client.feed_line("ACK:1:APPLIED")
            return True

        client = ElectrodeTransactionClient(
            send_line,
            ack_timeout_s=0.1,
            max_retries=0,
            initial_sequence=1,
        )

        result = client.apply_changes({5: 1})

        self.assertTrue(result.applied)
        self.assertFalse(commit_before_set_ack)
        self.assertEqual(sent, ["BEGIN:1", "SET:5:1", "COMMIT:1"])

    def test_rejects_invalid_changes_before_sending(self):
        client, sent = self.make_loopback()

        with self.assertRaises(ValueError):
            client.apply_changes({421: 1})
        with self.assertRaises(ValueError):
            client.apply_changes({1: 2})

        self.assertEqual(sent, [])

    def test_all_off_waits_for_emergency_ack(self):
        client, sent = self.make_loopback()

        self.assertTrue(client.all_off())
        self.assertEqual(sent, ["ALL_OFF"])

    def test_feed_line_ignores_non_protocol_serial_output(self):
        client, _ = self.make_loopback()

        self.assertFalse(client.feed_line("TOUCH:10,20"))
        self.assertTrue(client.feed_line("ERR:BUSY"))

    def test_lost_begin_ack_retries_same_open_sequence(self):
        sent = []
        begin_count = 0
        client = None

        def send_line(line):
            nonlocal begin_count
            sent.append(line)
            if line == "BEGIN:1":
                begin_count += 1
                if begin_count > 1:
                    client.feed_line("ACK:1:BEGIN")
            elif line == "SET:3:1":
                client.feed_line("ACK:1:SET:3")
            elif line == "COMMIT:1":
                client.feed_line("ACK:1:APPLIED")
            return True

        client = ElectrodeTransactionClient(
            send_line,
            ack_timeout_s=0.001,
            max_retries=2,
            initial_sequence=1,
        )

        result = client.apply_changes({3: 1})

        self.assertTrue(result.applied)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sent.count("BEGIN:1"), 2)

    def test_all_off_resets_local_sequence_namespace(self):
        client, sent = self.make_loopback()
        client.apply_changes({1: 1})

        self.assertTrue(client.all_off())
        second = client.apply_changes({2: 1})

        self.assertEqual(second.sequence, 1)
        self.assertEqual(sent.count("BEGIN:1"), 2)


if __name__ == "__main__":
    unittest.main()
