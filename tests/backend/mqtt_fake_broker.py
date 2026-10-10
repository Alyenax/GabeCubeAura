"""Stand-ins for MQTT tests: a one-client broker on a socket, and a client for the bridge."""

from __future__ import annotations

import socket
import struct
import threading
import time

from signalbar.mqtt import packets


class FakeBroker:
    def __init__(self, username="", password="", answer_pings=True, connack_delay=0.0):
        self.username, self.password = username, password
        self.answer_pings, self.connack_delay = answer_pings, connack_delay
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.server.settimeout(0.1)
        self.port = self.server.getsockname()[1]
        self.connects, self.published, self.subscribed = [], [], []
        self.disconnects = 0
        self.connection = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                self.connection, _ = self.server.accept()
                with self.connection:
                    self._handle(self.connection)
            except OSError:
                pass  # no client yet, or it went away mid-reply

    def _handle(self, conn):
        reader = packets.Reader()
        conn.settimeout(0.1)
        while not self._stop.is_set():
            try:
                data = conn.recv(65536)
            except socket.timeout:
                continue
            if not data:
                return
            for kind, flags, body in reader.feed(data):
                if kind == packets.CONNECT:
                    info = self._parse_connect(body)
                    self.connects.append(info)
                    self._stop.wait(self.connack_delay)
                    ok = not self.username or (info["username"], info["password"]) == (self.username, self.password)
                    conn.sendall(b"\x20\x02\x00" + (b"\x00" if ok else b"\x04"))
                    if not ok:
                        return
                elif kind == packets.PUBLISH:
                    self.published.append(packets.parse_publish(flags, body)[:3])
                elif kind == packets.SUBSCRIBE:
                    size = struct.unpack(">H", body[2:4])[0]
                    self.subscribed.append(body[4:4 + size].decode())
                    conn.sendall(b"\x90\x03" + body[:2] + b"\x00")
                elif kind == packets.PINGREQ and self.answer_pings:
                    conn.sendall(b"\xd0\x00")
                elif kind == packets.DISCONNECT:
                    self.disconnects += 1

    @staticmethod
    def _parse_connect(body):
        def read(pos):
            size = struct.unpack(">H", body[pos:pos + 2])[0]
            return body[pos + 2:pos + 2 + size].decode(), pos + 2 + size
        flags = body[7]  # after the protocol name and level
        info = {"will_topic": "", "will_message": "", "username": "", "password": "", "will_retain": bool(flags & 0x20)}
        info["client_id"], pos = read(10)
        for flag, keys in ((0x04, ("will_topic", "will_message")), (0x80, ("username",)), (0x40, ("password",))):
            for key in keys if flags & flag else ():
                info[key], pos = read(pos)
        return info

    def send(self, data: bytes):
        self.connection.sendall(data)

    def drop(self):
        if self.connection:
            self.connection.close()

    def wait_for(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def close(self):
        self._stop.set()
        self.drop()
        # Join before closing the listening socket, or the next test's socket can reuse
        # the fd and this thread accepts (and drops) that test's connection.
        self._thread.join(timeout=2.0)
        self.server.close()


class FakeClient:
    """What MqttBridge sees of MqttClient; go_online() plays the broker's CONNACK."""

    instances = []

    def __init__(self, host, port, client_id, **kwargs):
        self.kwargs = kwargs
        self.connected = self.connected_once = self.stopped = False
        self.last_error, self.messages_out = "", 0
        self.published, self.subscriptions = [], []
        FakeClient.instances.append(self)

    def start(self):
        pass

    def stop(self):
        self.stopped, self.connected = True, False

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, retain=False):
        if self.connected:
            self.published.append((topic, payload, retain))
        return self.connected

    def go_online(self):
        self.connected = self.connected_once = True
        self.kwargs["on_connect"]()

    def receive(self, topic, payload, retain=False):
        self.kwargs["on_message"](topic, payload, retain)

    def payloads(self, topic):
        return [p for t, p, r in self.published if t == topic]
