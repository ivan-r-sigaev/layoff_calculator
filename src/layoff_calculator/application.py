from domain import RunParams, RunResult, Machine, RepairStrategy
import numpy as np
from scipy import stats
import simpy
import math

HOURS_IN_DAY: int = 24
HOURS_IN_MACHINE_SHIFT: int = 16
HOURS_IN_REPAIR_SHIFT: int = 8

def _machine(env: simpy.Environment, workers: simpy.PriorityResource, seed: np.random.SeedSequence,
             machine: Machine, params: RunParams, is_worker_3_available: bool, result: RunResult):
    def count_working_hours(start, end):
        if start > end:
            return 0
        start_remainder = max(HOURS_IN_DAY - start % HOURS_IN_DAY - HOURS_IN_REPAIR_SHIFT, 0)
        end_remainder = max(HOURS_IN_DAY - end % HOURS_IN_DAY - HOURS_IN_REPAIR_SHIFT, 0)
        whole_days = end // HOURS_IN_DAY - start // HOURS_IN_DAY
        return start_remainder - end_remainder + whole_days * HOURS_IN_MACHINE_SHIFT
    
    rng = np.random.default_rng(seed)
    end_hours = params.simulation.days * HOURS_IN_DAY

    while True:
        working_hours = math.ceil(rng.exponential(machine.working_hours_mean))
        hours_to_day_end = HOURS_IN_DAY - env.now % HOURS_IN_DAY
        hours_to_shift_end = hours_to_day_end - HOURS_IN_REPAIR_SHIFT
        if hours_to_shift_end >= working_hours:
            hours_to_break = working_hours
        else:
            working_hours_remainder = working_hours - hours_to_shift_end
            working_days = working_hours_remainder // HOURS_IN_MACHINE_SHIFT
            hours_remainder = working_hours_remainder % HOURS_IN_MACHINE_SHIFT
            hours_to_break = hours_to_day_end + working_days * HOURS_IN_DAY + hours_remainder
        if env.now + hours_to_break >= end_hours:
            result.profit += count_working_hours(env.now, end_hours) * machine.profit_per_hour
            break
        yield env.timeout(hours_to_break)
        result.profit += working_hours * machine.profit_per_hour

        break_hours = env.now
        wait_for_end = env.timeout(end_hours - break_hours)
        wait_for_auto_repair = env.timeout(HOURS_IN_DAY - break_hours % HOURS_IN_DAY)
        if is_worker_3_available:
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
                # As per SimPy spec: smaller number -> higher priority
                priority = hours_to_repair_mean / machine.profit_per_hour
        wait_for_repair = workers.request(priority)
        if params.simulation.is_auto_repair_enabled:
            wait_result = yield wait_for_repair | wait_for_end | wait_for_auto_repair
        else:
            wait_result = yield wait_for_repair | wait_for_end

        if wait_for_end in wait_result:
            wait_for_repair.cancel()
            result.profit -= count_working_hours(break_hours, end_hours) * machine.profit_per_hour
            break
        if wait_for_auto_repair in wait_result:
            wait_for_repair.cancel()
            _ = rng.exponential() # Must exhaust one iteration of rng for fair CRN
            result.profit -= count_working_hours(break_hours, env.now) * machine.profit_per_hour
            continue

        hour_of_day = env.now % HOURS_IN_DAY
        if not params.simulation.is_hot_repair_enabled and hour_of_day < HOURS_IN_MACHINE_SHIFT:
            yield env.timeout(HOURS_IN_MACHINE_SHIFT - hour_of_day)
        repair_hours = env.now

        hours_to_fix = math.ceil(rng.exponential(hours_to_repair_mean))
        if params.simulation.is_auto_repair_enabled:
            hours_to_day_end = HOURS_IN_DAY - env.now % HOURS_IN_DAY
            hours_to_fix = min(hours_to_fix, hours_to_day_end)
        if env.now + hours_to_fix >= end_hours:
            result.profit -= count_working_hours(break_hours, end_hours) * machine.profit_per_hour
            result.profit -= (end_hours - repair_hours) * workers_salary
            break
        yield env.timeout(hours_to_fix)
        result.profit -= count_working_hours(break_hours, env.now) * machine.profit_per_hour
        result.profit -= (env.now - repair_hours) * workers_salary
        workers.release(wait_for_repair)

        hours_to_day_end = HOURS_IN_DAY - env.now % HOURS_IN_DAY
        if hours_to_day_end <= HOURS_IN_REPAIR_SHIFT:
            if env.now + hours_to_day_end >= end_hours:
                break
            yield env.timeout(hours_to_day_end)


def _simulate_run(params: RunParams, seeder: np.random.SeedSequence, is_worker_3_available: bool) -> float:
    env = simpy.Environment()
    workers = simpy.PriorityResource(env)
    result = RunResult(profit=0.0)

    for machine in params.constants.machines:
        n = machine.count
        seeds = seeder.spawn(n)
        for i in range(n):
            env.process(_machine(env, workers, seeds[i], machine, params, is_worker_3_available, result))

    env.run(params.simulation.days * HOURS_IN_DAY)
    return result.profit

class RunEngine:
    def __init__(self, params: RunParams):
        # TODO: validate params...
        # TODO: should I validate params here on when constructing the dataclass?
        self._params: RunParams = params
        self._results: list[float] = []
        self._seeder: np.random.SeedSequence = np.random.SeedSequence(params.simulation.global_seed)

    def make_runs(self, count: int):
        seeds = self._seeder.spawn(count)
        for i in range(count):
            seed = seeds[i]
            profit_with_3 = _simulate_run(self._params, seed, True)
            profit_without_3 = _simulate_run(self._params, seed, False)
            self._results.append(profit_without_3 - profit_with_3)

    def confidence_range(self, conf_level: float) -> tuple[float, float]:
        n = len(self.results)
        if n < 2:
            return (float('inf'), float('-inf'))
        mean = np.mean(self.results)
        se = stats.sem(self.results)
        t = stats.t.ppf((1 + conf_level) / 2, n - 1)
        margin = t * se
        return (mean - margin, mean + margin)

    @property
    def results(self) -> tuple[float, ...]:
        return tuple(self._results)
