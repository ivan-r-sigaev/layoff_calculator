from enum import StrEnum

class ConfigError(Exception):
    pass

class TomlName(StrEnum):
    MACHINES = "machines"
    MACHINES_NAME = "name"
    MACHINES_COUNT = "count"
    MACHINES_PROFIT = "profit-hourly"
    MACHINES_MTBF = "mean-working-hours"
    MACHINES_REPAIR_3 = "mean-repair-3-hours"
    MACHINES_REPAIR_6 = "mean-repair-6-hours"
    MACHINES_REPAIR_36 = "mean-repair-36-hours"
    COSTS = "costs"
    COSTS_BASE = "base-costs"
    COSTS_3 = "salary-3"
    COSTS_6 = "salary-6"
