# `dfrobot_mmwave` — DFRobot SEN0395 / SEN0609 / SEN0610 mmWave radars

One ESPHome external component for the three DFRobot 24 GHz presence radars. They share the
Leapmmw "JYSJ" command-line firmware, so a single hub with a per-model *dialect table* drives all of
them over UART, plus the radar's OUT pin where it has one.

| | SEN0395 | SEN0609 (C4001 25 m) | SEN0610 (C4001 12 m) |
|---|---|---|---|
| UART baud (must match) | 115200 | 9600 | 9600 |
| Presence pin | yes (IO2) | yes (OUT) | **no** |
| Working modes | presence | presence / speed-and-distance | presence / speed-and-distance |
| Targets | up to 8 (`$JYRPO`) | 1 in speed mode (`$DFDMD`) | 1 in speed mode |

Design and protocol reference: `claude/dfrobot-mmwave-implementation-plan.md` in the espHome project.

## How settings work

* **The radar is the source of truth.** Nothing is written at boot. After a start-up read, every setting
  entity shows what the radar reports.
* A change from Home Assistant is shown immediately (optimistic). 750 ms after the last change the
  component runs one transaction for everything changed so far (dragging a slider gives one flash write;
  changes made while a transaction runs go into the next one):
  `sensorStop` → `set…` → `saveConfig` → `sensorStart` (`sensorStart 1` on C4001, which keeps the
  presence state) → `get…` for everything it changed.
* Every read-back value is published. If the radar kept something else (it limits, rounds or rejects a
  value) the entity shows the radar's value and `last_error` says `requested X, radar reports Y`. If the
  transaction could not finish (no reply), the entity reverts to the last confirmed value.
* `last_error` holds the most recent problem until the next read or transaction that finishes cleanly,
  which sets it to an empty string. A failed transaction or a lost link leaves the message in place.
* A bare `Error` (or `no parameter has changed`) to `saveConfig` is not reported when every setting was read
  back and no `set` command failed: the radar answers that way when nothing changed (for example a value the
  radar clamps to what it already stores). A clamped value is still reported as `requested X, radar
  reports Y`. `sensor is not stopped` to `saveConfig` is always an error.
* A change that fails because the link dropped (no reply to `sensorStop`, for example) is not retried after
  the link comes back: the recovery read shows the radar's value again and `last_error` says what failed.
* After a lost link, or when a `sensorStop` went unanswered, the component sends `sensorStart` once the radar
  answers again, unless the **Running** switch was turned off. A C4001 that still sends no reports shortly
  after a read (with UART reports enabled) is also started once.
* **Work mode (C4001).** The presence and speed-and-distance modes are separate firmware apps, each with its
  own settings (range, for example) and its own software version string. A `work_mode` change is never
  combined with other changes: the component sends `sensorStop` → `setRunApp N`, waits for the first report
  of the new app (up to 3 s) and then reads everything again, including the version strings. `setRunApp`
  restarts the radar and keeps the choice without `saveConfig`. Other changes made at the same time are
  applied afterwards, to the new app. The radar cannot be asked which app runs, so the mode comes from the
  reports: `$DFDMD` means speed; a running radar that prints nothing for 3 s (after a switch, or at the end of a
  start-up or recovery read) is in the presence app, since the speed app is never silent. This is what gives
  `work_mode` a value when `uart_presence_report` is off.
* **Settings are per app on the C4001.** `min_range` / `max_range` and `led` keep separate values in the
  presence and speed apps. `trigger_range`, the sensitivities, the latencies, `inhibit_time` and the UART output
  settings (`uart_presence_report`, `uart_report_period`) exist only in the presence app;
  `speed_micro_motion` and `speed_threshold_factor` only in the speed app. A mode switch reads the new app's
  values; nothing is copied across.
* Settings of the other work mode are not read and cannot be set: the C4001 answers `Error` to them. Setting one
  of the UART output settings in speed mode reverts the entity and sets `last_error` to
  `uart output settings are presence-mode only`.
* In the speed app the radar answers `sensor stopped already` / `sensor started already` to `sensorStop` /
  `sensorStart 1` even when the state changes; both count as success, and settings changes and `saveConfig`
  work there as in the presence app.
* Number limits are the ones the firmware keeps (measured on a SEN0609 where they differ from the datasheet).
  A value outside them is refused before anything is sent, and the entity reverts. The min-below-max range
  check is the backstop when `min_range` is raised above a low `max_range`; its message names the reverted
  entity.
* Settings are read at start-up, after a link recovery and after a work-mode change; there is no periodic
  read. The **Reread radar settings** button (`refresh`) reads everything again, with a brief stop on a radar
  that only answers `get` commands while stopped.
* The component never changes the baud rate, OUT-pin polarity or OUT PWM, and never sends
  `resetSystem 1`.

## Configuration

```yaml
external_components:
  - source: github://igiannakas/esphome@dfrobot_mmwave
    components: [dfrobot_mmwave]

uart:
  id: radar_uart
  tx_pin: GPIO17        # ESP TX -> radar RX (D/T)
  rx_pin: GPIO16        # ESP RX <- radar TX (C/R)
  baud_rate: 9600       # 115200 for SEN0395; checked against the model

dfrobot_mmwave:
  id: radar
  uart_id: radar_uart
  model: SEN0609        # SEN0395 | SEN0609 | SEN0610 (required)
  presence_pin: GPIO19  # optional; omit on the SEN0610 or when OUT is not wired
  # target_timeout: 2s  # no target report for this long -> no target
```

`presence_pin` takes a bare pin; it defaults to an input with a pull-down (plain input on the ESP8266, which
has no pull-downs except GPIO16), so a disconnected wire reads as "no presence". The full pin schema
(`number`, `mode`, `inverted`) still works. The OUT pin is a push-pull output of the radar, so it is not
debounced; add binary-sensor filters if you want a delay.

Fixed internally: 3 s boot delay, a `getSWV` ping after 30 s without any data, NaN for "no target".

There is deliberately **no settings block in YAML**: settings live in the radar's flash and are changed
from Home Assistant or with `dfrobot_mmwave.set_parameter`.

### Entities

Every key is optional and takes the usual entity options. Using a key on a model that lacks it is a
config error. Every entity has a default name, so `key: {}` is enough; a `name:` of your own overrides it.

**Mode** is the C4001 work mode in which the entity has a value (the SEN0395 has only one mode). In the other
mode the C4001 answers `Error`, so number, select and sensor entities show *unknown*. A switch of the other
mode (for example `speed_micro_motion` in presence mode) is shown with its last value, because the native API
has no unknown state for a switch; changing it there is rejected with a `last_error`.

| Platform | Key | Mode | SEN0395 | SEN0609 | SEN0610 | Notes |
|---|---|---|:-:|:-:|:-:|---|
| binary_sensor | `occupancy` | both | ✓ | ✓ | ✓ | pin OR UART; see [How occupancy works](#how-occupancy-works) |
| | `uart_occupancy` | both | ✓ | ✓ | ✓ | the UART source alone; *unknown* while stale |
| | `out_pin_occupancy` | both | ✓ | ✓ | ✗ | the pin alone; needs `presence_pin` |
| | `link_ok` | both | ✓ | ✓ | ✓ | diagnostics; `status` and the `running` switch show whether the radar runs |
| number | `min_range` | both | 0–9.45 m, step 0.15 | 0–26 m | 0–12 m | SEN0395 rounds down to 0.15 m; C4001 presence app keeps ≥ 0.3 m |
| | `max_range` | both | 0–9.45 m, step 0.15 | 2.4–26 m | 2.4–12 m | each C4001 app keeps its own range; 26 m is the speed app's maximum |
| | `trigger_range` | presence | ✗ | 2.4–25 m | 2.4–12 m | not limited to max − min by the firmware |
| | `sensitivity` | both | 0–9 | ✗ | ✗ | |
| | `hold_sensitivity`, `trigger_sensitivity` | presence | ✗ | 0–9 | 0–9 | |
| | `on_latency` | presence | 0–100 s | 0–2 s, step 0.01 | 0–2 s, step 0.01 | |
| | `off_latency` | presence | 0.5–1500 s | 2–1500 s, step 0.5 | 2–1500 s, step 0.5 | box |
| | `inhibit_time` | presence | ✗ | 0.1–60 s | 0.1–60 s | |
| | `speed_threshold_factor` | speed | ✗ | 0–65535 | 0–65535 | box; default name "Speed mode threshold factor" |
| | `uart_report_period` | presence | 0.025–1500 s | probe, 0.2–1500 s | probe, 0.2–1500 s | box; keep-alive interval of the on-change reports |
| select | `work_mode` | both | ✗ | ✓ | ✓ | `presence` / `speed_and_distance` |
| switch | `running` | both | ✓ | ✓ | ✓ | `sensorStart`/`sensorStop`, not persisted by the radar |
| | `led` | both | ✓ | probe | probe | on = blink once a second while running (factory state), off = dark; default name "LED" |
| | `speed_micro_motion` | speed | ✗ | ✓ | ✓ | default name "Speed mode micro motion" |
| | `uart_presence_report` | presence | ✓ | probe | probe | |
| | `uart_target_report` | both | ✓ | ✗ | ✗ | enables `$JYRPO` |
| button | `refresh`, `restart`, `factory_reset` | both | ✓ | ✓ | ✓ | default names "Reread radar settings", "Restart radar", "Factory reset radar" |
| sensor | `target_count`, `target_1_distance` | speed (C4001) | ✓ | ✓ | ✓ | C4001: *unknown* in presence mode |
| | `target_1_snr`, `target_2..8_distance`, `target_2..8_snr` | — | ✓ | ✗ | ✗ | slot *i* = the radar's own target index |
| | `target_1_speed`, `target_1_energy` | speed | ✗ | ✓ | ✓ | speed is signed: positive moves away, negative approaches; energy has no unit or range |
| text_sensor | `software_version`, `hardware_version`, `status`, `last_error` | both | ✓ | ✓ | ✓ | |

**probe** = allowed in YAML; the component asks the radar at boot and the entity stays *unknown* if
the firmware does not support it (the config dump says which). The question is asked again on every
start-up read and link recovery.

Numbers with a wide range default to a text box (`box` in the notes) and the others to a slider; the
entity's own `mode:` option overrides this.

`status` is one of `boot_wait`, `probing`, `reading`, `applying`, `running`, `stopped`, `link_lost`,
`unsupported_firmware` (old SEN0395 firmware with the `detRangeCfg` command set: presence still works,
settings are read-only).

Speed-mode `$DFDMD` reports arrive about ten times a second; throttle the target sensors (see the first
example) if Home Assistant history gets too busy (values are already de-duplicated).

### How occupancy works

`occupancy` is on when either source reports presence and off when every source that is live reports
absence. The OUT pin is live whenever `presence_pin` is configured. The UART source is live while reports
keep arriving: `$DFHPD` / `$JYBSS` in presence mode (needs `uart_presence_report` on), `$DFDMD` in speed mode
(presence = at least one target, none after `target_timeout`). With no report for 3 × `uart_report_period`
+ 1 s (4 s in speed mode) the UART source goes stale and drops out, so a dead link or a stopped radar cannot
hold occupancy on; the component's own settings changes pause that clock. With no live source at all,
`occupancy` is *unknown*. With `uart_presence_report` off the radar sends no presence reports, so only the
pin counts; without a pin, `occupancy` then stays *unknown* by design.

The component reports on change: the radar prints a line on every presence transition, and
`uart_report_period` only sets the keep-alive line between them. A radar still in periodic (or passive) mode
from its factory settings or another tool is logged once at boot and switched to on-change the first time a
UART setting (`uart_report_period`, `uart_presence_report`, `uart_target_report`) is changed.

### Factory defaults

| Setting | SEN0395 (manual) | SEN0609 (measured, presence app) |
|---|---|---|
| `min_range` / `max_range` | 0 / 6 m | 0.6 / 6 m |
| `trigger_range` | ✗ | 6 m |
| `sensitivity` | 7 | ✗ |
| `hold_sensitivity` / `trigger_sensitivity` | ✗ | 7 / 5 |
| `on_latency` / `off_latency` | 0.025 / 15 s | 0.05 / 15 s |
| `inhibit_time` | ✗ | 1 s |
| `led` | on (blink) | on (blink) |

The SEN0610 is expected to match the SEN0609 within its 12 m range. The speed app has its own range
(0–26 m on the SEN0609) and its own `led` value. The factory reset (`resetCfg`) was measured to restore the
presence app's values; whether it also resets the speed app's has not been checked.

### Actions

```yaml
- dfrobot_mmwave.refresh: radar          # clears unapplied changes and re-reads everything
- dfrobot_mmwave.restart: radar          # resetSystem 0, then re-probe
- dfrobot_mmwave.factory_reset: radar    # resetCfg + saveConfig + start + read-back
- dfrobot_mmwave.set_parameter:
    id: radar
    parameter: max_range                 # any setting key from the table above
    value: !lambda "return 4.5;"         # selects/switches take the option index / 0|1
```

## Examples

SEN0609 on a Wemos D1 mini32 (OUT on GPIO19):

```yaml
esp32:
  board: wemos_d1_mini32
  framework: {type: arduino}

uart:
  id: radar_uart
  tx_pin: GPIO17
  rx_pin: GPIO16
  baud_rate: 9600

dfrobot_mmwave:
  id: radar
  model: SEN0609
  presence_pin: GPIO19

binary_sensor:
  - platform: dfrobot_mmwave
    occupancy: {}
    link_ok: {}
number:
  - platform: dfrobot_mmwave
    max_range: {}
    trigger_range: {}
    hold_sensitivity: {}
    trigger_sensitivity: {}
    off_latency: {}
select:
  - platform: dfrobot_mmwave
    work_mode: {}
switch:
  - platform: dfrobot_mmwave
    led: {}
sensor:
  - platform: dfrobot_mmwave
    target_1_distance:
      filters: [throttle: 500ms]
    target_1_speed:
      filters: [throttle: 500ms]
    target_1_energy:
      filters: [throttle: 500ms]
text_sensor:
  - platform: dfrobot_mmwave
    software_version: {}
    status: {}
    last_error: {}
button:
  - platform: dfrobot_mmwave
    refresh: {}
```

SEN0395 (115200 baud) on an ESP8266 D1 mini using the hardware UART:

```yaml
logger:
  baud_rate: 0          # UART0 belongs to the radar

uart:
  id: radar_uart
  tx_pin: GPIO1
  rx_pin: GPIO3
  baud_rate: 115200
  rx_buffer_size: 512   # target reports (up to 9 lines per cycle) overflow the default buffer

dfrobot_mmwave:
  id: radar
  model: SEN0395
  presence_pin: GPIO14  # radar IO2

sensor:
  - platform: dfrobot_mmwave
    target_count: {}
    target_1_distance: {}
switch:
  - platform: dfrobot_mmwave
    uart_target_report: {}
```

SEN0610 (no OUT pin) — occupancy comes from the UART report only:

```yaml
dfrobot_mmwave:
  id: radar
  model: SEN0610

binary_sensor:
  - platform: dfrobot_mmwave
    occupancy: {}
```

## Things still to confirm on hardware

The firmware behaviours below are not settled by the datasheets. The component does not guess: it
probes at boot or takes the safe option, and logs the outcome.

Confirmed on a SEN0609 (bench, 2026-09-16), firmware `JYSJ_00.00.04.040220` (presence app) /
`JYSJ_01.00.08.240220` (speed app), hardware `JYSJ_428_A01_H`:

* Echo is on; prompt and echo handling work. The component does not query the echo setting: an echoed line
  is recognised by comparing it with the last command, so a radar with echo off works too.
* `get*` is answered while the radar is running, with `Done` after each `Response`.
* `setUartOutput` / `getUartOutput 1` are supported, in the presence app only (`Error` in the speed app).
  `getLedMode 1` / `setLedMode` work in both apps.
* `saveConfig` answers plain `Done`; `save cfg complete` is not printed. When nothing changed it answers
  `Error`, or `no parameter has changed` + `Error` after `resetCfg`.
* `getRunApp` is not supported (`Error`); the work mode is taken from the reports. `setRunApp N` restarts the
  radar into the other app at once and persists without `saveConfig`.
* A redundant `sensorStop` answers `sensor stopped already` + `Done`; a redundant `sensorStart 1` answers
  `sensor started already`.
* Firmware limits that differ from the datasheet: `uart_report_period` floor 0.2 s with no coarser grid
  (93.525 s is kept exactly); `max_range` and `trigger_range` floor 2.4 m; `inhibit_time` ceiling 60 s;
  `on_latency` ceiling 2 s; `off_latency` floor 2 s; `min_range` floor 0.3 m in the presence app. The
  trigger range is not limited to max − min.
* `$DFHPD` follows `uart_report_period`, plus an immediate line on change in on-change mode (the mode the
  component writes).
* The OUT pin works in speed mode and follows the target without delay; `$DFDMD` streams at about 10 Hz.
* Commands work with CR LF and with no line ending at all, so the component always sends CR LF.

Still open:

* Everything on the SEN0610 and SEN0395 (including the SEN0395 limits and factory defaults, which come from
  its manual). `led` stays a probed setting on the C4001 until those are checked.
* SEN0610 upper range limit (12 m assumed) and prompt text.
* Whether the prompt is followed by a space (`DFRobot:/> ` or `DFRobot:/>`). The reader accepts both;
  a captured transcript should still be added as a replay test.
* How often the C4001 sends `$DFHPD` in an empty room. A quiet radar is pinged with `getSWV` after
  30 s instead of being declared lost, so either cadence works for the link; the UART presence source only
  stays live while reports follow `uart_report_period`.
* A radar left in passive UART output mode (report period above 1500 s) sends no reports until a UART
  setting is changed; polling with `getOutput` is not implemented, so until then only the pin provides
  occupancy.
* Whether `resetCfg` also resets the C4001 speed app's settings.

Run the probe YAMLs (`c4001-probe.yaml`, and a SEN0395 probe) and capture transcripts before relying on
anything in this list.

## Code layout

ESPHome only copies source files that sit directly in a component directory (or in entity platform
sub-packages), so the pure C++ protocol layer lives in flat `mmwave_*` files instead of a `protocol/`
folder. None of them includes an ESPHome header.

| File | Role |
|---|---|
| `mmwave_dialect.h` | per-model prompt, sentence tags, baud, timings, limits |
| `mmwave_params.h/.cpp` | parameter and command-group tables (the one place a setting is defined) |
| `mmwave_line_reader.*` | bytes → lines / prompt ends at `:/>`, one optional space swallowed (fixed 128-byte buffer) |
| `mmwave_responses.*` | reply classification, bounded Response/sentence tokenisers |
| `mmwave_formatter.*` | wire strings (`%.3f` without trailing zeros) |
| `mmwave_command_queue.h` | POD ring buffer, per-parameter state |
| `mmwave_engine.*` | lifecycle FSM, transactions, read-back, sentences, occupancy from pin OR UART |
| `dfrobot_mmwave.*` | ESPHome hub: feeds UART bytes / pin / time into the engine, publishes entities |
| `number/ select/ switch/ button/` | thin entity shims: publish the request, hand it to the hub |

No heap allocation happens after `setup()`; strings are only built when a text sensor is published.

## Tests

```bash
# host unit + simulation tests (fake radar, ASan/UBSan) — no ESPHome needed
esphome/components/dfrobot_mmwave/host_tests/run.sh
# config validation must reject model mismatches, wrong baud, missing pin, removed options
esphome/components/dfrobot_mmwave/host_tests/validate_negative.sh
# limits, default modes and names, presence pin schema, removed options
pytest tests/component_tests/dfrobot_mmwave
# ESPHome config / compile tests
script/test_build_components -e config -c dfrobot_mmwave
script/test_build_components -e compile -c dfrobot_mmwave -t esp32-idf
```
