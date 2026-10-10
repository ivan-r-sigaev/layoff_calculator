from dataclasses import dataclass
from enum import Enum

@dataclass(frozen=True)
class Machine:
    name: str
    count: int
    profit_per_hour: float
    working_hours_mean: float
    repair_hours_mean_3: float
    repair_hours_mean_6: float
    repair_hours_mean_36: float

class RepairStrategy(Enum):
    FIFO = 1
    WSPT = 2

@dataclass(frozen=True)
class ConstantParams:
    machines: list[Machine]
    costs_per_hour_3: float
    costs_per_hour_6: float
    costs_per_hour_base: float

@dataclass(frozen=True)
class SimulationParams:
    days: int
    repair_strategy: RepairStrategy
    global_seed: int
    is_hot_repair_enabled: bool
    is_auto_repair_enabled: bool

@dataclass(frozen=True)
class RunParams:
    constants: ConstantParams
    simulation: SimulationParams

@dataclass
class RunResult:
    profit: float
