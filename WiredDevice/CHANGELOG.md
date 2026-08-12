# Changelog

## 0.2.0

Adds a FrameLink endpoint, so WireTAP can treat this host as a device rather
than a generic adapter.

### Added

- **FrameLink endpoint.** Turn on *Enable FrameLink endpoint* and restart. The
  add-on serves its interfaces on port 120, with microsecond timestamps and
  interfaces that identify themselves. In WireTAP, add a **framelink** IO
  profile pointing at this host and press *Re-probe*.
- GVRET and FrameLink can run **at the same time**, each with its own toggle.
  They listen on separate ports and each receives its own copy of every frame.

### Changed

- The two servers are now supervised individually. If one stops it is restarted
  on its own, instead of taking the whole add-on down with it.
- `gvret_can_fd` and `gvret_log_level` are now **`can_fd`** and **`log_level`**,
  shared by both servers. CAN FD describes the bus, not the protocol serving it.
  Both were off or default, so there is nothing to re-enter.

## 0.1.0

Adds an optional GVRET interface, so the CAN bus can be polled live from
WireTAP or SavvyCAN rather than only configured.

Supersedes 0.0.21 to 0.0.24, which were same-day development releases.

### Added

- **GVRET server.** Turn on *Enable GVRET server* and restart. Every configured
  interface is bridged to TCP, with `can0` as bus 0, `can1` as bus 1 and so on.
  Point WireTAP at `<home-assistant-host>:23`. There is no discovery broadcast,
  so the host and port have to be entered.
- **Forwarding to a WireTAP gateway.** Frames can be archived to a backend
  gateway as well as bridged live. Frames are cached to `/data` while the
  gateway is unreachable and drain in order once it returns.
- **CAN FD support**, for payloads up to 64 bytes, where the interface allows it.
- A changelog and documentation, both of which render in the add-on UI.

### Changed

- The configuration tab now shows a readable name and a line of help for every
  option, instead of the bare key.
- Option types now match their values, so bitrates and pin numbers are number
  fields, `can0` and `can1` are toggles, and the controller is a dropdown.
  Existing settings are carried over.
- New icon.

### Fixed

- **The add-on could not be rebuilt.** The Supervisor no longer supplies a
  default base image to add-ons without a build configuration, so the build
  failed at `FROM` with an unknown error. The base images are now named
  explicitly for each architecture. Any update attempted before this release
  would have failed the same way.

### Upgrading

Turn **Watchdog** on if you enable GVRET. Without it, a server that stops is
not restarted, and the add-on stays stopped along with it.
