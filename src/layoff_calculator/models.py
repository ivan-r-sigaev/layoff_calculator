from dataclasses import dataclass
from enum import Enum, auto
import numpy as np

@dataclass(frozen=True)
class Machine:
    # TODO: validate...
    name: str
    count: int
    profit_per_hour: float
    working_hours_mean: float
    repair_hours_mean_3: float
    repair_hours_mean_6: float
    repair_hours_mean_36: float

class RepairStrategy(Enum):
    FIFO = auto()
    WSPT = auto()

@dataclass(frozen=True)
class ConstantParams:
    # TODO: validate...
    machines: list[Machine]
    costs_per_hour_3: float
    costs_per_hour_6: float
    costs_per_hour_base: float
