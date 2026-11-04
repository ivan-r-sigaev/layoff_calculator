from dataclasses import dataclass
from enum import Enum, auto
import math
import numpy as np

@dataclass(frozen=True)
class Machine:
    name: str
    count: int
    profit_per_hour: float
    working_hours_mean: float
    repair_hours_mean_3: float
    repair_hours_mean_6: float
    repair_hours_mean_36: float

    def __post_init__(self):
        # if not self.name or not self.name.strip():
        #     raise ValueError("Machine name must be non-empty.")
        
        if self.count <= 0:
            raise ValueError(f"Machine '{self.name}': count must be > 0 (got {self.count}).")
        
        if self.profit_per_hour < 0:
            raise ValueError(f"Machine '{self.name}': profit per hour must be >= 0 (got {self.profit_per_hour}).")
        
        if self.working_hours_mean <= 0:
            raise ValueError(f"Machine '{self.name}': working_hours_mean must be > 0 (got {self.working_hours_mean}).")
        
        for id, value in [
            ("(3)", self.repair_hours_mean_3),
            ("(6)", self.repair_hours_mean_6),
            ("(3 + 6)", self.repair_hours_mean_36),
        ]:
            if value <= 0 and value != math.inf:
                raise ValueError(f"Machine '{self.name}': mean repair time {id} must be > 0 or +inf (got {value}).")

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

    def __post_init__(self):
        if not self.machines:
            raise ValueError("Machine list must be non-empty.")

        # unique_names = []
        # for m in self.machines:
        #     name = m.name
        #     if name in unique_names:
        #         raise ValueError(f"All machine names in the list must be unique (name '{name}' appears multiple times).")

        #     unique_names.append(m)

        for id, value in [
            ("(3)", self.costs_per_hour_3),
            ("(6)", self.costs_per_hour_6),
        ]:
            if value < 0:
                raise ValueError(f"worker salary {id} must be >= 0 (got {value}).")

        if self.costs_per_hour_base < 0:
            raise ValueError(f"base costs per hour must be >= 0 (got {self.costs_per_hour_base}).")
