#!/usr/bin/env python3

#
# SocketCAN to TCP FrameLink endpoint
#
# (c) 2026 Wired Square Pty Ltd
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software
# and associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial
# portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

"""FrameLink device endpoint bridging SocketCAN interfaces to a TCP client.

FrameLink devices are servers: the device listens on port 120 and the client
(WireTAP, framelink-cli) dials in. This serves the add-on's CAN interfaces as
though they were the interfaces of a FrameLink device.

Protocol 4. The codec follows wslib-rs crates/wslib-framelink-protocol/docs/
framelink.md and crates/wslib-framing/docs/cobs.md, which are normative — the
wire-format.md in ws-framelink is behind and disagrees with them.
"""

import argparse
import errno
import logging
import select
import signal
import socket
import struct
import sys
import time

log = logging.getLogger("framelink")

# Protocol ---------------------------------------------------------------

PROTOCOL_VERSION = 4
HEADER_SIZE = 5

MSG_PING = 0x01
MSG_PONG = 0x02
MSG_CAPABILITIES_REQ = 0x03
MSG_CAPABILITIES_RESP = 0x04
MSG_ACK = 0x05
MSG_NACK = 0x06
MSG_FRAME_RX = 0x10
MSG_FRAME_TX = 0x11
MSG_STREAM_START = 0x12
MSG_STREAM_STOP = 0x13
MSG_FRAME_TX_BATCH = 0x14
MSG_DSIG_LIST = 0x60
MSG_DSIG_LIST_RESP = 0x61

# total, offset, count: a device with no signals of its own
EMPTY_DSIG_LIST = bytes(6)

FLAG_NONE = 0x00
FLAG_ACK_REQ = 0x01
FLAG_RESPONSE = 0x02
FLAG_ERROR = 0x04

ERR_UNKNOWN_TYPE = 0x01
ERR_INVALID_PAYLOAD = 0x02
ERR_INVALID_INTERFACE = 0x05
ERR_VERSION = 0x0C

IFACE_CAN = 0x01
IFACE_CANFD = 0x02

META_BOARD_NAME = 0x01
META_BOARD_REVISION = 0x02
META_DEVICE_ID = 0x03

QTY_STRING = 0x11

# FrameLink CAN metadata flags
CAN_FLAG_EXTENDED = 0x01
CAN_FLAG_FD = 0x02
CAN_FLAG_BRS = 0x04
CAN_FLAG_RTR = 0x08

# SocketCAN --------------------------------------------------------------

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x000007FF

SOL_CAN_RAW = 101
CAN_RAW_FD_FRAMES = 5
CANFD_BRS = 0x01

SO_TIMESTAMP = getattr(socket, "SO_TIMESTAMP", 29)
SCM_TIMESTAMP = SO_TIMESTAMP

CAN_FRAME_SIZE = 16
CANFD_FRAME_SIZE = 72

#
# Per-frame layouts, compiled once. These sit in the hot path, so they are
# Struct objects rather than format strings re-looked-up on every call.
#
CAN_META_LEN = 6
_CAN_META = struct.Struct("<IBB")                # can_id, dlc, flags
_ENTRY_HDR = struct.Struct("<QBB" + "IBB" + "H")  # entry header through data_len
_U16 = struct.Struct("<H")
_CAN_HDR = struct.Struct("<IB")                  # can_id, length. Data follows at offset 8
_CANFD_HDR = struct.Struct("<IBB")               # can_id, length, flags

# struct timeval is two longs, so 16 bytes on 64-bit and 8 on armv7
_TIMEVAL = struct.Struct("<qq") if struct.calcsize("@l") == 8 else struct.Struct("<ll")
_ANC_SIZE = socket.CMSG_SPACE(_TIMEVAL.size) if hasattr(socket, "CMSG_SPACE") else 64

# How long RX frames are accumulated before a batch is flushed, and the most
# that go in one message. FRAME_RX is a batch format; one message per CAN
# frame would waste most of the wire.
BATCH_WINDOW = 0.005
MAX_BATCH = 128


class FrameError(Exception):
    """Malformed frame on the wire."""


class VersionMismatch(FrameError):
    """Well-formed frame of another protocol version, answered with NACK VERSION."""

    def __init__(self, version, seq):
        super().__init__("unsupported protocol version %d" % version)
        self.seq = seq


def cobs_encode(data):
    """COBS-encode data. The result never contains a 0x00 byte.

    Copies whole runs between zeros rather than walking byte by byte, since
    this sits in the per-frame path on hardware where that matters.
    """

    out = bytearray()
    pos = 0
    end = len(data)

    while True:
        zero = data.find(0, pos)
        run_end = end if zero == -1 else zero

        # A code byte spans at most 254 data bytes, so long runs are split
        while run_end - pos >= 0xFE:
            out.append(0xFF)
            out += data[pos:pos + 0xFE]
            pos += 0xFE

        out.append(run_end - pos + 1)
        out += data[pos:run_end]

        if zero == -1:
            return out

        pos = zero + 1


def cobs_decode(data):
    """COBS-decode data back to the original bytes."""

    if not data:
        raise FrameError("cobs: empty input")

    out = bytearray()
    i = 0
    n = len(data)

    while i < n:
        code = data[i]
        i += 1

        if code == 0:
            raise FrameError("cobs: zero code byte")

        end = i + code - 1
        if end > n:
            raise FrameError("cobs: truncated group")
        out += data[i:end]
        i = end

        # A non-maximal group implies a zero, except at the very end
        if code < 0xFF and i < n:
            out.append(0x00)

    return bytes(out)


def build_frame(msg_type, flags, seq, payload=b""):
    """Build a complete wire frame, COBS-encoded between 0x00 delimiters."""

    raw = bytearray()
    raw.append((PROTOCOL_VERSION << 4) | (flags & 0x0F))
    raw.append(msg_type)
    raw.append(seq)
    raw += _U16.pack(len(payload))
    raw += payload

    out = bytearray(b"\x00")
    out += cobs_encode(raw)
    out.append(0x00)

    return out


def parse_frame(cobs_data):
    """Parse one COBS-encoded frame body into (flags, msg_type, seq, payload)."""

    decoded = cobs_decode(cobs_data)

    if len(decoded) < HEADER_SIZE:
        raise FrameError("frame shorter than header")

    seq = decoded[2]

    version = (decoded[0] >> 4) & 0x0F
    if version != PROTOCOL_VERSION:
        raise VersionMismatch(version, seq)

    flags = decoded[0] & 0x0F
    msg_type = decoded[1]
    (length,) = _U16.unpack_from(decoded, 3)

    actual = len(decoded) - HEADER_SIZE
    if length != actual:
        raise FrameError("length mismatch: header %d, actual %d" % (length, actual))

    return flags, msg_type, seq, decoded[HEADER_SIZE:HEADER_SIZE + length]


class Deframer:
    """Splits a TCP byte stream into COBS frame bodies on 0x00 delimiters.

    Runs of delimiters and frames sharing a delimiter are both tolerated,
    matching the client's deframer.
    """

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf.extend(data)

    def next_frame(self):
        while True:
            end = self.buf.find(0x00)
            if end == -1:
                return None

            chunk = bytes(self.buf[:end])
            del self.buf[:end + 1]

            # An empty chunk is a run of delimiters; keep looking
            if chunk:
                return chunk


def meta_tlv(meta_id, quantity, value):
    """Encode one metadata TLV: id(u8) quantity(u8) len(u8) value."""

    return bytes([meta_id, quantity, len(value)]) + value


def build_capabilities(device_id, board_name, board_revision, interfaces):
    """Build a CAPABILITIES_RESP payload.

    num_device_meta(u8) [meta...]
    num_interfaces(u8)  [index(u8) type(u8) num_meta(u8) [meta...]] * N
    num_peripherals(u8) [...]
    """

    device_meta = []

    for meta_id, value in (
        (META_BOARD_NAME, board_name),
        (META_BOARD_REVISION, board_revision),
        (META_DEVICE_ID, device_id),
    ):
        if value:
            device_meta.append(meta_tlv(meta_id, QTY_STRING, value.encode()[:255]))

    out = bytearray()
    out.append(len(device_meta))
    for entry in device_meta:
        out.extend(entry)

    out.append(len(interfaces))
    for index, iface_type in interfaces:
        out.extend([index, iface_type, 0])

    # No peripherals
    out.append(0)

    return bytes(out)


def build_frame_rx(entries):
    """Build a FRAME_RX payload. Always batch-shaped, even for one frame."""

    buf = bytearray(_U16.pack(len(entries)))

    for timestamp_us, iface_index, can_id, dlc, flags, data in entries:
        buf += _ENTRY_HDR.pack(
            timestamp_us, iface_index, CAN_META_LEN, can_id, dlc, flags, len(data)
        )
        buf += data

    return buf


def parse_frame_entry(payload, offset, with_timestamp):
    """Parse one frame entry, returning (iface_index, metadata, data, offset).

    FRAME_TX entries carry a timestamp field, which the client writes as zero.
    FRAME_TX_BATCH entries omit it entirely.
    """

    try:
        if with_timestamp:
            offset += 8

        iface_index = payload[offset]
        meta_len = payload[offset + 1]
        offset += 2

        meta = payload[offset:offset + meta_len]
        offset += meta_len

        (data_len,) = _U16.unpack_from(payload, offset)
        offset += 2

        data = payload[offset:offset + data_len]
        offset += data_len

        if len(data) != data_len:
            raise FrameError("truncated frame data")
    except (IndexError, struct.error) as err:
        raise FrameError("truncated frame entry") from err

    return iface_index, meta, data, offset


class CanInterface:
    """One SocketCAN interface exposed as a FrameLink interface index."""

    def __init__(self, name, index, can_fd):
        self.name = name
        self.index = index
        self.can_fd = can_fd
        self.frame_size = CANFD_FRAME_SIZE if can_fd else CAN_FRAME_SIZE

        self.sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMP, 1)

        if can_fd:
            self.sock.setsockopt(SOL_CAN_RAW, CAN_RAW_FD_FRAMES, 1)

        self.sock.bind((name,))
        self.sock.setblocking(False)

    @property
    def iface_type(self):
        return IFACE_CANFD if self.can_fd else IFACE_CAN

    def fileno(self):
        return self.sock.fileno()

    def drain(self):
        """Discard anything already queued, so a new stream starts fresh."""

        while True:
            try:
                self.sock.recv(self.frame_size)
            except OSError:
                return

    def receive(self):
        """Read one frame, returning (timestamp_us, can_id, dlc, flags, data).

        Returns None for error frames and anything unparseable, so a caller
        draining the socket can skip them and keep going. Lets OSError through
        instead: BlockingIOError means the socket is empty, and any other
        error should end the drain rather than spin on it.
        """

        frame, ancdata, _flags, _addr = self.sock.recvmsg(self.frame_size, _ANC_SIZE)

        timestamp_us = _timestamp_from(ancdata)

        # Frame size is fixed when the socket is opened, so the layout is known
        if len(frame) == CANFD_FRAME_SIZE:
            can_id, length, fd_flags = _CANFD_HDR.unpack_from(frame)
            is_fd = True
        elif len(frame) == CAN_FRAME_SIZE:
            can_id, length = _CAN_HDR.unpack_from(frame)
            fd_flags = 0
            is_fd = False
        else:
            return None

        if can_id & CAN_ERR_FLAG:
            return None

        flags = 0
        if can_id & CAN_EFF_FLAG:
            flags |= CAN_FLAG_EXTENDED
        if can_id & CAN_RTR_FLAG:
            flags |= CAN_FLAG_RTR
        if is_fd:
            flags |= CAN_FLAG_FD
            if fd_flags & CANFD_BRS:
                flags |= CAN_FLAG_BRS

        arb_id = can_id & (CAN_EFF_MASK if can_id & CAN_EFF_FLAG else CAN_SFF_MASK)

        # Slice the payload straight out of the frame, rather than unpacking
        # the whole fixed-size data field and then trimming it
        payload = frame[8:8 + length]

        return timestamp_us, arb_id, length, flags, payload

    def transmit(self, can_id, dlc, flags, data):
        """Write a frame to the bus."""

        extended = bool(flags & CAN_FLAG_EXTENDED)
        raw_id = can_id & (CAN_EFF_MASK if extended else CAN_SFF_MASK)

        if extended:
            raw_id |= CAN_EFF_FLAG
        if flags & CAN_FLAG_RTR:
            raw_id |= CAN_RTR_FLAG

        if self.can_fd:
            fd_flags = CANFD_BRS if flags & CAN_FLAG_BRS else 0
            # can_id, len, flags, then the two reserved bytes, then 64 of data
            frame = (_CANFD_HDR.pack(raw_id, len(data), fd_flags) + b"\x00\x00"
                     + data[:64].ljust(64, b"\x00"))
        else:
            # can_id, dlc, then three pad bytes, then 8 of data
            frame = _CAN_HDR.pack(raw_id, len(data)) + b"\x00\x00\x00" + data[:8].ljust(8, b"\x00")

        self.sock.send(frame)


def _timestamp_from(ancdata):
    """Extract the kernel SO_TIMESTAMP in microseconds.

    Falls back to the wall clock when the ancillary data is missing, which
    costs a little accuracy under load but never fails.
    """

    for level, ctype, value in ancdata:
        if level == socket.SOL_SOCKET and ctype == SCM_TIMESTAMP and len(value) >= _TIMEVAL.size:
            sec, usec = _TIMEVAL.unpack_from(value)
            return sec * 1_000_000 + usec

    return time.time_ns() // 1000


class FrameLinkServer:
    """Serves the configured CAN interfaces to a single FrameLink client."""

    def __init__(self, ifaces, host, port, device_id, board_name, board_revision, can_fd):
        self.host = host
        self.port = port
        self.device_id = device_id

        self.interfaces = [CanInterface(name, i, can_fd) for i, name in enumerate(ifaces)]
        self.by_index = {iface.index: iface for iface in self.interfaces}

        self.capabilities = build_capabilities(
            device_id,
            board_name,
            board_revision,
            [(iface.index, iface.iface_type) for iface in self.interfaces],
        )

        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, port))

        # FrameLink devices accept exactly one client
        self.listener.listen(1)

        self.streams = set()
        self.pending = []

    def run(self):
        log.info(
            "FrameLink endpoint on %s:%d serving %s as %s",
            self.host,
            self.port,
            ", ".join("%s=bus%d" % (i.name, i.index) for i in self.interfaces),
            self.device_id,
        )

        while True:
            conn, addr = self.listener.accept()
            log.info("Client connected from %s:%d", addr[0], addr[1])

            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            try:
                self._serve(conn)
            except (ConnectionError, OSError) as err:
                log.info("Client error: %s", err)
            finally:
                conn.close()

                # Reset stream state so a reconnecting client re-arms
                self.streams.clear()
                self.pending.clear()
                log.info("Client disconnected")

    def _serve(self, conn):
        deframer = Deframer()
        last_flush = time.monotonic()

        while True:
            readable = [conn] + [self.by_index[i] for i in self.streams]

            #
            # Only wait on the batch window when there is something to flush.
            # Otherwise block until a socket is actually ready, so an idle
            # connection costs nothing. The window is measured from the last
            # flush, so a frame arriving late in a window is not delayed by a
            # further full window.
            #
            if self.pending:
                timeout = max(0.0, BATCH_WINDOW - (time.monotonic() - last_flush))
            else:
                timeout = None

            ready, _, _ = select.select(readable, [], [], timeout)

            for source in ready:
                if source is conn:
                    if not self._read_client(conn, deframer):
                        return
                else:
                    self._drain(source)

            if self.pending and (
                len(self.pending) >= MAX_BATCH or time.monotonic() - last_flush >= BATCH_WINDOW
            ):
                self._flush(conn)
                last_flush = time.monotonic()

    def _read_client(self, conn, deframer):
        """Consume whatever the client sent. Returns False once it hangs up."""

        data = conn.recv(4096)
        if not data:
            return False

        deframer.feed(data)

        while True:
            body = deframer.next_frame()
            if body is None:
                return True

            try:
                _flags, msg_type, seq, payload = parse_frame(body)
            except VersionMismatch as err:
                # Our version in the header is what lets a host's probe_version() read it
                log.warning("Refusing frame: %s", err)
                self._nack(conn, err.seq, ERR_VERSION)
                continue
            except FrameError as err:
                log.warning("Dropping malformed frame: %s", err)
                continue

            self._dispatch(conn, msg_type, seq, payload)

    def _drain(self, source):
        """Read everything queued on an interface, not just one frame.

        A busy bus delivers far more frames than select wakeups, so reading
        one per wakeup would spend most of the time in syscalls.
        """

        while len(self.pending) < MAX_BATCH:
            try:
                frame = source.receive()
            except OSError:
                # Empty socket, or an error worth backing off from
                return

            # None is a frame worth skipping, not an empty socket
            if frame is None:
                continue

            timestamp_us, can_id, dlc, can_flags, payload = frame
            self.pending.append((timestamp_us, source.index, can_id, dlc, can_flags, payload))

    def _flush(self, conn):
        batch, self.pending = self.pending, []
        conn.sendall(build_frame(MSG_FRAME_RX, FLAG_NONE, 0, build_frame_rx(batch)))

    def _send(self, conn, msg_type, flags, seq, payload=b""):
        conn.sendall(build_frame(msg_type, flags, seq, payload))

    def _ack(self, conn, seq):
        self._send(conn, MSG_ACK, FLAG_RESPONSE, seq)

    def _nack(self, conn, seq, error):
        self._send(conn, MSG_NACK, FLAG_RESPONSE | FLAG_ERROR, seq, bytes([error]))

    def _dispatch(self, conn, msg_type, seq, payload):
        if msg_type == MSG_PING:
            self._send(conn, MSG_PONG, FLAG_RESPONSE, seq)

        elif msg_type == MSG_CAPABILITIES_REQ:
            self._send(conn, MSG_CAPABILITIES_RESP, FLAG_RESPONSE, seq, self.capabilities)

        elif msg_type == MSG_STREAM_START:
            if not payload:
                self._nack(conn, seq, ERR_INVALID_PAYLOAD)
                return

            index = payload[0]
            iface = self.by_index.get(index)
            if iface is None:
                self._nack(conn, seq, ERR_INVALID_INTERFACE)
                return

            # Any filter config is ignored; we stream promiscuously
            iface.drain()
            self.streams.add(index)
            log.info("Streaming %s as bus %d", iface.name, index)
            self._ack(conn, seq)

        elif msg_type == MSG_STREAM_STOP:
            if not payload:
                self._nack(conn, seq, ERR_INVALID_PAYLOAD)
                return

            self.streams.discard(payload[0])
            self._ack(conn, seq)

        elif msg_type in (MSG_FRAME_TX, MSG_FRAME_TX_BATCH):
            self._transmit(conn, msg_type, seq, payload)

        elif msg_type == MSG_DSIG_LIST:
            self._send(conn, MSG_DSIG_LIST_RESP, FLAG_RESPONSE, seq, EMPTY_DSIG_LIST)

        else:
            # Includes BOARD_DEF_DOWNLOAD, the other device signal messages and the rule engine.
            # The client treats a NACK as "unsupported" and carries on.
            self._nack(conn, seq, ERR_UNKNOWN_TYPE)

    def _transmit(self, conn, msg_type, seq, payload):
        batch = msg_type == MSG_FRAME_TX_BATCH

        try:
            if batch:
                (count,) = _U16.unpack_from(payload, 0)
                offset = 2
            else:
                count = 1
                offset = 0

            for _ in range(count):
                index, meta, data, offset = parse_frame_entry(payload, offset, not batch)

                iface = self.by_index.get(index)
                if iface is None:
                    self._nack(conn, seq, ERR_INVALID_INTERFACE)
                    return

                if len(meta) != CAN_META_LEN:
                    self._nack(conn, seq, ERR_INVALID_PAYLOAD)
                    return

                can_id, dlc, can_flags = _CAN_META.unpack(meta)
                iface.transmit(can_id, dlc, can_flags, data)
        except (FrameError, struct.error) as err:
            log.warning("Bad transmit request: %s", err)
            self._nack(conn, seq, ERR_INVALID_PAYLOAD)
            return
        except OSError as err:
            log.warning("Transmit failed: %s", err)
            self._nack(conn, seq, ERR_INVALID_INTERFACE)
            return

        self._ack(conn, seq)


def build_parser():
    ap = argparse.ArgumentParser(description="SocketCAN to TCP FrameLink endpoint")

    ap.add_argument("-i", "--iface", default="can0",
        help="CAN interface(s), comma-separated. Order sets the bus index (default: can0)")
    ap.add_argument("--host", default="0.0.0.0",
        help="Listen address")
    ap.add_argument("-p", "--port", type=int, default=120,
        help="Listen port (default: 120)")
    ap.add_argument("--device-id", default=None,
        help="Device identity reported to clients (default: hostname)")
    ap.add_argument("--board-name", default="Wired Square Device CAN",
        help="Board name reported to clients")
    ap.add_argument("--board-revision", default="",
        help="Board revision reported to clients")
    ap.add_argument("--can-fd", action="store_true",
        help="Serve the interfaces as CAN FD, for 64 byte payloads")
    ap.add_argument("--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)")

    return ap.parse_args()


def main():
    args = build_parser()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ifaces = [name for name in args.iface.split(",") if name.strip()]
    if not ifaces:
        log.error("No CAN interfaces configured")
        sys.exit(2)

    device_id = args.device_id or socket.gethostname()

    try:
        server = FrameLinkServer(
            ifaces=ifaces,
            host=args.host,
            port=args.port,
            device_id=device_id,
            board_name=args.board_name,
            board_revision=args.board_revision,
            can_fd=args.can_fd,
        )
    except PermissionError:
        log.error("Permission denied. Raw CAN sockets need CAP_NET_RAW.")
        sys.exit(1)
    except OSError as err:
        if err.errno == errno.ENODEV:
            log.error("No such CAN interface: %s", args.iface)
        else:
            log.error("Startup failed: %s", err)
        sys.exit(1)

    try:
        server.run()
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
