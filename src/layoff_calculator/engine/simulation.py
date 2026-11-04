from layoff_calculator.models import ConstantParams, Machine, RepairStrategy
import math
from dataclasses import dataclass
import simpy
import numpy as np

@dataclass(frozen=True)
class SimulationParams:
    # TODO: validate...
    days: int
    repair_strategy: RepairStrategy
    global_seed: int
    max_workers: int
    is_hot_repair_enabled: bool
    is_auto_repair_enabled: bool

@dataclass(frozen=True)
class RunParams:
    constants: ConstantParams
    simulation: SimulationParams
    seeder: np.random.SeedSequence
    is_worker_3_available: bool

@dataclass
class RunResult:
    profit: float

HOURS_IN_DAY: int = 24
HOURS_IN_MACHINE_SHIFT: int = 16
HOURS_IN_REPAIR_SHIFT: int = 8

def _hour_of_day(time: int):
    return time % HOURS_IN_DAY

def _machine_hours_left(hour_of_day: int):
    return max(0, HOURS_IN_MACHINE_SHIFT - hour_of_day)

def _hours_left(hour_of_day: int):
    return HOURS_IN_DAY - hour_of_day

def _hours_to_break(machine_hours: int, hour_of_day: int):
    machine_hours_left = _machine_hours_left(hour_of_day)
    if machine_hours_left > machine_hours:
        return machine_hours
    
    machine_hours -= machine_hours_left
    total = _hours_left(hour_of_day)

    whole_days_left = machine_hours // HOURS_IN_MACHINE_SHIFT
    machine_hours -= whole_days_left * HOURS_IN_MACHINE_SHIFT
    total += whole_days_left * HOURS_IN_DAY

    total += machine_hours

    return total
    
def _count_machine_hours(start: int, end: int):
    if start > end:
        return 0
    start_remainder = _machine_hours_left(_hour_of_day(start))
    end_remainder = _machine_hours_left(_hour_of_day(end))
    whole_days = end // HOURS_IN_DAY - start // HOURS_IN_DAY
    return start_remainder + whole_days * HOURS_IN_MACHINE_SHIFT - end_remainder

def _machine(env: simpy.Environment, workers: simpy.PriorityResource, seed: np.random.SeedSequence,
             machine: Machine, params: RunParams, result: RunResult):
    rng = np.random.default_rng(seed)
    end_time = params.simulation.days * HOURS_IN_DAY

    while True:
        machine_hours = math.ceil(rng.exponential(machine.working_hours_mean))
        hours_to_break = _hours_to_break(machine_hours, _hour_of_day(env.now))
        if env.now + hours_to_break >= end_time:
            result.profit += _count_machine_hours(env.now, end_time) * machine.profit_per_hour
            break
        yield env.timeout(hours_to_break)
        result.profit += machine_hours * machine.profit_per_hour

        break_time = env.now
        wait_for_end = env.timeout(end_time - env.now - 1) 
        wait_for_auto_repair = env.timeout(_hours_left(_hour_of_day(env.now)))
        if params.is_worker_3_available:
            hours_to_repair_mean = machine.repair_hours_mean_36
            workers_salary = params.constants.costs_per_hour_6 + params.constants.costs_per_hour_base + \
                params.constants.costs_per_hour_3
        else:
            hours_to_repair_mean = machine.repair_hours_mean_6
            workers_salary = params.constants.costs_per_hour_6 + params.constants.costs_per_hour_base
        match params.simulation.repair_strategy:
            case RepairStrategy.FIFO:
                priority = 0
            case RepairStrategy.WSPT:
                if machine.profit_per_hour != 0.0:
                    # As per SimPy spec: smaller number -> higher priority
                    priority = hours_to_repair_mean / machine.profit_per_hour
                else:
                    priority = 0
        wait_for_workers = workers.request(priority)
        if params.simulation.is_auto_repair_enabled:
            wait_result = yield wait_for_workers | wait_for_end | wait_for_auto_repair
        else:
            wait_result = yield wait_for_workers | wait_for_end

        if wait_for_end in wait_result:
            if wait_for_workers in wait_result:
                workers.release(wait_for_workers)
            else:
                wait_for_workers.cancel()
            
            result.profit -= _count_machine_hours(break_time, end_time) * machine.profit_per_hour
            break

        if wait_for_auto_repair in wait_result:
            if wait_for_workers in wait_result:
                workers.release(wait_for_workers)
            else:
                wait_for_workers.cancel()
            
            _ = rng.exponential() # Must exhaust one iteration of rng for fair CRN
            result.profit -= _count_machine_hours(break_time, env.now) * machine.profit_per_hour
            continue

        machine_hours_left = _machine_hours_left(_hour_of_day(env.now))
        if not params.simulation.is_hot_repair_enabled and machine_hours_left != 0:
            yield env.timeout(machine_hours_left)
        
        repair_hours = env.now

        hours_to_fix = math.ceil(rng.exponential(hours_to_repair_mean))
        if params.simulation.is_auto_repair_enabled:
            hours_to_fix = min(hours_to_fix, _hours_left(_hour_of_day(env.now)))
        if env.now + hours_to_fix >= end_time:
            result.profit -= _count_machine_hours(break_time, end_time) * machine.profit_per_hour
            result.profit -= (end_time - repair_hours) * workers_salary
            break
        yield env.timeout(hours_to_fix)
        result.profit -= _count_machine_hours(break_time, env.now) * machine.profit_per_hour
        result.profit -= (env.now - repair_hours) * workers_salary
        workers.release(wait_for_workers)

        
        if _machine_hours_left(_hour_of_day(env.now)) == 0:
            yield env.timeout(_hours_left(_hour_of_day(env.now)))


def simulate_run(params: RunParams) -> RunResult:
    env = simpy.Environment()
    workers = simpy.PriorityResource(env)
    result = RunResult(profit=0.0)
    seeder = np.random.SeedSequence(**params.seeder.state)

    for machine in params.constants.machines:
        n = machine.count
        seeds = seeder.spawn(n)
        for i in range(n):
            env.process(_machine(env, workers, seeds[i], machine, params, result))

    env.run(params.simulation.days * HOURS_IN_DAY)
    return result