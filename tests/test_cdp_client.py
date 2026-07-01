import unittest

from src.cdp_client import ReadOnlyCdpClient


class ReadOnlyCdpClientTests(unittest.TestCase):
    def test_websocket_url_is_disabled_for_sprint_1(self):
        client = ReadOnlyCdpClient("http://172.17.0.1:9223/json/version")

        with self.assertRaisesRegex(RuntimeError, "read-only"):
            client.websocket_url()


if __name__ == "__main__":
    unittest.main()
