from __future__ import annotations

import socket
import ssl
import time
import unittest

from mqtt_fake_broker import FakeBroker
from signalbar.mqtt import packets
from signalbar.mqtt.client import ConnackError, MqttClient, MqttError, TlsHandshakeTimeout, describe_error


class PacketTests(unittest.TestCase):
    def test_remaining_length_round_trips_at_every_byte_boundary(self):
        for value, encoded in ((0, b"\x00"), (127, b"\x7f"), (128, b"\x80\x01"), (16383, b"\xff\x7f"),
                               (16384, b"\x80\x80\x01"), (2097152, b"\x80\x80\x80\x01")):
            with self.subTest(value=value):
                self.assertEqual(packets.encode_length(value), encoded)
        for size in (127, 128, 16383, 16384):
            payload = b"x" * (size - 3)  # the topic "t" takes three bytes
            self.assertEqual(packets.Reader().feed(packets.publish("t", payload))[0][2], b"\x00\x01t" + payload)
        with self.assertRaises(packets.PacketError):
            packets.encode_length(268_435_456)

    def test_connect_publish_and_subscribe_encode_byte_for_byte(self):
        self.assertEqual(packets.connect("c", 30), bytes.fromhex("100d00044d5154540402001e000163"))
        data = packets.connect("id", 30, username="u", password="p", will=("t", "offline", True))
        self.assertEqual(data[2 + 6 + 1], 0x80 | 0x40 | 0x20 | 0x04 | 0x02)
        self.assertTrue(data.endswith(b"\x00\x01u\x00\x01p"))
        self.assertIn(b"\x00\x01t\x00\x07offline", data)
        self.assertEqual(packets.publish("a/b", "hi", retain=True), b"\x31\x07\x00\x03a/bhi")
        self.assertEqual(packets.subscribe(7, ["x"]), b"\x82\x06\x00\x07\x00\x01x\x00")

    def test_reader_handles_split_and_batched_packets(self):
        reader = packets.Reader()
        stream = b"\x20\x02\x00\x00" + packets.publish("t", b"\xff\x00", retain=True) + b"\xd0\x00"
        self.assertEqual(reader.feed(stream[:3]), [])
        out = reader.feed(stream[3:])
        self.assertEqual([p[0] for p in out], [packets.CONNACK, packets.PUBLISH, packets.PINGRESP])
        self.assertEqual(packets.parse_publish(out[1][1], out[1][2]), ("t", b"\xff\x00", True, 0, None))
        self.assertEqual(packets.parse_publish(0x02, b"\x00\x01t\x00\x2apayload"), ("t", b"payload", False, 1, 42))

    def test_oversize_overlong_and_malformed_packets_are_refused(self):
        for feed in (lambda: packets.Reader(limit=10).feed(b"\x30\x0b" + b"\x00" * 11),
                     lambda: packets.Reader().feed(b"\x30\xff\xff\xff\xff\x01"),
                     lambda: packets.parse_publish(0, b"\x00\x02\xff\xfe"),
                     lambda: packets.parse_publish(0, b"\x00")):
            with self.assertRaises(packets.PacketError):
                feed()


class ClientTests(unittest.TestCase):
    def make(self, broker, **kwargs):
        client = MqttClient("127.0.0.1", broker.port, "gca-test", backoff=(0.05, 0.2), **kwargs)
        self.addCleanup(broker.close)
        self.addCleanup(client.stop)  # runs before broker.close
        return client

    def test_connects_with_will_subscribes_and_publishes(self):
        broker = FakeBroker(username="u", password="p")
        connected, received = [], []
        client = self.make(broker, username="u", password="p", will=("gca/availability", "offline", True),
                           on_connect=lambda: connected.append(1), on_message=lambda *m: received.append(m))
        client.subscribe("homeassistant/status")
        client.start()
        self.assertTrue(broker.wait_for(lambda: client.connected and broker.subscribed))
        self.assertTrue(client.publish("gca/availability", "online", retain=True))
        broker.send(packets.publish("homeassistant/status", "online", retain=True))
        self.assertTrue(broker.wait_for(lambda: broker.published and received))
        self.assertEqual(broker.published[0], ("gca/availability", b"online", True))
        self.assertEqual(received[0], ("homeassistant/status", b"online", True))
        info = broker.connects[0]
        self.assertEqual((info["username"], info["will_topic"], info["will_message"], info["will_retain"]),
                         ("u", "gca/availability", "offline", True))
        self.assertEqual((connected, client.phase, client.last_reason), ([1], "connected", ""))

    def test_a_wrong_password_is_reported_and_retried(self):
        broker = FakeBroker(username="u", password="right")
        client = self.make(broker, username="u", password="wrong")
        client.start()
        self.assertTrue(broker.wait_for(lambda: len(broker.connects) >= 2))
        self.assertFalse(client.connected_once)
        self.assertEqual(client.last_error, "bad username or password")
        self.assertEqual(client.last_reason, "Wrong username or password")

    def test_reconnects_and_subscribes_again_after_a_drop_or_garbage(self):
        broker = FakeBroker()
        connects = []
        client = self.make(broker, on_connect=lambda: connects.append(1))
        client.subscribe("homeassistant/status")
        client.start()
        self.assertTrue(broker.wait_for(lambda: client.connected))
        broker.drop()
        self.assertTrue(broker.wait_for(lambda: len(connects) == 2, timeout=5))
        self.assertEqual(broker.subscribed, ["homeassistant/status"] * 2)
        broker.send(b"\x30\xff\xff\xff\xff\x01")
        self.assertTrue(broker.wait_for(lambda: len(connects) == 3, timeout=5))
        client._sock.close()  # as a close() from another thread would
        self.assertTrue(broker.wait_for(lambda: len(connects) == 4, timeout=5))

    def test_a_silent_broker_is_caught_by_the_keepalive(self):
        broker = FakeBroker(answer_pings=False)
        client = self.make(broker, keepalive=1)
        client.start()
        self.assertTrue(broker.wait_for(lambda: client.connected))
        self.assertTrue(broker.wait_for(lambda: len(broker.connects) >= 2, timeout=6))
        self.assertIn("keepalive", client.last_error)

    def test_stop_sends_disconnect_and_a_stop_mid_handshake_never_connects(self):
        broker = FakeBroker()
        client = self.make(broker)
        client.start()
        self.assertTrue(broker.wait_for(lambda: client.connected))
        client.stop()
        self.assertTrue(broker.wait_for(lambda: broker.disconnects == 1))
        self.assertEqual(client.phase, "stopped")
        slow = FakeBroker(connack_delay=1.5)
        connected = []
        late = self.make(slow, on_connect=lambda: connected.append(1))
        late.start()
        self.assertTrue(slow.wait_for(lambda: len(slow.connects) == 1))
        started = time.monotonic()
        late.stop()
        self.assertLess(time.monotonic() - started, 1.0)
        time.sleep(2.0)
        self.assertEqual((connected, late.connected), ([], False))

    def test_a_refused_connection_waits_with_a_countdown(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        client = MqttClient("127.0.0.1", port, "gca-test", backoff=(2.0, 2.0))
        self.addCleanup(client.stop)
        self.assertIsNone(client.retry_in())
        client.start()
        deadline = time.monotonic() + 3
        while client.retry_in() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((client.phase, client.last_reason), ("waiting_retry", f"Nothing listening at 127.0.0.1:{port}"))
        self.assertTrue(0 < client.retry_in() <= 2.0)
        client.stop()
        self.assertIsNone(client.retry_in())


class DescribeErrorTests(unittest.TestCase):
    def describe(self, error):
        return describe_error(error, "broker.lan", 1883)

    @staticmethod
    def ssl_error(reason, cls=ssl.SSLError, **fields):
        error = cls(1, f"[SSL: {reason}] failed")
        error.reason = reason
        for name, value in fields.items():
            setattr(error, name, value)
        return error

    def test_every_way_a_connection_fails_has_a_plain_reason(self):
        mismatch = "TLS mismatch: check the port and the TLS switch"
        cases = [(ConnackError(code), text) for code, text in enumerate((
            "Bad protocol version", "Broker rejected the client ID", "Broker unavailable",
            "Wrong username or password", "Not authorised",
            "Broker refused the connection (code 6)"), start=1)]
        cases += [
            (ConnectionRefusedError(111, "Connection refused"), "Nothing listening at broker.lan:1883"),
            (socket.timeout("timed out"), "Broker not reachable (timed out)"),
            (TlsHandshakeTimeout("timed out"), "Broker did not finish the TLS handshake (timed out)"),
            (socket.gaierror(-2, "Name or service not known"), "Broker name not found"),
            (OSError(113, "No route to host"), "Network error: No route to host"),
            (ssl.SSLEOFError(8, "EOF occurred in violation of protocol"), mismatch),
            (self.ssl_error("WRONG_VERSION_NUMBER"), mismatch),
            (self.ssl_error("HTTP_REQUEST"), mismatch),
            (self.ssl_error("SSLV3_ALERT_HANDSHAKE_FAILURE"), "TLS failed: SSLV3_ALERT_HANDSHAKE_FAILURE"),
            (self.ssl_error("CERTIFICATE_VERIFY_FAILED", ssl.SSLCertVerificationError,
                            verify_message="certificate has expired"), "TLS failed: certificate has expired"),
            (MqttError("broker closed the connection"), "Broker closed the connection"),
            (MqttError("keepalive timeout: broker stopped answering"), "Broker stopped answering"),
            (packets.PacketError("bad length"), "Broker sent something that is not MQTT"),
            (ValueError("x"), "ValueError"),
        ]
        for error, expected in cases:
            with self.subTest(error=repr(error)):
                self.assertEqual(self.describe(error), expected)
        self.assertEqual(describe_error(ConnectionRefusedError(), "fd00::5", 8883), "Nothing listening at [fd00::5]:8883")
        self.assertEqual(str(ConnackError(4)), "bad username or password")
        self.assertLessEqual(len(self.describe(self.ssl_error("R" * 200))), 92)


if __name__ == "__main__":
    unittest.main()
