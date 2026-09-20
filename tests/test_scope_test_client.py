import unittest

from controllers.scope_test_client import ScopeTestClient, ScopeTestConfig, matrix_electrode_id


class ScopeTestConfigTests(unittest.TestCase):
    def test_maps_physical_20x21_matrix_ids_like_firmware(self):
        self.assertEqual(matrix_electrode_id(1, 1), 1)
        self.assertEqual(matrix_electrode_id(20, 20), 400)
        self.assertEqual(matrix_electrode_id(1, 21), 401)
        self.assertEqual(matrix_electrode_id(20, 21), 420)

    def test_h5_requires_same_row_adjacent_columns(self):
        ScopeTestConfig(mode="H5B", row=3, col=7, row_b=3, col_b=8).validate()
        with self.assertRaisesRegex(ValueError, "同一行且列号相邻"):
            ScopeTestConfig(mode="H5B", row=3, col=7, row_b=4, col_b=7).validate()

    def test_builds_one_based_chapter1_start_command(self):
        config = ScopeTestConfig(
            mode="H6",
            row=20,
            col=21,
            row_b=1,
            col_b=2,
            phase="FALLING_EDGE",
        )
        self.assertEqual(
            config.start_command(),
            "CH1:START:H6:20:21:1:2:FALLING_EDGE",
        )

    def test_builds_array20_retention_command_with_frame_frequency(self):
        config = ScopeTestConfig(mode="RET_ARRAY20", row=4, col=7, scan_frequency_hz=500)

        self.assertEqual(
            config.start_command(),
            "CH1:START:RET_ARRAY20:4:7:1:2:HIGH_EARLY:500",
        )

    def test_scan_retention_rejects_unsupported_frequency(self):
        with self.assertRaisesRegex(ValueError, "扫描频率"):
            ScopeTestConfig(mode="RET_ARRAY20", scan_frequency_hz=125).validate()


class ScopeTestClientTests(unittest.TestCase):
    def test_start_waits_for_matching_firmware_ack(self):
        sent = []
        client = None

        def send_line(line):
            sent.append(line)
            client.feed_line("ACK:CH1:START:H3A")
            return True

        client = ScopeTestClient(send_line, timeout_s=0.01)
        result = client.start(ScopeTestConfig(mode="H3A"))

        self.assertTrue(result.ok)
        self.assertEqual(sent, ["CH1:START:H3A:1:1:1:2:HIGH_EARLY"])

    def test_scope_client_does_not_consume_atomic_transaction_ack(self):
        client = ScopeTestClient(lambda _line: True)

        self.assertFalse(client.feed_line("ACK:27:APPLIED"))
        self.assertFalse(client.feed_line("ERR:27:TIMEOUT"))
        self.assertTrue(client.feed_line("ERR:CH1:CONFIG"))

    def test_array20_retention_accepts_ack_with_actual_timing(self):
        client = None

        def send_line(_line):
            client.feed_line("ACK:CH1:START:RET_ARRAY20:800:1240:62:55")
            return True

        client = ScopeTestClient(send_line, timeout_s=0.01)

        result = client.start(ScopeTestConfig(mode="RET_ARRAY20", scan_frequency_hz=800))

        self.assertTrue(result.ok)
        self.assertEqual(result.response, "ACK:CH1:START:RET_ARRAY20:800:1240:62:55")

    def test_stop_reports_timeout_without_ack(self):
        client = ScopeTestClient(lambda _line: True, timeout_s=0.001)

        result = client.stop()

        self.assertFalse(result.ok)
        self.assertIn("超时", result.error)


if __name__ == "__main__":
    unittest.main()
