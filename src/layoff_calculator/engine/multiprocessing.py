from layoff_calculator.engine.simulation import SimulationParams, RunParams, RunResult, simulate_run
from layoff_calculator.models import ConstantParams
import statistics
import multiprocessing as mp
from threading import Lock
from concurrent.futures import Future, ProcessPoolExecutor
from collections import deque
import numpy as np
from scipy import stats
from dataclasses import dataclass

@dataclass(frozen=True)
class SplitRunResult:
    run_with_3: RunResult
    run_without_3: RunResult

    @property
    def layoff_profit(self) -> float:
        return self.run_without_3.profit - self.run_with_3.profit

class SplitRunError(RuntimeError):
    def __init__(self, seeder: np.random.SeedSequence, 
                 e_with_3: BaseException | None, e_without_3: BaseException | None):
        if e_with_3 is None and e_without_3 is None:
            raise ValueError(
                f"Constructing {SplitRunError.__name__} requires at lease one non-None exception passed as an argument")
        self.seeder = seeder
        self.e_with_3: BaseException | None = e_with_3
        self.e_without_3: BaseException | None = e_without_3
        super().__init__(self._format())
    
    def _format(self) -> str:
        parts = []
        if self.e_with_3 is not None:
            parts.append(f"with_3: {self.e_with_3!r}")
        if self.e_without_3 is not None:
            parts.append(f"without_3: {self.e_without_3!r}")
        return f"Run failed (seeder={self.seeder!r}): " + "; ".join(parts)

class RunResults:
    def __init__(self):
        self._layoff_profits: list[float] = []

    def add(self, result: SplitRunResult) -> None:
        self._layoff_profits.append(result.layoff_profit)

    def layoff_profit_mean(self) -> float:
        if len(self._layoff_profits) == 0:
            return float("nan")
        return statistics.mean(self._layoff_profits)

    def layoff_profit_stdev(self) -> float:
        if len(self._layoff_profits) < 2:
            return float("nan")
        return statistics.stdev(self._layoff_profits)

    def layoff_profit_bayesian_p(self) -> float:
        n = len(self._layoff_profits)
        if n < 2:
            return 0.5
        
        mean = self.layoff_profit_mean()
        stdev = self.layoff_profit_stdev()
        if stdev == 0:
            if mean > 0:
                return 1.0
            elif mean < 0:
                return 0.0
            else:
                return 0.5
        
        t = mean / (stdev / np.sqrt(n))
        return float(stats.t.cdf(t, df=n-1))

class Engine:
    def __init__(self, constants: ConstantParams, simulation: SimulationParams):
        self._constants: ConstantParams = constants
        self._simulation: SimulationParams = simulation
        self._seeder: np.random.SeedSequence = np.random.SeedSequence(simulation.global_seed)
        self._completed_runs_count: int = 0
        self._submitted_runs_count: int = 0
        self._pending_results: deque[Future[SplitRunResult]] = deque()
        self._results: RunResults = RunResults()
        mp_context = mp.get_context("spawn")
        self._executor: ProcessPoolExecutor = ProcessPoolExecutor(max_workers=simulation.max_workers, mp_context=mp_context)

    @property
    def submitted_runs_count(self) -> int:
        return self._submitted_runs_count

    @property
    def completed_runs_count(self) -> int:
        return self._completed_runs_count

    @property
    def pending_runs_count(self) -> int:
        return self._submitted_runs_count - self._completed_runs_count

    @property
    def layoff_profit_mean(self) -> float:
        return self._results.layoff_profit_mean()

    @property
    def layoff_profit_stdev(self) -> float:
        return self._results.layoff_profit_stdev()

    @property
    def layoff_profit_bayesian_p(self) -> float:
        return self._results.layoff_profit_bayesian_p()

    def make_runs(self, count: int) -> None:
        seeds = self._seeder.spawn(count)
        for i in range(count):
            seed = seeds[i]
            f_split_run = self._submit_split_run(seed)
            self._pending_results.append(f_split_run)
            self._submitted_runs_count += 1

    def check_pending_results(self) -> None:
        while len(self._pending_results) != 0 and self._pending_results[0].done():
            self._completed_runs_count += 1
            result = self._pending_results.popleft().result()
            self._results.add(result)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _submit_split_run(self, seeder: np.random.SeedSequence) -> Future[SplitRunResult]:
        seeder = np.random.SeedSequence(**seeder.state)
        params_without_3 = RunParams(
            constants=self._constants, simulation=self._simulation,
            seeder=np.random.SeedSequence(**seeder.state),
            is_worker_3_available=False)
        params_with_3 = RunParams(
            constants=self._constants, simulation=self._simulation,
            seeder=np.random.SeedSequence(**seeder.state),
            is_worker_3_available=True)
        f_without_3 = self._executor.submit(simulate_run, params_without_3)
        f_with_3 = self._executor.submit(simulate_run, params_with_3)

        result: Future = Future()
        result_lock: Lock = Lock()

        def _set_result_on_ready(_):
            with result_lock:  # Executor probably already serializes callbacks, but just to be safe.
                if result.done() or not (f_with_3.done() and f_without_3.done()):
                    return

                try:
                    e_with_3 = f_with_3.exception()
                    e_without_3 = f_without_3.exception()
                    if e_with_3 is not None or e_without_3 is not None:
                        raise SplitRunError(
                            seeder=np.random.SeedSequence(**seeder.state),
                            e_with_3=e_with_3, e_without_3=e_without_3)
                    split_run = SplitRunResult(run_with_3=f_with_3.result(), run_without_3=f_without_3.result())
                    result.set_result(split_run)
                except Exception as e:
                    result.set_exception(e)
            
            f_with_3.add_done_callback(_set_result_on_ready)
            f_without_3.add_done_callback(_set_result_on_ready)

            return result
