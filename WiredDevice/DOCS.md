# Wired Square Device CAN

Configures CAN interfaces on Home Assistant OS, and optionally exposes them to
[WireTAP](https://github.com/Wired-Square/WireTAP) over GVRET or FrameLink.

## CAN interface

On a Raspberry Pi the add-on patches `config.txt` with the MCP2515 device tree
overlays, then brings each interface up with the configured bitrate.

Patching the kernel config requires **protection mode to be disabled**. Turn it
off, start the add-on once, reboot, then turn protection back on — the overlay
persists.

| Option | Description |
| --- | --- |
| `bitrate` | CAN bus bitrate, in bits per second |
| `restart-ms` | Auto-restart delay after a bus-off condition |
| `tx_queue_length` | Transmit queue length |
| `can_controller` | CAN controller type. Currently `mcp2515` |
| `can0` / `can1` | Enable the overlay for that interface |
| `can0_oscillator` / `can1_oscillator` | Crystal frequency of the controller |
| `can0_interrupt` | GPIO pin used for the interrupt |
| `can1_interrupt` | GPIO pin used for the interrupt |

## GVRET

Set `gvret` to `true` to run a GVRET server that bridges every configured CAN
interface to TCP, so WireTAP or SavvyCAN can poll the bus live.

| Option | Default | Description |
| --- | --- | --- |
| `gvret` | `false` | Run the GVRET server |
| `gvret_port` | `23` | TCP port to listen on |
| `gvret_bus_offset` | `0` | Bus number of the first interface |

`can_fd` and `log_level` are shared by both servers, since they describe the bus
and the add-on rather than either protocol.

Interfaces are enumerated automatically and numbered in order, so `can0`
becomes bus 0 and `can1` becomes bus 1, plus `gvret_bus_offset`. Keep
`gvret_bus_offset` plus the interface count at 15 or below — GVRET carries the
bus number in a single nibble.

### Connecting

There is no discovery broadcast, so point the client at the Home Assistant host
explicitly:

```
<home-assistant-ip>:23
```

To check the server without a client, the GVRET handshake is `E7 E7`, after
which a keepalive is answered with `F1 09 DE AD`:

```bash
printf '\xE7\xE7\xF1\x09' | nc -w2 <home-assistant-ip> 23 | xxd
```

## FrameLink

Set `framelink` to `true` to serve the interfaces as a FrameLink device. This is
the richer option: microsecond timestamps, batched frames, and interfaces that
identify themselves, so WireTAP treats the host as a device rather than a
generic adapter.

| Option | Default | Description |
| --- | --- | --- |
| `framelink` | `false` | Serve the interfaces as a FrameLink device |
| `framelink_port` | `120` | TCP port to listen on |
| `framelink_device_id` | | Name reported to clients. Blank uses the host name |

In WireTAP, add an IO profile of kind **framelink**, set the host to the Home
Assistant address and the port to 120, then press **Re-probe**. The interfaces
and device name fill in from the device itself, and each interface becomes a
bus: `can0` is bus 0, `can1` is bus 1.

Only **one client at a time** can be connected, which matches how the hardware
behaves. GVRET and FrameLink can both be enabled at once; they listen on
separate ports and each gets its own copy of every frame.

## Recording frames

Beyond live bridging, frames can be archived to a WireTAP backend gateway. Set
`forward` to `true` — the GVRET bridge keeps working either way.

| Option | Default | Description |
| --- | --- | --- |
| `forward` | `false` | Push frames to a WireTAP backend gateway |
| `forward_host` | | Gateway address |
| `forward_port` | `9323` | Gateway ingest port |
| `forward_api_key` | | API key with the `ingest` role |
| `forward_database` | | Capture database. Empty uses the gateway default |

Frames are buffered to `/data/wiretap-cache.db` when the gateway is
unreachable, and drain in order once it returns.

Only the gateway is supported as a destination. Writing to PostgreSQL directly
is deliberately not offered: it would put database credentials on the Home
Assistant host, whereas an API key limits this add-on to ingest.

## Troubleshooting

Both servers have a control tool that can be run from the add-on console:

```bash
gvret-util showconf       # current configuration, with secrets masked
gvret-util args           # the arguments the server will be started with
framelink-util showconf   # the same, for the FrameLink endpoint
framelink-util args
```

If the log reports no CAN interfaces, the controller has not come up — check
`can-util enum` and the CAN options above.
