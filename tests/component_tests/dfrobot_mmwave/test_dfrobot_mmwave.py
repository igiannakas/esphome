"""Tests for dfrobot_mmwave config validation, number limits and default entity modes."""

from collections.abc import Callable
from pathlib import Path

import pytest

from esphome.components.dfrobot_mmwave import NUMBER_LIMITS, number_limits, number_mode
from esphome.config import load_config
from esphome.core import CORE

BASE_YAML = """
esphome:
  name: test
esp32:
  board: esp32dev
  framework:
    type: esp-idf
uart:
  id: radar_uart
  tx_pin: GPIO17
  rx_pin: GPIO16
  baud_rate: 9600
"""


@pytest.mark.parametrize(
    ("model", "key", "expected"),
    [
        ("SEN0609", "max_range", (2.4, 26.0, 0.1)),
        ("SEN0609", "trigger_range", (2.4, 25.0, 0.1)),
        ("SEN0609", "inhibit_time", (0.1, 60.0, 0.1)),
        ("SEN0609", "on_latency", (0.0, 2.0, 0.01)),
        ("SEN0609", "off_latency", (2.0, 1500.0, 0.5)),
        ("SEN0609", "uart_report_period", (0.2, 1500.0, 0.025)),
        ("SEN0610", "max_range", (2.4, 12.0, 0.1)),
        ("SEN0610", "trigger_range", (2.4, 12.0, 0.1)),
        ("SEN0395", "min_range", (0.0, 9.45, 0.15)),
        ("SEN0395", "on_latency", (0.0, 100.0, 0.025)),
        ("SEN0395", "uart_report_period", (0.025, 1500.0, 0.025)),
    ],
)
def test_number_limits(
    model: str, key: str, expected: tuple[float, float, float]
) -> None:
    assert number_limits(model, key) == pytest.approx(expected)


def test_every_limit_is_consistent() -> None:
    for rows in NUMBER_LIMITS.values():
        for lo, hi, step in rows.values():
            assert lo <= hi
            assert step > 0


@pytest.mark.parametrize(
    ("model", "key", "mode"),
    [
        ("SEN0609", "min_range", "SLIDER"),
        ("SEN0609", "inhibit_time", "SLIDER"),
        ("SEN0609", "off_latency", "BOX"),
        ("SEN0609", "uart_report_period", "BOX"),
        ("SEN0609", "speed_threshold_factor", "BOX"),
        ("SEN0395", "on_latency", "BOX"),
        ("SEN0395", "sensitivity", "SLIDER"),
    ],
)
def test_number_mode_defaults(model: str, key: str, mode: str) -> None:
    assert number_mode(model, key) == mode


def test_generated_limits_and_modes(generate_main: Callable[[str], str]) -> None:
    main_cpp = generate_main(
        "tests/component_tests/dfrobot_mmwave/test_dfrobot_mmwave.yaml"
    )

    assert "n_max_range->traits.set_min_value(2.4f);" in main_cpp
    assert "n_max_range->traits.set_max_value(26.0f);" in main_cpp
    assert "n_inhibit->traits.set_max_value(60.0f);" in main_cpp
    assert "n_period->traits.set_min_value(0.2f);" in main_cpp
    assert "n_min_range->traits.set_mode(number::NUMBER_MODE_SLIDER);" in main_cpp
    assert "n_on_latency->traits.set_mode(number::NUMBER_MODE_SLIDER);" in main_cpp
    assert "n_period->traits.set_mode(number::NUMBER_MODE_BOX);" in main_cpp
    # an explicit mode on the entity wins over the default (BOX for off_latency)
    assert "n_off_latency->traits.set_mode(number::NUMBER_MODE_SLIDER);" in main_cpp


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "radar.yaml"
    path.write_text(BASE_YAML + body)
    return path


def test_minimal_config(generate_main: Callable[[str], str]) -> None:
    main_cpp = generate_main("tests/component_tests/dfrobot_mmwave/test_minimal.yaml")

    # a bare presence pin is an input with a pull-down
    assert "set_pin(::GPIO_NUM_19);" in main_cpp
    assert "(gpio::Flags::FLAG_INPUT | gpio::Flags::FLAG_PULLDOWN)" in main_cpp
    assert "radar->set_target_timeout(2000);" in main_cpp
    # renamed and new entities get default names
    assert '"LED"' in main_cpp
    assert '"Speed mode micro motion"' in main_cpp
    assert '"Speed mode threshold factor"' in main_cpp


def test_presence_pin_full_schema(
    tmp_path: Path, generate_main: Callable[[Path], str]
) -> None:
    path = _write(
        tmp_path,
        """
dfrobot_mmwave:
  id: radar
  model: SEN0609
  presence_pin:
    number: GPIO19
    mode: INPUT
    inverted: true
""",
    )
    main_cpp = generate_main(path)

    assert "set_flags(gpio::Flags::FLAG_INPUT);" in main_cpp
    assert "set_inverted(true);" in main_cpp


DEFAULT_NAMES = [
    "Occupancy",
    "Occupancy (UART)",
    "Occupancy (OUT pin)",
    "Radar link",
    "Radar enabled",
    "LED",
    "UART presence report",
    "UART target report",
    "UART report period",
    "Min range",
    "Max range",
    "Trigger range",
    "Sensitivity",
    "Hold sensitivity",
    "Trigger sensitivity",
    "On latency",
    "Off latency",
    "Inhibit time",
    "Speed mode micro motion",
    "Speed mode threshold factor",
    "Work mode",
    "Reread radar settings",
    "Restart radar",
    "Factory reset radar",
    "Targets",
    "Target 1 distance",
    "Target 1 SNR",
    "Target 8 distance",
    "Target 8 SNR",
    "Target 1 speed",
    "Target 1 energy",
    "Radar firmware",
    "Radar hardware",
    "Radar status",
    "Radar last error",
]


def test_every_entity_has_a_default_name(generate_main: Callable[[str], str]) -> None:
    main_cpp = generate_main(
        "tests/component_tests/dfrobot_mmwave/test_default_names.yaml"
    )

    for name in DEFAULT_NAMES:
        assert f'"{name}"' in main_cpp, name


def test_explicit_name_overrides_the_default(
    tmp_path: Path, generate_main: Callable[[Path], str]
) -> None:
    path = _write(
        tmp_path,
        """
dfrobot_mmwave:
  id: radar
  model: SEN0609
button:
  - platform: dfrobot_mmwave
    refresh:
      name: Read it again
""",
    )
    main_cpp = generate_main(path)

    assert '"Read it again"' in main_cpp
    assert '"Reread radar settings"' not in main_cpp


REMOVED = [
    ("dfrobot_mmwave", "presence_source: pin"),
    ("dfrobot_mmwave", "apply_mode: manual"),
    ("dfrobot_mmwave", "boot_delay: 3s"),
    ("dfrobot_mmwave", "refresh_interval: 10min"),
    ("dfrobot_mmwave", "link_timeout: 30s"),
    ("dfrobot_mmwave", "pin_debounce: 0ms"),
    ("dfrobot_mmwave", "speed_mode_idle_value: nan"),
    ("binary_sensor", "presence_disagreement: {name: x}"),
    ("binary_sensor", "config_pending: {name: x}"),
    ("button", "apply: {name: x}"),
    ("select", "led_mode: {name: x}"),
    ("switch", "micro_motion: {name: x}"),
    ("number", "threshold_factor: {name: x}"),
    ("select", "uart_report_mode: {name: x}"),
    ("binary_sensor", "sensor_running: {name: x}"),
]


@pytest.mark.parametrize(("domain", "line"), REMOVED)
def test_removed_options_are_rejected(tmp_path: Path, domain: str, line: str) -> None:
    key = line.split(":", maxsplit=1)[0]
    hub = "dfrobot_mmwave:\n  id: radar\n  model: SEN0609\n  presence_pin: GPIO19\n"
    if domain == "dfrobot_mmwave":
        body = hub + f"  {line}\n"
    else:
        body = hub + f"{domain}:\n  - platform: dfrobot_mmwave\n    {line}\n"
    CORE.config_path = _write(tmp_path, body)

    errors = [str(err) for err in load_config({}).errors]

    assert any(
        "extra keys not allowed" in err and f"['{key}']" in err for err in errors
    ), errors


def test_apply_action_is_removed(tmp_path: Path) -> None:
    CORE.config_path = _write(
        tmp_path,
        """
dfrobot_mmwave:
  id: radar
  model: SEN0609
interval:
  - interval: 1h
    then:
      - dfrobot_mmwave.apply: radar
""",
    )

    errors = [str(err) for err in load_config({}).errors]

    assert any("dfrobot_mmwave.apply" in err for err in errors), errors
