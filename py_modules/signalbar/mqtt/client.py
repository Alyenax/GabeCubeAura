"""A small MQTT 3.1.1 client: one connection, QoS 0, keepalive, last will and automatic reconnect."""

from __future__ import annotations

import os
import select
import socket
import ssl
import threading
import time

from . import packets

SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/certs/ca-bundle.crt",
)


class MqttError(Exception):
    pass


class TlsHandshakeTimeout(TimeoutError):
    """TCP connected but the TLS handshake did not finish in time (still a TimeoutError)."""


class ConnackError(MqttError):
    """The broker answered CONNECT with a refusal (MQTT 3.1.1 return codes 1-5)."""

    def __init__(self, code):
        super().__init__(packets.CONNACK_ERRORS.get(code, f"connection refused ({code})"))
        self.code = code


# The settings page's words for each CONNACK refusal (last_error keeps packets.CONNACK_ERRORS' text).
CONNACK_REASONS = {
    1: "Bad protocol version",
    2: "Broker rejected the client ID",
    3: "Broker unavailable",
    4: "Wrong username or password",
    5: "Not authorised",
}
# What OpenSSL reports when the other end is not speaking TLS (plain MQTT on a TLS client, or the reverse).
_TLS_MISMATCH_REASONS = {"UNEXPECTED_EOF_WHILE_READING", "WRONG_VERSION_NUMBER", "HTTP_REQUEST", "UNKNOWN_PROTOCOL",
                         "RECORD_LAYER_FAILURE"}
_MQTT_REASONS = {
    "broker closed the connection": "Broker closed the connection",
    "no answer from broker": "Broker did not answer (timed out)",
    "keepalive timeout: broker stopped answering": "Broker stopped answering",
}


def describe_error(error, host, port) -> str:
    """Why a connection attempt failed, in plain English, for the settings page. Host and port are
    what the user typed there; no error raised here can carry the password."""
    where = f"[{host}]:{port}" if ":" in str(host) else f"{host}:{port}"
    if isinstance(error, ConnackError):
        return CONNACK_REASONS.get(error.code, f"Broker refused the connection (code {error.code})")
    if isinstance(error, ssl.SSLError):  # before OSError: SSLError is one
        if not isinstance(error, ssl.SSLCertVerificationError) and (
                isinstance(error, ssl.SSLEOFError) or getattr(error, "reason", None) in _TLS_MISMATCH_REASONS):
            return "TLS mismatch: check the port and the TLS switch"
        detail = getattr(error, "verify_message", None) or getattr(error, "reason", None) or type(error).__name__
        return f"TLS failed: {str(detail)[:80]}"
    if isinstance(error, socket.gaierror):
        return "Broker name not found"
    if isinstance(error, ConnectionRefusedError):
        return f"Nothing listening at {where}"
    if isinstance(error, TlsHandshakeTimeout):
        return "Broker did not finish the TLS handshake (timed out)"
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "Broker not reachable (timed out)"
    if isinstance(error, packets.PacketError):
        return "Broker sent something that is not MQTT"
    if isinstance(error, MqttError):
        text = str(error)
        return _MQTT_REASONS.get(text) or (text[:1].upper() + text[1:80] if text else "MQTT error")
    if isinstance(error, OSError):
        return f"Network error: {(error.strerror or type(error).__name__)[:80]}"
    return type(error).__name__


def _tls_context():
    # Decky's bundled OpenSSL may not find SteamOS's roots; add them explicitly,
    # never disabling verification (same reasoning as providers/weather.py).
    context = ssl.create_default_context()
    for bundle in SYSTEM_CA_BUNDLES:
        if os.path.isfile(bundle):
            try:
                context.load_verify_locations(cafile=bundle)
            except (OSError, ssl.SSLError):
                continue
    return context


class MqttClient:
    def __init__(self, host, port=1883, client_id="gabecubeaura", *, username="", password="",
                 keepalive=30, will=None, tls=False, on_connect=None, on_message=None, logger=None,
                 connect_timeout=10.0, backoff=(2.0, 300.0)):
        self.host, self.port, self.client_id = host, int(port), client_id
        self._username, self._password = username, password
        self.keepalive = max(1, int(keepalive))
        self._will, self._tls = will, bool(tls)
        self._on_connect, self._on_message = on_connect, on_message
        self.log = logger
        self._connect_timeout = connect_timeout
        self._backoff = backoff
        self._topics = []
        self._packet_id = 0
        self._sock = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.connected = False
        self.connected_once = False
        self.last_error = ""
        # For the settings page: the phase ("idle" before start, "connecting", "connected",
        # "waiting_retry", "stopped"), why the last attempt failed in plain English ("" once connected),
        # and when the next attempt starts while waiting (see retry_in).
        self.phase = "idle"
        self.last_reason = ""
        self._retry_at = None
        self.messages_out = 0

    # ---- public API ----------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gabecubeaura-mqtt", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        sock = self._sock
        if sock is not None and self.connected:
            try:
                with self._send_lock:
                    sock.sendall(packets.DISCONNECT_PACKET)
            except OSError:
                pass
        self._abort()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def retry_in(self):
        """Seconds until the next connection attempt while waiting after a failure, else None."""
        at = self._retry_at
        return None if at is None else max(0.0, at - time.monotonic())

    def subscribe(self, topic):
        if topic not in self._topics:
            self._topics.append(topic)
            if self.connected:
                try:
                    self._send(packets.subscribe(self._next_id(), [topic]))
                except (OSError, MqttError):
                    # The topic is queued; the next CONNACK replays it. Recycle the connection.
                    self._abort()

    def publish(self, topic, payload, retain=False) -> bool:
        if not self.connected:
            return False
        try:
            self._send(packets.publish(topic, payload, retain))
        except (OSError, MqttError, packets.PacketError):
            self._abort()
            return False
        self.messages_out += 1
        return True

    # ---- connection loop -----------------------------------------------
    def _run(self):
        delay = self._backoff[0]
        while not self._stop.is_set():
            self.phase = "connecting"
            try:
                self._session()
                delay = self._backoff[0]
            except (OSError, ssl.SSLError, packets.PacketError, MqttError) as error:
                if not self._stop.is_set():
                    self.last_error = str(error) or type(error).__name__
                    self.last_reason = describe_error(error, self.host, self.port)
            except Exception as error:  # noqa: BLE001 - nothing may end the connection thread
                if not self._stop.is_set():
                    self.last_error = f"{type(error).__name__}: {error}"
                    self.last_reason = describe_error(error, self.host, self.port)
                    if self.log:
                        self.log.warning(f"[GabeCubeAura] MQTT loop error: {self.last_error}")
            finally:
                self._close()
            if self._stop.is_set():
                break
            self._retry_at = time.monotonic() + delay
            self.phase = "waiting_retry"
            stopped = self._stop.wait(delay)
            self._retry_at = None
            if stopped:
                break
            delay = min(delay * 2, self._backoff[1])
        self._retry_at = None
        self.phase = "stopped"

    def _session(self):
        sock = socket.create_connection((self.host, self.port), timeout=self._connect_timeout)
        if self._stop.is_set():
            sock.close()
            raise MqttError("stopped")
        if self._tls:
            try:
                sock = _tls_context().wrap_socket(sock, server_hostname=self.host)
            except (socket.timeout, TimeoutError) as error:
                sock.close()
                raise TlsHandshakeTimeout(str(error)) from error
        sock.settimeout(self._connect_timeout)
        self._sock = sock
        reader = packets.Reader()
        self._send(packets.connect(self.client_id, self.keepalive, self._username, self._password, self._will))
        deadline = time.monotonic() + self._connect_timeout
        while True:
            if time.monotonic() > deadline:
                raise MqttError("no answer from broker")
            if self._stop.is_set():
                raise MqttError("stopped")
            # Poll in short slices so stop() ends a pending handshake promptly.
            if not select.select([sock], [], [], 0.25)[0]:
                continue
            data = sock.recv(4096)
            if not data:
                raise MqttError("broker closed the connection")
            found = [p for p in reader.feed(data) if p[0] == packets.CONNACK]
            if found:
                code = found[0][2][1] if len(found[0][2]) > 1 else 3
                if code:
                    raise ConnackError(code)
                break
        if self._stop.is_set():
            raise MqttError("stopped")
        self.connected = True
        self.connected_once = True
        self.phase, self.last_reason = "connected", ""
        # last_error is deliberately kept across a successful reconnect: it records why the
        # previous connection ended; callers read it only while `connected` is False.
        if self._topics:
            self._send(packets.subscribe(self._next_id(), list(self._topics)))
        self._call(self._on_connect)
        last_ping = time.monotonic()
        waiting_since = None
        while not self._stop.is_set():
            ready, _, _ = select.select([sock], [], [], 0.25)
            now = time.monotonic()
            if ready:
                data = sock.recv(65536)
                if not data:
                    raise MqttError("broker closed the connection")
                for kind, flags, body in reader.feed(data):
                    if kind == packets.PINGRESP:
                        waiting_since = None
                    elif kind == packets.PUBLISH:
                        topic, payload, retain, qos, packet_id = packets.parse_publish(flags, body)
                        if qos == 1 and packet_id is not None:
                            self._send(packets.puback(packet_id))
                        self._call(self._on_message, topic, payload, retain)
            if waiting_since is not None and now - waiting_since > self.keepalive:
                raise MqttError("keepalive timeout: broker stopped answering")
            if waiting_since is None and now - last_ping >= self.keepalive / 2:
                self._send(packets.PINGREQ_PACKET)
                last_ping = waiting_since = now

    # ---- helpers -------------------------------------------------------
    def _send(self, data):
        sock = self._sock
        if sock is None:
            raise MqttError("not connected")
        with self._send_lock:
            sock.sendall(data)

    def _next_id(self):
        self._packet_id = self._packet_id % 0xFFFF + 1
        return self._packet_id

    def _abort(self):
        # Callable from any thread: shutdown() wakes the loop's select/recv (EOF), and the loop
        # thread then does the teardown. Never close() the socket from a non-loop thread: its
        # fileno becomes -1 under the loop's feet and select() raises ValueError.
        self.connected = False
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass

    def _close(self):
        # Loop thread only: stop() never calls this; it _abort()s and the loop's finally closes the socket.
        self.connected = False
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _call(self, callback, *args):
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as error:  # noqa: BLE001 - a bridge bug must not kill the connection
            if self.log:
                self.log.warning(f"[GabeCubeAura] MQTT callback failed: {type(error).__name__}: {error}")
