import tomli_w
import math
from pathlib import Path
from layoff_calculator.models import ConstantParams
from layoff_calculator.config.common import TomlName

def save_config(path: str | Path, params: ConstantParams) -> None:
    path = Path(path)

    with path.open("wb") as f:
        obj = {
            TomlName.MACHINES: [
                {
                    TomlName.MACHINES_NAME: machine.name,
                    TomlName.MACHINES_COUNT: machine.count,
                    TomlName.MACHINES_PROFIT: machine.profit_per_hour,
                    TomlName.MACHINES_MTBF: machine.working_hours_mean,
                    TomlName.MACHINES_REPAIR_3: _save_repair(machine.repair_hours_mean_3),
                    TomlName.MACHINES_REPAIR_6: _save_repair(machine.repair_hours_mean_6),
                    TomlName.MACHINES_REPAIR_36: _save_repair(machine.repair_hours_mean_36)
                } for machine in params.machines
            ],
            TomlName.COSTS: {
                TomlName.COSTS_BASE: params.costs_per_hour_base,
                TomlName.COSTS_3: params.costs_per_hour_3,
                TomlName.COSTS_6: params.costs_per_hour_6,
            }
        }
        tomli_w.dump(obj, f)


def _save_repair(value: float):
    if value == math.inf:
        return "n/a"
    return value
