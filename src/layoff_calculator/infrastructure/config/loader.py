import tomllib
from typing import Any
from pathlib import Path
from domain import Machine, ConstantParams
from infrastructure.config.common import TomlName, ConfigError

def load_config(path: str | Path) -> ConstantParams:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("rb") as f:
        try:
            raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML in {path}: {e}") from e

    machines = _parse_machines(raw)
    costs = _parse_costs(raw)

    return ConstantParams(
        machines=machines,
        costs_per_hour_3=costs[TomlName.COSTS_3],
        costs_per_hour_6=costs[TomlName.COSTS_6],
        costs_per_hour_base=costs[TomlName.COSTS_BASE],
    )


def _parse_machines(raw: dict[str, Any]) -> list[Machine]:
    if TomlName.MACHINES not in raw:
        raise ConfigError(f"Missing section: [[{TomlName.MACHINES}]]")
    entries = raw[TomlName.MACHINES]
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"Section [[{TomlName.MACHINES}]] must be a non-empty list")

    machines: list[Machine] = []
    seen_names: set[str] = set()

    for i, entry in enumerate(entries):
        prefix = f"{TomlName.MACHINES}[{i}]"

        name = _parse_str(entry, TomlName.MACHINES_NAME, prefix)
        if name in seen_names:
            raise ConfigError(f"{prefix}.{TomlName.MACHINES_NAME}: duplicate machine name '{name}'")
        seen_names.add(name)

        count = _parse_positive_int(entry, TomlName.MACHINES_COUNT, prefix)

        profit = _parse_non_negative_float(entry, TomlName.MACHINES_PROFIT, prefix)
        working = _parse_positive_float(entry, TomlName.MACHINES_MTBF, prefix)
        repair_3 = _parse_repair(entry, TomlName.MACHINES_REPAIR_3, prefix)
        repair_6 = _parse_repair(entry, TomlName.MACHINES_REPAIR_6, prefix)
        repair_36 = _parse_repair(entry, TomlName.MACHINES_REPAIR_36, prefix)

        machines.append(Machine(
            name=name,
            count=count,
            profit_per_hour=profit,
            working_hours_mean=working,
            repair_hours_mean_3=repair_3,
            repair_hours_mean_6=repair_6,
            repair_hours_mean_36=repair_36,
        ))

    return machines


def _parse_costs(raw: dict[str, Any]) -> dict[TomlName, float]:
    if TomlName.COSTS not in raw:
        raise ConfigError(f"Missing section: [{TomlName.COSTS}]")
    c = raw[TomlName.COSTS]
    prefix = TomlName.COSTS
    return {
        TomlName.COSTS_3: _parse_non_negative_float(c, TomlName.COSTS_3, prefix),
        TomlName.COSTS_6: _parse_non_negative_float(c, TomlName.COSTS_6, prefix),
        TomlName.COSTS_BASE: _parse_non_negative_float(c, TomlName.COSTS_BASE, prefix),
    }


def _parse_str(d: dict[str, Any], key: str, prefix: str) -> str:
    if key not in d:
        raise ConfigError(f"{prefix}: missing key '{key}'")
    value = d[key]
    if not isinstance(value, str):
        raise ConfigError(f"{prefix}.{key}: expected string, got {type(value).__name__}")
    return value


def _parse_positive_int(d: dict[str, Any], key: str, prefix: str) -> int:
    if key not in d:
        raise ConfigError(f"{prefix}: missing key '{key}'")
    value = d[key]
    # bool is int subclass, thanks Python...
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{prefix}.{key}: expected int, got {type(value).__name__}")
    
    if value <= 0:
        raise ConfigError(f"{prefix}.{key} must be positive, got {value}")
    return value


def _parse_positive_float(d: dict[str, Any], key: str, prefix: str) -> float:
    value = _parse_non_negative_float(d, key, prefix)
    if value <= 0:
        raise ConfigError(f"{prefix}.{key} must be positive, got {value}")
    return value


def _parse_non_negative_float(d: dict[str, Any], key: str, prefix: str) -> float:
    if key not in d:
        raise ConfigError(f"{prefix}: missing key '{key}'")
    value = d[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{prefix}.{key}: expected number, got {type(value).__name__}")
    value = float(value)
    if value < 0:
        raise ConfigError(f"{prefix}.{key} must be non-negative, got {value}")
    return value


def _parse_repair(d: dict[str, Any], key: str, prefix: str) -> float | None:
    if key not in d:
        raise ConfigError(f"{prefix}: missing key '{key}'")
    value = d[key]
    if isinstance(value, str):
        if value.lower() == "n/a":
            return float("inf")
        raise ConfigError(f'{prefix}.{key}: expected number or "n/a", got "{value}"')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f'{prefix}.{key}: expected number or "n/a", got {type(value).__name__}')
    value = float(value)
    if value <= 0:
        raise ConfigError(f"{prefix}.{key} must be positive, got {value}")
    return value
