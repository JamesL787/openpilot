"""Phone-side Starpilot Auto session over any socket-compatible byte transport.

StarPilot plays the *phone* role: the head unit sends the version request, then
acts as the TLS client while this side is the TLS server presenting the phone
identity. After authentication the session discovers services, opens the video
channel (and, best effort, the input channel so touches are acknowledged and
discarded, the sensor channel for driving status and night mode, and the Bluetooth
channel with the comma's adapter address, as a phone does) and streams H.264 access units with bounded acknowledgement flow.

Adapted from yummydirtx/openpilot ``tools/android_auto/{session,video,live_session}.py``
(MIT), pinned at 672a16f6183567c0ada53654f8527d97e1a483fa, whose protocol facts
were cross-checked against AACS. Transport-neutral: the donor used USB and the
desktop head unit over TCP; here the transport is the head unit's Wi-Fi TCP port.
"""

from __future__ import annotations

import math
import re
import select
import ssl
import struct
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from openpilot.starpilot.system.starpilot_auto.touch import InputConfig, TouchEvent, TouchMapper, parse_input_config
from openpilot.starpilot.system.starpilot_auto.wire import describe, describe_fields, field, json_fields, one, parse_fields, signed

MAX_MESSAGE = 2 * 1024 * 1024
PHONE_MAX_VERSION = (6, 1)  # protocol version Starpilot Auto 17.6 reports to newer head units
MAX_FRAGMENT_BYTES = 2 * MAX_MESSAGE
FRAGMENT_SIZE = 16000
TRACE_SECONDS, TRACE_MAX_EVENTS = 6.0, 80

FLAG_FIRST = 1
FLAG_LAST = 2
FLAG_CONTROL = 4
FLAG_ENCRYPTED = 8

# Control channel (0) message ids.
MSG_VERSION_REQUEST = 0x01
MSG_VERSION_RESPONSE = 0x02
MSG_SSL_HANDSHAKE = 0x03
MSG_AUTH_COMPLETE = 0x04
MSG_SERVICE_DISCOVERY_REQUEST = 0x05
MSG_SERVICE_DISCOVERY_RESPONSE = 0x06
MSG_CHANNEL_OPEN_REQUEST = 0x07
MSG_CHANNEL_OPEN_RESPONSE = 0x08
MSG_PING_REQUEST = 0x0b
MSG_PING_RESPONSE = 0x0c
MSG_SHUTDOWN_REQUEST = 0x0f
MSG_SHUTDOWN_RESPONSE = 0x10

# Media channel message ids.
AV_MEDIA_WITH_TIMESTAMP = 0x0000
AV_MEDIA_CODEC_CONFIG = 0x0001  # SPS/PPS without a timestamp, sent before the first frame like a phone's MediaCodec
AV_SETUP_REQUEST = 0x8000
AV_START_INDICATION = 0x8001
AV_STOP_INDICATION = 0x8002
AV_SETUP_RESPONSE = 0x8003
AV_MEDIA_ACK = 0x8004
VIDEO_FOCUS_REQUEST = 0x8007
VIDEO_FOCUS_INDICATION = 0x8008

# Sensor channel message ids.
SENSOR_START_REQUEST = 0x8001
SENSOR_START_RESPONSE = 0x8002
SENSOR_EVENT = 0x8003

# Bluetooth channel message ids.
BT_PAIRING_REQUEST = 0x8001
BT_PAIRING_RESPONSE = 0x8002

# Input channel message ids.
INPUT_EVENT = 0x8001
INPUT_BINDING_REQUEST = 0x8002
INPUT_BINDING_RESPONSE = 0x8003

CODEC_H264_BP = 3
SETUP_STATUS_READY = 2
FOCUS_PROJECTED = 1
FOCUS_NATIVE = 2
FOCUS_PROJECTED_NO_INPUT = 4
FOCUS_REASON_USER_SELECTION = 4
SHUTDOWN_REASON_USER_SELECTION = 1
SENSOR_NIGHT_MODE = 10
SENSOR_DRIVING_STATUS = 13
# A phone subscribes to the car's driving status and night mode before projecting. Some head units
# keep the screen until it has: a 2019 Honda Civic (39101-TBA-A510) answered every focus request
# with native focus while only video and input were open.
PHONE_SENSORS = (SENSOR_DRIVING_STATUS, SENSOR_NIGHT_MODE)

RESOLUTIONS = {1: (800, 480), 2: (1280, 720), 3: (1920, 1080)}
# Named in errors and reports only: 1440p, 4K and portrait screens also offer 800x480, which is mandatory.
RESOLUTION_NAMES = {**{index: f"{w}x{h}" for index, (w, h) in RESOLUTIONS.items()}, 4: "2560x1440", 5: "3840x2160",
                    6: "720x1280", 7: "1080x1920", 8: "1440x2560", 9: "2160x3840"}
CODEC_NAMES = {3: "H.264", 5: "VP9", 6: "AV1", 7: "H.265"}
DISPLAY_MAIN = 0  # MediaSinkService.display_type; 1 is the instrument cluster, 2 an auxiliary screen
FRAME_RATES = {1: 60, 2: 30}
# Software H.264 on the comma is the constraint: prefer 720p, then 480p. 1080p
# is accepted only when nothing smaller is offered.
RESOLUTION_PREFERENCE = (2, 1, 3)

# A real phone pings periodically; answering pings is mandatory, sending them
# is harmless and keeps impatient receivers from declaring the link idle.
PING_INTERVAL = 2.0
# Android's TLS 1.2 suites, strongest first. Python's defaults leave out the SHA-1 and static-RSA
# suites that older head-unit stacks need (a Sony XAV-AX3200 offers only TLS_RSA_WITH_AES_128_CBC_SHA).
TLS12_CIPHERS = ":".join((
  "ECDHE-ECDSA-AES128-GCM-SHA256", "ECDHE-RSA-AES128-GCM-SHA256", "ECDHE-ECDSA-AES256-GCM-SHA384",
  "ECDHE-RSA-AES256-GCM-SHA384", "ECDHE-ECDSA-CHACHA20-POLY1305", "ECDHE-RSA-CHACHA20-POLY1305",
  "ECDHE-ECDSA-AES128-SHA", "ECDHE-RSA-AES128-SHA", "ECDHE-ECDSA-AES256-SHA", "ECDHE-RSA-AES256-SHA",
  "AES128-GCM-SHA256", "AES256-GCM-SHA384", "AES128-SHA", "AES256-SHA",
)) + ":@SECLEVEL=1"
# Messages we do not handle are logged with a readable body, but only the first few of each
# kind and then every hundredth, so a head unit repeating one cannot flood the session log.
IGNORED_LOG_FIRST = 5
IGNORED_LOG_EVERY = 100


class AuthenticationRejected(ValueError):
  pass


class PeerRequestedStop(EOFError):
  pass


START_CODE = re.compile(b"\x00\x00(?:\x00)?\x01")


def codec_config(access_unit: bytes) -> bytes:
  """The SPS and PPS NAL units of a keyframe, as Android's codec-config buffer carries them."""
  starts = list(START_CODE.finditer(access_unit))
  units = []
  for index, match in enumerate(starts):
    end = starts[index + 1].start() if index + 1 < len(starts) else len(access_unit)
    if match.end() < end and access_unit[match.end()] & 31 in (7, 8):
      units.append(b"\x00\x00\x00\x01" + access_unit[match.end():end])
  return b"".join(units)


@dataclass(frozen=True)
class VideoMode:
  channel: int
  config_index: int
  width: int
  height: int
  fps: int
  margin_width: int
  margin_height: int

  @property
  def content_width(self) -> int:
    return self.width - self.margin_width

  @property
  def content_height(self) -> int:
    return self.height - self.margin_height

  def as_dict(self) -> dict:
    return {"channel": self.channel, "config_index": self.config_index, "width": self.width, "height": self.height,
            "fps": self.fps, "margin_width": self.margin_width, "margin_height": self.margin_height}


def describe_video_config(config: dict, display_type: int | None = None) -> str:
  """One offered video configuration (parsed fields), e.g. "1280x720 H.264 margins 0x240 (display 1)"."""
  resolution, codec = one(config, 1), one(config, 10, CODEC_H264_BP)
  text = f"{RESOLUTION_NAMES.get(resolution, f'resolution {resolution}')} {CODEC_NAMES.get(codec, f'codec {codec}')}"
  margin_width, margin_height = one(config, 3, 0) or 0, one(config, 4, 0) or 0
  if margin_width or margin_height:
    text += f" margins {margin_width}x{margin_height}"
  if display_type:
    text += f" (display {display_type})"
  return text


def describe_video_configs(channels: list[dict]) -> str:
  """What the head unit offered, for an error a person can act on."""
  offered = [describe_video_config(config, channel.get("display_type"))
             for channel in channels for config in channel.get("video_configs", [])]
  return ", ".join(offered) or "no video"


def choose_video_mode(channels: list[dict]) -> VideoMode:
  """Pick a negotiated H.264 mode on the main display that the software encoder can sustain."""
  candidates = []
  for channel in channels:
    if (channel.get("display_type") or DISPLAY_MAIN) != DISPLAY_MAIN:
      continue  # an instrument-cluster or auxiliary screen, never the one the driver uses
    for index, config in enumerate(channel.get("video_configs", [])):
      resolution = one(config, 1)
      codec = one(config, 10, CODEC_H264_BP)
      if resolution not in RESOLUTIONS or codec != CODEC_H264_BP:
        continue
      width, height = RESOLUTIONS[resolution]
      margin_width, margin_height = int(one(config, 3, 0) or 0), int(one(config, 4, 0) or 0)
      if not (0 <= margin_width < width and 0 <= margin_height < height):
        continue
      fps = FRAME_RATES.get(one(config, 2, 2), 30)
      mode = VideoMode(int(channel["id"]), index, width, height, fps, margin_width, margin_height)
      candidates.append((RESOLUTION_PREFERENCE.index(resolution), fps != 30, index, mode))
  if not candidates:
    raise ValueError(f"Head unit did not advertise a supported H.264 video mode (offered {describe_video_configs(channels)})")
  return min(candidates, key=lambda item: item[:3])[3]


class Session:
  """TLS, framing and control-channel handshake; one instance per TCP connection."""

  def __init__(self, peer, cert: str, key: str, log: Callable[..., None] | None = None, ca: str | None = None, *,
               receive_timeout: float = 3.0, send_timeout: float = 3.0, handshake_timeout: float = 15.0):
    self.peer = peer
    self._log = log
    self.receive_timeout = self._timeout(receive_timeout)
    self.send_timeout = self._timeout(send_timeout)
    self.handshake_timeout = self._timeout(handshake_timeout)
    self.authenticated = False
    self.head_unit_subject: str = ""
    self.incoming = ssl.MemoryBIO()
    self.outgoing = ssl.MemoryBIO()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(TLS12_CIPHERS)
    context.options |= ssl.OP_CIPHER_SERVER_PREFERENCE  # our strongest-first order wins, not the head unit's
    context.load_cert_chain(cert, key)
    self.peer_verification_enabled = ca is not None
    if ca is not None:
      context.load_verify_locations(cafile=ca)
      context.verify_mode = ssl.CERT_REQUIRED
    self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=True)
    self.fragments: dict[int, tuple[int, int, bytearray]] = {}
    self.ignored_counts: dict[tuple[str, int, int], int] = {}
    self.bytes_sent = 0
    self.bytes_received = 0
    self.trace_until = 0.0  # diagnostic window after a focus grant: log every message each way
    self.trace_count = 0

  @staticmethod
  def _timeout(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
      raise ValueError("Message timeout must be finite and positive")
    return value

  def event(self, name: str, **values) -> None:
    if self._log is not None:
      self._log(name, **values)

  def trace(self, direction: str, channel: int, kind: int, data: bytes) -> None:
    """Diagnostic: every message in the TRACE_SECONDS after a focus grant (the Civic drops USB ~3 s into it)."""
    if time.monotonic() < self.trace_until and self.trace_count < TRACE_MAX_EVENTS:
      self.trace_count += 1
      self.event("trace_" + direction, channel=channel, kind=kind, bytes=len(data), head=bytes(data[:24]).hex(),
                 ms=round((self.trace_until - TRACE_SECONDS - time.monotonic()) * -1000))

  def ignored(self, name: str, channel: int, kind: int, data: bytes, **values) -> None:
    """Log a message this side does not act on, rate-limited per (event, channel, kind)."""
    key = (name, channel, kind)
    count = self.ignored_counts[key] = self.ignored_counts.get(key, 0) + 1
    if count <= IGNORED_LOG_FIRST or count % IGNORED_LOG_EVERY == 0:
      self.event(name, channel=channel, kind=kind, count=count, bytes=len(data), message=describe(data), **values)

  # ----------------------------------------------------------------- framing

  def send(self, channel: int, kind: int, body: bytes = b"", encrypted: bool = True, control: bool = False) -> None:
    """Send one whole message within one deadline; the session is invalid on failure."""
    if self.authenticated and not encrypted:
      raise ValueError("Plaintext is forbidden after authentication")
    data = struct.pack(">H", kind) + body
    if len(data) > MAX_MESSAGE:
      raise ValueError("Message exceeds size limit")
    self.trace("tx", channel, kind, body)
    deadline = time.monotonic() + self.send_timeout
    timed_peer = hasattr(self.peer, "gettimeout") and hasattr(self.peer, "settimeout")
    previous_timeout = self.peer.gettimeout() if timed_peer else None
    try:
      for offset in range(0, len(data), FRAGMENT_SIZE):
        chunk = data[offset:offset + FRAGMENT_SIZE]
        flags = (FLAG_FIRST if offset == 0 else 0) | (FLAG_LAST if offset + len(chunk) == len(data) else 0)
        flags |= (FLAG_ENCRYPTED if encrypted else 0) | (FLAG_CONTROL if control else 0)
        if encrypted:
          written = self.tls.write(chunk)
          if written != len(chunk):
            raise ValueError("Incomplete TLS write")
          chunk = self.outgoing.read()
        header = struct.pack(">BBH", channel, flags, len(chunk))
        if flags & 3 == FLAG_FIRST:
          header += struct.pack(">I", len(data))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
          raise TimeoutError("Starpilot Auto message send deadline exceeded")
        if timed_peer:
          self.peer.settimeout(remaining)
        self.peer.sendall(header + chunk)
        self.bytes_sent += len(header) + len(chunk)
        if time.monotonic() >= deadline:
          raise TimeoutError("Starpilot Auto message send deadline exceeded")
    finally:
      if timed_peer:
        self.peer.settimeout(previous_timeout)

  def receive(self, timeout: float | None = None) -> tuple[int, int, bytes]:
    """Read one complete message within one deadline, tolerating partial reads.

    ``timeout`` overrides the default deadline: setup waits give a slow head unit longer than streaming does.
    """
    if timeout is None:
      timeout = self.receive_timeout if self.authenticated else self.handshake_timeout
    deadline = time.monotonic() + max(0.001, timeout)
    timed_peer = hasattr(self.peer, "gettimeout") and hasattr(self.peer, "settimeout")
    previous_timeout = self.peer.gettimeout() if timed_peer else None

    def read_exact(size: int) -> bytes:
      data = bytearray()
      while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
          raise TimeoutError("Starpilot Auto message receive deadline exceeded")
        if timed_peer:
          self.peer.settimeout(remaining)
        chunk = self.peer.recv(size - len(data))
        if not chunk:
          raise EOFError(f"Head unit disconnected after {len(data)}/{size} bytes")
        data.extend(chunk)
      self.bytes_received += size
      return bytes(data)

    try:
      return self._receive_message(read_exact)
    finally:
      if timed_peer:
        self.peer.settimeout(previous_timeout)

  def _receive_message(self, read_exact) -> tuple[int, int, bytes]:
    while True:
      channel, flags, size = struct.unpack(">BBH", read_exact(4))
      if flags & ~15 or size == 0:
        raise ValueError("Invalid frame header")
      if self.authenticated and not flags & FLAG_ENCRYPTED:
        raise ValueError("Plaintext is forbidden after authentication")
      segment = flags & 3
      total = struct.unpack(">I", read_exact(4))[0] if segment == FLAG_FIRST else None
      if total is not None and not 2 <= total <= MAX_MESSAGE:
        raise ValueError("Invalid fragmented message size")
      if total is not None and total + sum(item[0] for item in self.fragments.values()) > MAX_FRAGMENT_BYTES:
        raise ValueError("Aggregate fragmented message limit exceeded")
      payload = read_exact(size)
      if flags & FLAG_ENCRYPTED:
        self.incoming.write(payload)
        plain = bytearray()
        while True:
          try:
            part = self.tls.read(65536)
            if not part:
              raise EOFError("TLS closed")
            plain.extend(part)
          except ssl.SSLWantReadError:
            break
        payload = bytes(plain)
      if segment == 3:
        if channel in self.fragments:
          raise ValueError("Full message interrupted fragment sequence")
      elif segment == FLAG_FIRST:
        if channel in self.fragments or total is None or len(payload) >= total:
          raise ValueError("Invalid first fragment")
        self.fragments[channel] = (total, flags & 12, bytearray(payload))
        continue
      else:
        if channel not in self.fragments:
          raise ValueError("Continuation without first fragment")
        expected, mode, assembled = self.fragments[channel]
        if mode != flags & 12 or len(assembled) + len(payload) > expected:
          raise ValueError("Inconsistent fragment sequence")
        assembled.extend(payload)
        if segment == 0:
          continue
        del self.fragments[channel]
        if len(assembled) != expected:
          raise ValueError("Incorrect assembled message size")
        payload = bytes(assembled)
      if len(payload) < 2:
        raise ValueError("Missing message type")
      kind = struct.unpack(">H", payload[:2])[0]
      return channel, kind, payload[2:]

  # --------------------------------------------------------------- handshake

  def _handshake_message(self, kinds: tuple[int, ...], expected: str) -> tuple[int, bytes]:
    """The next control message of ``kinds``, answering pings and skipping strays within the handshake deadline.

    Some head units ping, or send a message early, between the handshake steps.
    """
    deadline = time.monotonic() + self.handshake_timeout
    while True:
      remaining = deadline - time.monotonic()
      if remaining <= 0:
        raise TimeoutError(f"Head unit did not send {expected}")
      channel, kind, data = self.receive(timeout=remaining)
      if channel == 0 and kind in kinds:
        return kind, data
      if channel == 0 and kind == MSG_PING_REQUEST:
        self.send(0, MSG_PING_RESPONSE, field(1, one(parse_fields(data), 1, 0)), encrypted=self.authenticated)
      elif not (channel == 0 and kind == MSG_PING_RESPONSE):
        self.ignored("handshake_ignored", channel, kind, data, expected=expected)

  def authenticate(self) -> None:
    _, data = self._handshake_message((MSG_VERSION_REQUEST,), "a version request")
    if len(data) != 4:
      raise ValueError(f"Invalid version request ({len(data)} bytes)")
    major, minor = struct.unpack(">HH", data)
    if major < 1:
      raise ValueError(f"Unsupported Starpilot Auto protocol version {major}.{minor}")
    # Starpilot Auto 17.6 answers any request above 1.7 with its own maximum and success;
    # newer head units (e.g. 2025 Honda, 4.1) hang up on anything else.
    reply = (1, min(minor, 5)) if (major, minor) <= (1, 7) else PHONE_MAX_VERSION
    self.event("version", major=major, minor=minor, reply=f"{reply[0]}.{reply[1]}")
    self.send(0, MSG_VERSION_RESPONSE, struct.pack(">HHH", *reply, 0), encrypted=False)
    while True:
      _, data = self._handshake_message((MSG_SSL_HANDSHAKE,), "the TLS handshake")
      self.incoming.write(data)
      done = False
      try:
        self.tls.do_handshake()
        done = True
      except ssl.SSLWantReadError:
        pass
      except ssl.SSLError as error:
        # e.g. NO_SHARED_CIPHER from an old head-unit TLS stack, or a certificate the root does not verify
        self.event("tls_failed", reason=error.reason or "", library=error.library or "", error=str(error)[:200])
        raise
      response = self.outgoing.read()
      if response:
        self.send(0, MSG_SSL_HANDSHAKE, response, encrypted=False)
      if done:
        break
    self.event("tls_established", version=self.tls.version(), cipher=self.tls.cipher()[0])
    if self.peer_verification_enabled:
      peer_cert = self.tls.getpeercert() or {}
      organizations = [value for rdn in peer_cert.get("subject", ()) for name, value in rdn if name == "organizationName"]
      if any(name in ("CarService", "Google Automotive Link") for name in organizations):
        raise ValueError("Head unit presented a phone or CA identity")
      self.head_unit_subject = ", ".join(f"{name}={value}" for rdn in peer_cert.get("subject", ()) for name, value in rdn)
      self.event("head_unit_verified", subject=self.head_unit_subject, expires=peer_cert.get("notAfter", ""))
    _, data = self._handshake_message((MSG_AUTH_COMPLETE,), "the authentication status")
    status = signed(one(parse_fields(data), 1))
    if status is None or not isinstance(status, int):
      raise ValueError("Missing or invalid authentication status")
    if status != 0:
      self.event("authentication_rejected", status=status)
      raise AuthenticationRejected(f"Head unit rejected the phone certificate (status {status})")
    self.authenticated = True
    self.event("authenticated", version=self.tls.version(), cipher=self.tls.cipher()[0])

  def discover(self, device_name: str, device_brand: str) -> list[dict]:
    self.send(0, MSG_SERVICE_DISCOVERY_REQUEST, field(4, device_name) + field(5, device_brand))
    raw = self.wait_for(0, MSG_SERVICE_DISCOVERY_RESPONSE)
    response = parse_fields(raw)
    channels = []
    for descriptor in response.get(1, []):
      if not isinstance(descriptor, bytes):
        continue
      fields = parse_fields(descriptor)
      item: dict = {"id": one(fields, 1), "services": sorted(number for number in fields if number != 1),
                    "descriptor": describe_fields(fields)}
      av = one(fields, 3)
      if isinstance(av, bytes):
        media = parse_fields(av)
        item["media_type"] = one(media, 1)
        item["display_id"], item["display_type"] = one(media, 6), one(media, 7)
        item["video_configs"] = [parse_fields(c) for c in media.get(4, []) if isinstance(c, bytes)]
      if isinstance(one(fields, 4), bytes):
        item["input"] = True
        try:
          item["display_id"] = one(parse_fields(one(fields, 4)), 5)  # the display this input belongs to
        except ValueError:
          pass
        try:
          item["input_config"] = parse_input_config(one(fields, 4))
        except ValueError:
          item["input_config"] = InputConfig()
      sensors = one(fields, 2)
      if isinstance(sensors, bytes):
        try:
          item["sensors"] = [one(parse_fields(sensor), 1) for sensor in parse_fields(sensors).get(1, []) if isinstance(sensor, bytes)]
        except ValueError:
          item["sensors"] = []
      bluetooth = one(fields, 6)
      if isinstance(bluetooth, bytes):
        try:
          item["bluetooth"] = parse_bluetooth_service(bluetooth)
        except (ValueError, IndexError):  # a truncated packed method list
          item["bluetooth"] = {"car_address": "", "pairing_methods": []}
      channels.append(item)
    # Everything but the channel list: make, model, year, software and, on newer units, headunit_info.
    head_unit = redact_head_unit(describe_fields({number: values for number, values in response.items() if number != 1}))
    self.event("discovered", channels=[{k: (json_fields_list(v) if k == "video_configs" else str(v) if k == "input_config" else v)
                                        for k, v in ch.items()} for ch in channels],
               head_unit=head_unit)
    return channels

  def wait_for(self, channel: int, kind: int, timeout: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
      ch, message, data = self.receive(timeout=remaining)
      if ch == channel and message == kind:
        return data
      self.dispatch(ch, message, data, expected=f"{channel}/{kind:#x}")
    raise TimeoutError(f"Head unit did not send {channel}/{kind:#x}")

  def dispatch(self, channel: int, kind: int, data: bytes, expected: str) -> None:
    """Handle a message that arrived while waiting for another one."""
    if channel == 0 and kind == MSG_PING_REQUEST:
      self.send(0, MSG_PING_RESPONSE, field(1, one(parse_fields(data), 1, 0)))
    elif not (channel == 0 and kind == MSG_PING_RESPONSE):
      self.ignored("unexpected_while_waiting", channel, kind, data, expected=expected)


SDR_VEHICLE_ID = 5          # ServiceDiscoveryResponse.vehicle_id
HEAD_UNIT_INFO = 17         # ServiceDiscoveryResponse.headunit_info
HEAD_UNIT_INFO_VEHICLE_ID = 4


def parse_bluetooth_service(data: bytes) -> dict:
  """BluetoothService: the car's adapter address and its pairing methods (packed or not)."""
  fields = parse_fields(data)
  methods: list[int] = []
  for value in fields.get(2, []):
    if isinstance(value, bytes):
      packed = value
      while packed:
        number, size = 0, 0
        while True:
          byte = packed[size]
          number |= (byte & 0x7F) << (7 * size)
          size += 1
          if not byte & 0x80:
            break
        methods.append(number)
        packed = packed[size:]
    else:
      methods.append(value)
  address = one(fields, 1, b"")
  return {"car_address": address.decode(errors="replace") if isinstance(address, bytes) else "", "pairing_methods": methods}


def redact_head_unit(described: dict) -> dict:
  """Drop the vehicle identifier from a described discovery response: logs are shared for diagnosis."""
  if SDR_VEHICLE_ID in described:
    described[SDR_VEHICLE_ID] = ["redacted"]
  for info in described.get(HEAD_UNIT_INFO, []):
    if isinstance(info, dict) and HEAD_UNIT_INFO_VEHICLE_ID in info:
      info[HEAD_UNIT_INFO_VEHICLE_ID] = ["redacted"]
  return described


def json_fields_list(configs: list[dict]) -> list[dict]:
  return [json_fields(config) for config in configs]


class ProjectionSession(Session):
  """Video projection with focus epochs, bounded ACK window and mandatory resume keyframes."""

  # Wi-Fi jitter, plus bursts where this loop itself stalls: the dashcam encoders and the model starting at onroad
  # held it ~1 s on 2026-10-01 while the car kept acking in 27-219 ms. Stays under the 3 s after which a Honda takes
  # its screen back without video.
  ACK_TIMEOUT = 2.5
  ACK_DRAIN_SECONDS = 0.1  # before calling an ACK late, read what already arrived, for at most this long
  MAX_WINDOW = 2

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.channels: list[dict] = []
    self.mode: VideoMode | None = None
    self.window = 1
    self.focused = False
    self.allow_projection = True
    self.media_started = False
    self.needs_keyframe = True
    self.session_id = 1
    self.retired_sessions: deque[int] = deque(maxlen=8)
    self.pending: deque[float] = deque()
    self.unacked = 0
    self.acked = 0
    self.epoch_acked = 0
    self.video_confirmed = False
    self.frames_sent = 0
    self.focus_epoch = 0
    self.max_ack_seconds = 0.0
    self.config_ack_slack = 0  # codec-config messages a head unit may acknowledge like frames
    self.input_channel: int | None = None
    self.sensor_channel: int | None = None
    self.bluetooth_channel: int | None = None
    self.input_events = 0
    self.touch: TouchMapper | None = None
    self.touch_events: deque[TouchEvent] = deque(maxlen=128)
    self.last_ping_sent = 0.0
    self.last_rx = time.monotonic()
    self.ping_responses = 0

  # ------------------------------------------------------------------- setup

  def start(self, device_name: str, device_brand: str, phone_address: str = "") -> VideoMode:
    self.channels = self.discover(device_name, device_brand)
    self.mode = choose_video_mode(self.channels)
    self.open_video()
    self.open_input()
    self.open_sensors()
    self.open_bluetooth(phone_address)
    self.request_projection()
    return self.mode

  def open_video(self) -> None:
    mode = self.mode
    assert mode is not None
    self.send(mode.channel, MSG_CHANNEL_OPEN_REQUEST, field(1, 0) + field(2, mode.channel), control=True)
    opened = parse_fields(self.wait_for(mode.channel, MSG_CHANNEL_OPEN_RESPONSE))
    if signed(one(opened, 1)) != 0:
      raise ValueError(f"Head unit rejected opening the video channel: {json_fields(opened)}")
    self.send(mode.channel, AV_SETUP_REQUEST, field(1, CODEC_H264_BP))
    setup = parse_fields(self.wait_for(mode.channel, AV_SETUP_RESPONSE))
    window = int(one(setup, 2, 0) or 0)
    if one(setup, 1) != SETUP_STATUS_READY or window < 1:  # the window is capped to MAX_WINDOW below; MIB3 offers 100
      raise ValueError(f"Unsupported video setup response: {json_fields(setup)}")
    configs = setup.get(3, [])
    if configs and mode.config_index not in configs:
      raise ValueError(f"Head unit did not accept video configuration {mode.config_index}: {json_fields(setup)}")
    self.window = min(window, self.MAX_WINDOW)
    self.event("video_setup", mode=mode.as_dict(), window=window, used_window=self.window)

  def input_channel_for(self, video_channel: int) -> dict | None:
    """The input service of the display being projected to, matched by display id (unset means the main display).

    A car with a second screen can list that screen's input first. When no input names the
    projected display, the first one not tied to another screen's video is used (else the
    first of all): a guessed touch channel beats none.
    """
    inputs = [channel for channel in self.channels if channel.get("input")]
    video = next((channel for channel in self.channels if channel.get("id") == video_channel), {})
    display = video.get("display_id") or 0
    matched = next((channel for channel in inputs if (channel.get("display_id") or 0) == display), None)
    if matched is not None or not inputs:
      return matched
    other_screens = {channel.get("display_id") or 0 for channel in self.channels
                     if "video_configs" in channel and channel.get("id") != video_channel}
    return next((channel for channel in inputs if (channel.get("display_id") or 0) not in other_screens), inputs[0])

  def open_input(self) -> None:
    """Open the touch/key channel so input is acknowledged; failures are not fatal."""
    assert self.mode is not None
    channel = self.input_channel_for(self.mode.channel)
    if channel is None:
      return  # the head unit has no input service at all
    try:
      self.send(channel["id"], MSG_CHANNEL_OPEN_REQUEST, field(1, 0) + field(2, channel["id"]), control=True)
      opened = parse_fields(self.wait_for(channel["id"], MSG_CHANNEL_OPEN_RESPONSE, timeout=3.0))
      if signed(one(opened, 1)) != 0:
        raise ValueError("channel open rejected")
      self.input_channel = channel["id"]
      config = channel.get("input_config") or InputConfig()
      # Echo the advertised keycodes, as a phone does; touch needs no binding.
      self.send(channel["id"], INPUT_BINDING_REQUEST, b"".join(field(1, code) for code in config.keycodes))
      if self.mode is not None:
        self.touch = TouchMapper(config, self.mode.width, self.mode.height, self.mode.margin_width, self.mode.margin_height)
      video = next((ch for ch in self.channels if ch.get("id") == self.mode.channel), {})
      self.event("input_opened", channel=channel["id"], keycodes=len(config.keycodes),
                 touch=f"{config.touch_width}x{config.touch_height}",
                 display_matched=(channel.get("display_id") or 0) == (video.get("display_id") or 0))
    except (TimeoutError, ValueError) as error:
      self.event("input_unavailable", error=str(error))

  def open_sensors(self) -> None:
    """Subscribe to driving status and night mode like a phone; failures are not fatal."""
    channel = next((channel for channel in self.channels if "sensors" in channel), None)
    if channel is None:
      return  # the head unit has no sensor service
    wanted = [sensor for sensor in PHONE_SENSORS if sensor in channel["sensors"]]
    try:
      self.send(channel["id"], MSG_CHANNEL_OPEN_REQUEST, field(1, 0) + field(2, channel["id"]), control=True)
      opened = parse_fields(self.wait_for(channel["id"], MSG_CHANNEL_OPEN_RESPONSE, timeout=3.0))
      if signed(one(opened, 1)) != 0:
        raise ValueError("channel open rejected")
      self.sensor_channel = channel["id"]
      statuses = {}
      for sensor in wanted:
        self.send(channel["id"], SENSOR_START_REQUEST, field(1, sensor) + field(2, 0))
        statuses[sensor] = signed(one(parse_fields(self.wait_for(channel["id"], SENSOR_START_RESPONSE, timeout=3.0)), 1))
      self.event("sensors_opened", channel=channel["id"], offered=channel["sensors"], started=statuses)
    except (TimeoutError, ValueError) as error:
      self.event("sensors_unavailable", error=str(error))

  def open_bluetooth(self, phone_address: str) -> None:
    """Tell the car which Bluetooth device this is, as a phone does; failures are not fatal.

    A phone sends its adapter address so the car can match the projection to its hands-free
    link. The 2019 Honda Civic lists this service with its own address; it may keep the screen
    until the phone has identified itself.
    """
    channel = next((channel for channel in self.channels if "bluetooth" in channel), None)
    if channel is None:
      return  # the head unit has no Bluetooth service
    service = channel["bluetooth"]
    try:
      self.send(channel["id"], MSG_CHANNEL_OPEN_REQUEST, field(1, 0) + field(2, channel["id"]), control=True)
      opened = parse_fields(self.wait_for(channel["id"], MSG_CHANNEL_OPEN_RESPONSE, timeout=3.0))
      if signed(one(opened, 1)) != 0:
        raise ValueError("channel open rejected")
      self.bluetooth_channel = channel["id"]
      if not phone_address:
        self.event("bluetooth_opened", channel=channel["id"], car_address=service["car_address"],
                   methods=service["pairing_methods"], phone_address="", response=None)
        return
      method = service["pairing_methods"][0] if service["pairing_methods"] else 0
      self.send(channel["id"], BT_PAIRING_REQUEST, field(1, phone_address) + field(2, method))
      response = describe(self.wait_for(channel["id"], BT_PAIRING_RESPONSE, timeout=3.0))
      self.event("bluetooth_opened", channel=channel["id"], car_address=service["car_address"],
                 methods=service["pairing_methods"], phone_address=phone_address, method=method, response=response)
    except (TimeoutError, ValueError) as error:
      self.event("bluetooth_unavailable", error=str(error))

  def request_projection(self) -> None:
    """Ask for display focus; the Mazda donor needed this, DHU grants it unsolicited."""
    assert self.mode is not None
    self.allow_projection = True
    self.send(self.mode.channel, VIDEO_FOCUS_REQUEST, field(2, FOCUS_PROJECTED) + field(3, FOCUS_REASON_USER_SELECTION))

  def dispatch(self, channel: int, kind: int, data: bytes, expected: str) -> None:
    # Once video is set up, an early focus grant or ping must not be lost while
    # waiting for the input channel.
    if self.mode is not None and not (channel == 0 and kind in (MSG_VERSION_REQUEST, MSG_SSL_HANDSHAKE)):
      self.handle(channel, kind, data)
    else:
      super().dispatch(channel, kind, data, expected)

  # --------------------------------------------------------------- streaming

  def pump(self, timeout: float) -> bool:
    """Handle at most one incoming message; returns True when one was handled."""
    now = time.monotonic()
    if self.authenticated and now - self.last_ping_sent >= PING_INTERVAL:
      self.last_ping_sent = now
      self.send(0, MSG_PING_REQUEST, field(1, time.monotonic_ns() // 1000))
    if not select.select([self.peer], [], [], max(0.0, timeout))[0]:
      return False
    self.handle(*self.receive())
    self.last_rx = time.monotonic()
    return True

  def handle(self, channel: int, kind: int, data: bytes) -> None:
    try:
      fields = parse_fields(data) if kind not in (AV_MEDIA_WITH_TIMESTAMP, 1) else {}
    except ValueError:
      fields = {}  # non-protobuf payload on a channel this sender never opened
    mode = self.mode
    self.trace("rx", channel, kind, data)
    if channel == 0:
      if kind == MSG_PING_REQUEST:
        self.send(0, MSG_PING_RESPONSE, field(1, one(fields, 1, 0)))
      elif kind == MSG_PING_RESPONSE:
        self.ping_responses += 1
      elif kind == MSG_SHUTDOWN_REQUEST:
        self.send(0, MSG_SHUTDOWN_RESPONSE)
        self.event("peer_requested_shutdown", reason=one(fields, 1))
        raise PeerRequestedStop(f"Head unit ended projection (reason {one(fields, 1)})")
      else:
        self.ignored("control_ignored", channel, kind, data)
    elif mode is not None and channel == mode.channel:
      if kind == VIDEO_FOCUS_INDICATION:
        self._handle_focus(one(fields, 1), one(fields, 2, 0))
      elif kind == AV_MEDIA_ACK:
        self._handle_ack(one(fields, 1), int(one(fields, 2, 0) or 0))
      else:
        self.ignored("video_ignored", channel, kind, data)
    elif channel == self.input_channel:
      if kind == INPUT_EVENT:
        self.input_events += 1
        if self.touch is not None and self.focused:
          try:
            self.touch_events.extend(self.touch.decode(data))
          except ValueError as error:
            self.event("input_invalid", error=str(error))
      elif kind == INPUT_BINDING_RESPONSE:
        self.event("input_bound", status=signed(one(fields, 1, 0)))
      else:
        self.ignored("input_ignored", channel, kind, data)
    elif channel == self.sensor_channel:
      # Driving status and night mode updates; logged (rate-limited) for diagnosis, not acted on.
      self.ignored("sensor_event" if kind == SENSOR_EVENT else "sensor_ignored", channel, kind, data)
    elif channel == self.bluetooth_channel:
      # Pairing follow-ups (authentication data, a late response); the comma is already paired over BlueZ.
      self.ignored("bluetooth_ignored", channel, kind, data)
    else:
      self.ignored("channel_ignored", channel, kind, data)

  def _handle_focus(self, focus, unsolicited) -> None:
    was_focused = self.focused
    granted = focus in (FOCUS_PROJECTED, FOCUS_PROJECTED_NO_INPUT)
    self.focused = granted and self.allow_projection
    self.event("video_focus", focus=focus, unsolicited=unsolicited, focused=self.focused)
    if was_focused and not self.focused and self.touch is not None:
      self.touch_events.extend(self.touch.reset())
    if self.focused and not was_focused:
      assert self.mode is not None
      if self.media_started:
        # A new media epoch: retire in-flight frames from the previous one so
        # late ACKs are harmless, and never continue an old inter-frame chain.
        self.retired_sessions.append(self.session_id)
        self.session_id += 1
        self.unacked = 0
        self.pending.clear()
        self.config_ack_slack = 0
        self.epoch_acked = 0
      self.media_started = True
      self.needs_keyframe = True
      self.focus_epoch += 1
      self.trace_until, self.trace_count = time.monotonic() + TRACE_SECONDS, 0
      self.send(self.mode.channel, AV_START_INDICATION, field(1, self.session_id) + field(2, self.mode.config_index))

  def _handle_ack(self, sid, count: int) -> None:
    if sid in self.retired_sessions:
      return
    # Head units may acknowledge codec config like a frame: under the current
    # session (as an extra count) or, like the DHU, under session 0.
    if sid != self.session_id and 0 < count <= self.config_ack_slack:
      self.config_ack_slack -= count
      self._confirm_video()
      return
    excess = count - self.unacked
    if sid == self.session_id and 0 < excess <= self.config_ack_slack:
      self.config_ack_slack -= excess
      count -= excess
      if count == 0:
        self._confirm_video()
        return
    if sid != self.session_id or not 0 < count <= self.unacked or count > len(self.pending):
      raise ValueError(f"Invalid video acknowledgement session={sid} count={count} pending={self.unacked}")
    now = time.monotonic()
    for _ in range(count):
      self.max_ack_seconds = max(self.max_ack_seconds, now - self.pending.popleft())
    self.unacked -= count
    self.acked += count
    self.epoch_acked += count
    self._confirm_video()

  def _confirm_video(self) -> None:
    # Same-session ACKs do not distinguish configuration from frames. Until the
    # optional configuration ACKs are accounted for, use the conservative lower
    # bound on acknowledged frames without changing flow-control credit.
    if not self.video_confirmed and self.epoch_acked > self.config_ack_slack:
      self.video_confirmed = True
      self.event("video_acknowledged", session=self.session_id, ack_ms=round(self.max_ack_seconds * 1000))

  def can_send(self) -> bool:
    return self.focused and self.unacked < self.window

  def _ack_overdue(self, now: float) -> bool:
    return bool(self.focused and self.pending and now - self.pending[0] > self.ACK_TIMEOUT)

  def check_progress(self, now: float | None = None) -> None:
    measured = now is None
    now = time.monotonic() if measured else now
    if self._ack_overdue(now):
      # ACKs that arrived while this loop was busy (a slow encode, a CPU burst) still sit in the socket; the
      # streaming loop drains only a bounded batch per pass, so read what is there before calling the car silent.
      deadline = time.monotonic() + self.ACK_DRAIN_SECONDS
      while time.monotonic() < deadline and self.pump(0.0):
        pass
      if measured:
        now = time.monotonic()
      if self._ack_overdue(now):
        raise TimeoutError(f"Video acknowledgement older than {self.ACK_TIMEOUT:.1f} s")
    # Only a receiver known to answer pings can be declared dead by silence; for
    # others a lost link surfaces as a socket error or a dropped Wi-Fi lease.
    if self.ping_responses and now - self.last_rx > 15.0:
      raise TimeoutError("Head unit stopped answering for 15 s")

  def send_frame(self, data: bytes, timestamp_us: int, *, keyframe: bool) -> None:
    if not self.can_send():
      raise RuntimeError("Cannot send without video focus and window credit")
    if self.needs_keyframe and not keyframe:
      raise ValueError("A fresh media epoch must start with SPS/PPS and an IDR frame")
    assert self.mode is not None
    if self.needs_keyframe:
      config = codec_config(data)
      if config:
        self.send(self.mode.channel, AV_MEDIA_CODEC_CONFIG, config)
        self.config_ack_slack += 1
    self.send(self.mode.channel, AV_MEDIA_WITH_TIMESTAMP, struct.pack(">Q", timestamp_us) + data)
    self.needs_keyframe = False
    self.pending.append(time.monotonic())
    self.unacked += 1
    self.frames_sent += 1

  def shutdown(self, timeout: float = 2.0) -> None:
    self.send(0, MSG_SHUTDOWN_REQUEST, field(1, SHUTDOWN_REASON_USER_SELECTION))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
      if not select.select([self.peer], [], [], 0.05)[0]:
        continue
      channel, kind, data = self.receive()
      if channel == 0 and kind == MSG_SHUTDOWN_RESPONSE:
        self.event("shutdown_acknowledged")
        return
      if channel == 0 and kind == MSG_SHUTDOWN_REQUEST:
        self.send(0, MSG_SHUTDOWN_RESPONSE)
        return
      if self.mode is not None and channel == self.mode.channel and kind in (VIDEO_FOCUS_INDICATION, AV_MEDIA_ACK):
        continue
      if channel == 0 and kind == MSG_PING_REQUEST:
        self.send(0, MSG_PING_RESPONSE, field(1, one(parse_fields(data), 1, 0)))
    raise TimeoutError("Head unit did not acknowledge shutdown")

  def stats(self) -> dict:
    return {"frames_sent": self.frames_sent, "frames_acked": self.acked, "pending": self.unacked,
            "focus_epoch": self.focus_epoch, "focused": self.focused, "max_ack_ms": round(self.max_ack_seconds * 1000),
            "input_events": self.input_events, "touch": self.touch is not None}
