from __future__ import annotations

import math
import os
import random
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QLabel, QToolButton
)

from layoff_calculator.models import (
    ConstantParams, Machine, RepairStrategy,
)

if TYPE_CHECKING:
    from layoff_calculator.engine import Engine, SimulationParams


# -------------------------------
# No-Wheel Subclasses
# -------------------------------

class _NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class _ScientificDoubleSpinBox(_NoWheelDoubleSpinBox):
    def textFromValue(self, value: float) -> str:
        if math.isnan(value):
            return "NaN"
        return f"{value:.2e}"


class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

# -------------------------------
# Table columns
# -------------------------------


COL_NAME, COL_COUNT, COL_PROFIT, COL_MTBF, COL_R3, COL_R6, COL_R36 = range(7)

COLUMN_HEADERS = [
    "Название",
    "Кол-во, шт.",
    "Прибыль, руб./ч.",
    "МО работы, ч.",
    "МО рем. 3р., ч.",
    "МО рем. 6р., ч.",
    "МО рем. 3р.+6р., ч.",
]

COLUMN_TOOLTIPS = [
    "Название типа машины",
    "Количество машин данного типа",
    "Прибыль от работы (и убыток от простоя) в час",
    "Среднее время работы между поломками (ч)",
    "Среднее время ремонта силами 3-его разряда (ч)",
    "Среднее время ремонта силами 6-ого разряда (ч)",
    "Среднее время ремонта силами обоих разрядов (ч)",
]


# -------------------------------
# Validators & delegate
# -------------------------------

class _NumberValidator(QValidator):
    def __init__(self, *, allow_decimals: bool, allow_zero: bool,
                 allow_empty: bool, parent=None):
        super().__init__(parent)
        self._alllow_decimals = allow_decimals
        self._allow_zero = allow_zero
        self._allow_empty = allow_empty

    def validate(self, text: str, pos: int):
        s = text.strip()
        if s == "":
            return (
                (QValidator.Acceptable if self._allow_empty else QValidator.Intermediate),
                text, pos,
            )
        if s in ("-", "+", ".", "-.", "+."):
            return QValidator.Intermediate, text, pos
        try:
            value = int(s) if self._alllow_decimals else float(s)
        except ValueError:
            return QValidator.Invalid, text, pos
        if value < 0 or (value == 0 and not self._allow_zero):
            return QValidator.Invalid, text, pos
        return QValidator.Acceptable, text, pos


class _MachineDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        col = index.column()
        editor = QLineEdit(parent)
        if col == COL_NAME:
            return editor
        if col == COL_COUNT:
            editor.setValidator(_NumberValidator(
                allow_decimals=True, allow_zero=False, allow_empty=False, parent=editor))
        elif col == COL_PROFIT:
            editor.setValidator(_NumberValidator(
                allow_decimals=False, allow_zero=True, allow_empty=False, parent=editor))
        elif col == COL_MTBF:
            editor.setValidator(_NumberValidator(
                allow_decimals=False, allow_zero=False, allow_empty=False, parent=editor))
        else:
            editor.setValidator(_NumberValidator(
                allow_decimals=False, allow_zero=False, allow_empty=True, parent=editor))
        return editor


# -------------------------------
# Helpers
# -------------------------------

def _format(value: float) -> str:
    if value == math.inf:
        return ""
    if value == int(value):
        return str(int(value))
    return repr(value)


def _parse(text: str) -> float | None:
    text = text.strip()
    return math.inf if text == "" else float(text)


def _help_label(text: str, tooltip: str) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    label = QLabel(text)

    icon_btn = QToolButton()
    icon_btn.setText("?")
    icon_btn.setToolTip(tooltip)
    # Стилизация под серую круглую иконку
    icon_btn.setStyleSheet("""
        QToolButton {
            color: #888888;
            border: 1px solid #888888;
            border-radius: 7px;
            font-weight: bold;
            font-size: 10px;
            padding: 0px;
        }
        QToolButton:hover {
            color: #444444;
            border: 1px solid #444444;
            background-color: #f0f0f0;
        }
    """)
    icon_btn.setFixedSize(14, 14)
    icon_btn.setCursor(Qt.CursorShape.WhatsThisCursor)

    layout.addWidget(label)
    layout.addWidget(icon_btn)
    layout.addStretch()
    return widget


def _money_spin() -> QDoubleSpinBox:
    spin = _NoWheelDoubleSpinBox()
    spin.setRange(0.0, 1e9)
    spin.setDecimals(2)
    spin.setSingleStep(1.0)
    return spin


# -------------------------------
# Machines table widget
# -------------------------------

class MachinesTable(QTableWidget):
    MAX_VISIBLE_ROWS = 8

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMN_HEADERS), parent)
        self.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setItemDelegate(_MachineDelegate(self))

        for i, tip in enumerate(COLUMN_TOOLTIPS):
            item = self.horizontalHeaderItem(i)
            if item:
                item.setToolTip(tip)

        self.model().rowsInserted.connect(self._adjust_height)
        self.model().rowsRemoved.connect(self._adjust_height)
        self.horizontalHeader().sectionResized.connect(self._adjust_height)

        self._adjust_height()

    def _adjust_height(self, *args) -> None:
        header_height = self.horizontalHeader().height()
        if header_height <= 1:
            header_height = self.horizontalHeader().sizeHint().height()

        row_height = self.verticalHeader().defaultSectionSize()
        if row_height <= 0:
            row_height = 30

        rows = self.rowCount()
        content_height = header_height + rows * row_height + self.frameWidth() * 2 + 2
        capped_height = header_height + self.MAX_VISIBLE_ROWS * \
            row_height + self.frameWidth() * 2 + 2

        self.setFixedHeight(min(content_height, capped_height))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._adjust_height()

    def add_machine(self, machine: Machine | None = None) -> None:
        if machine is None:
            machine = Machine(
                name="Новая машина",
                count=1,
                profit_per_hour=0,
                working_hours_mean=1,
                repair_hours_mean_3=math.inf,
                repair_hours_mean_6=math.inf,
                repair_hours_mean_36=math.inf
            )

        row = self.rowCount()
        self.insertRow(row)

        values = [
            machine.name,
            str(machine.count),
            _format(machine.profit_per_hour),
            _format(machine.working_hours_mean),
            _format(machine.repair_hours_mean_3),
            _format(machine.repair_hours_mean_6),
            _format(machine.repair_hours_mean_36),
        ]
        for col, text in enumerate(values):
            self.setItem(row, col, QTableWidgetItem(text))

    def remove_selected(self) -> None:
        rows = sorted({idx.row()
                      for idx in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)

    def read_machines(self) -> list[Machine]:
        machines: list[Machine] = []
        for row in range(self.rowCount()):
            name = self._cell_text(row, COL_NAME)
            if not name:
                continue
            machines.append(Machine(
                name=name,
                count=int(self._cell_text(row, COL_COUNT)),
                profit_per_hour=float(self._cell_text(row, COL_PROFIT)),
                working_hours_mean=float(self._cell_text(row, COL_MTBF)),
                repair_hours_mean_3=_parse(self._cell_text(row, COL_R3)),
                repair_hours_mean_6=_parse(self._cell_text(row, COL_R6)),
                repair_hours_mean_36=_parse(self._cell_text(row, COL_R36)),
            ))
        return machines

    def _cell_text(self, row: int, col: int) -> str:
        item = self.item(row, col)
        return item.text().strip() if item else ""


# -------------------------------
# Constants panel
# -------------------------------

class ConstantsPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("КОНСТАНТЫ", parent)
        layout = QVBoxLayout(self)

        self.table = MachinesTable(self)
        layout.addWidget(self.table)

        row_buttons = QHBoxLayout()
        self.add_button = QPushButton("Добавить машину")
        self.add_button.setToolTip("Добавить новую строку в таблицу машин")
        self.remove_button = QPushButton("Удалить выбранные")
        self.remove_button.setToolTip("Удалить выделенные строки из таблицы")
        self.add_button.clicked.connect(lambda: self.table.add_machine())
        self.remove_button.clicked.connect(self.table.remove_selected)
        row_buttons.addWidget(self.add_button)
        row_buttons.addWidget(self.remove_button)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        costs_form = QFormLayout()
        self.costs_3 = _money_spin()
        self.costs_6 = _money_spin()
        self.costs_base = _money_spin()
        costs_form.addRow(_help_label("Зарплата 3 разряда, руб./ч.",
                          "Почасовая оплата труда слесаря 3-го разряда."), self.costs_3)
        costs_form.addRow(_help_label("Зарплата 6 разряда, руб./ч.",
                          "Почасовая оплата труда слесаря 6-го разряда."), self.costs_6)
        costs_form.addRow(_help_label("Накладные расходы, руб./ч.",
                          "Дополнительные издержки за каждый час работы бригады."), self.costs_base)
        layout.addLayout(costs_form)

        io_buttons = QHBoxLayout()
        self.load_button = QPushButton("Загрузить")
        self.load_button.setToolTip("Загрузить параметры из TOML-файла")
        self.save_button = QPushButton("Сохранить")
        self.save_button.setToolTip("Сохранить текущие параметры в TOML-файл")
        self.load_button.clicked.connect(self._on_load)
        self.save_button.clicked.connect(self._on_save)
        io_buttons.addWidget(self.load_button)
        io_buttons.addWidget(self.save_button)
        io_buttons.addStretch(1)
        layout.addLayout(io_buttons)

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить конфиг", "config.toml", "TOML (*.toml)")
        if not path:
            return
        try:
            from layoff_calculator.config import load_config, ConfigError
        except ImportError as e:
            QMessageBox.warning(self, "Недоступно",
                                f"Модуль конфигурации не найден: {e}")
            return
        try:
            params = load_config(path)
        except ConfigError as e:
            QMessageBox.critical(self, "Ошибка загрузки", str(e))
            return
        self.set_constants(params)

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить конфиг", "config.toml", "TOML (*.toml)")
        if not path:
            return
        try:
            from layoff_calculator.config import save_config, ConfigError
        except ImportError as e:
            QMessageBox.warning(self, "Недоступно",
                                f"Модуль конфигурации не найден: {e}")
            return
        try:
            save_config(path, self.get_constants())
        except (ConfigError, OSError) as e:
            QMessageBox.critical(self, "Ошибка сохранения", str(e))

    def get_constants(self) -> ConstantParams:
        return ConstantParams(
            machines=self.table.read_machines(),
            costs_per_hour_3=self.costs_3.value(),
            costs_per_hour_6=self.costs_6.value(),
            costs_per_hour_base=self.costs_base.value(),
        )

    def set_constants(self, params: ConstantParams) -> None:
        self.table.setRowCount(0)
        for m in params.machines:
            self.table.add_machine(m)
        self.costs_3.setValue(params.costs_per_hour_3)
        self.costs_6.setValue(params.costs_per_hour_6)
        self.costs_base.setValue(params.costs_per_hour_base)


# -------------------------------
# Simulation panel
# -------------------------------

class SimulationPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("ПАРАМЕТРЫ СИМУЛЯЦИИ", parent)
        form = QFormLayout(self)

        self.days = _NoWheelSpinBox()
        self.days.setRange(1, 100_000)
        self.days.setValue(200)
        form.addRow(_help_label("Продолжительность симуляции, дн.",
                    "Длительность одного прогона симуляции в днях."), self.days)

        self.strategy = _NoWheelComboBox()
        for strategy in RepairStrategy:
            self.strategy.addItem(strategy.name, strategy)
        form.addRow(_help_label("Стратегия починки",
                    "Порядок выбора машины для ремонта: FIFO (первым пришел - первым обслужен) или WSPT (взвешенное кратчайшее время)."), self.strategy)

        self.seed_enabled = QCheckBox()
        self.seed_enabled.setChecked(False)
        self.seed_value = _NoWheelSpinBox()
        self.seed_value.setRange(0, 2**31 - 1)
        self.seed_value.setValue(42)
        self.seed_enabled.toggled.connect(self.seed_value.setEnabled)
        self.seed_value.setEnabled(self.seed_enabled.isChecked())
        seed_row = QHBoxLayout()
        seed_row.addWidget(self.seed_enabled)
        seed_row.addWidget(self.seed_value, 1)
        form.addRow(_help_label("Зерно симуляции",
                    "Начальное значение генератора случайных чисел для воспроизводимости результатов."), seed_row)

        self.max_workers_enabled = QCheckBox()
        self.max_workers_enabled.setChecked(False)

        self.max_workers = _NoWheelSpinBox()
        self.max_workers.setRange(1, 256)
        self.max_workers.setValue(os.cpu_count() or 1)
        self.max_workers.setEnabled(self.max_workers_enabled.isChecked())

        self.max_workers_enabled.toggled.connect(self._on_workers_toggled)

        workers_row = QHBoxLayout()
        workers_row.addWidget(self.max_workers_enabled)
        workers_row.addWidget(self.max_workers, 1)
        form.addRow(_help_label("Макс. параллельных потоков",
                    "Количество одновременно работающих процессов (если галочка снята, используется количество ядер CPU)."), workers_row)

        self.hot_repair = QCheckBox("")
        self.hot_repair.setChecked(True)
        form.addRow(_help_label("Починка только в 3-ю смену",
                    "Если включено, ремонт машин происходит только в отведенную 3-ю смену."), self.hot_repair)

        self.auto_repair = QCheckBox("")
        self.auto_repair.setChecked(True)
        form.addRow(_help_label("Мгновенная починка в конце дня",
                    "Если включено, все сломанные машины бесплатно и мгновенно чинятся в конце рабочего дня."), self.auto_repair)

    def _on_workers_toggled(self, checked: bool) -> None:
        self.max_workers.setEnabled(checked)
        if not checked:
            self.max_workers.setValue(os.cpu_count() or 1)

    def get_simulation(self) -> SimulationParams:
        from layoff_calculator.engine import SimulationParams

        seed = (
            self.seed_value.value()
            if self.seed_enabled.isChecked()
            else random.randint(0, 2**31 - 1)
        )

        workers = (
            self.max_workers.value()
            if self.max_workers_enabled.isChecked()
            else (os.cpu_count() or 1)
        )

        return SimulationParams(
            days=self.days.value(),
            repair_strategy=self.strategy.currentData(),
            global_seed=seed,
            max_workers=workers,
            is_hot_repair_enabled=self.hot_repair.isChecked(),
            is_auto_repair_enabled=self.auto_repair.isChecked(),
        )

    def set_simulation(self, params: SimulationParams) -> None:
        self.days.setValue(params.days)
        idx = self.strategy.findData(params.repair_strategy)
        if idx >= 0:
            self.strategy.setCurrentIndex(idx)
        self.seed_enabled.setChecked(True)
        self.seed_value.setValue(params.global_seed)

        self.max_workers_enabled.setChecked(True)
        self.max_workers.setValue(params.max_workers)

        self.hot_repair.setChecked(params.is_hot_repair_enabled)
        self.auto_repair.setChecked(params.is_auto_repair_enabled)


# -------------------------------
# Runs panel
# -------------------------------

class RunsPanel(QGroupBox):
    run_requested = Signal(int)
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("ПРОГОНЫ", parent)
        self._busy = False

        form = QFormLayout(self)

        self.add_runs = _NoWheelSpinBox()
        self.add_runs.setRange(1, 10_000)
        self.add_runs.setValue(10)

        self.run_button = QPushButton("Добавить и запустить")
        self.run_button.setToolTip(
            "Запустить симуляцию для указанного количества новых прогонов")
        self.reset_button = QPushButton("Сбросить")
        self.reset_button.setToolTip(
            "Очистить результаты и разблокировать параметры")

        run_row = QHBoxLayout()
        run_row.addWidget(self.add_runs, 1)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.reset_button)
        form.addRow(_help_label("Добавить прогоны",
                    "Количество новых симуляций для запуска."), run_row)

        self.total_runs = _NoWheelSpinBox()
        self.total_runs.setRange(0, 10_000_000)
        self.total_runs.setReadOnly(True)
        self.total_runs.setButtonSymbols(QSpinBox.NoButtons)
        form.addRow(_help_label("Суммарные прогоны",
                    "Общее количество успешно завершенных симуляций."), self.total_runs)

        self.avg_benefit = _NoWheelDoubleSpinBox()
        self.avg_benefit.setRange(-1e15, 1e15)
        self.avg_benefit.setDecimals(2)
        self.avg_benefit.setReadOnly(True)
        self.avg_benefit.setButtonSymbols(QDoubleSpinBox.NoButtons)
        form.addRow(_help_label("Средняя выгода от увольнения, руб.",
                    "Средняя разница в прибыли: положительное значение означает выгоду от увольнения."), self.avg_benefit)

        self.variance = _ScientificDoubleSpinBox()
        self.variance.setRange(0.0, 1e30)
        self.variance.setDecimals(2)
        self.variance.setReadOnly(True)
        self.variance.setButtonSymbols(QDoubleSpinBox.NoButtons)
        form.addRow(_help_label(
            "Дисперсия", "Дисперсия разницы в прибыли. Показывает разброс результатов."), self.variance)

        self.bayesian_p = _NoWheelDoubleSpinBox()
        self.bayesian_p.setRange(0.0, 1.0)
        self.bayesian_p.setDecimals(4)
        self.bayesian_p.setReadOnly(True)
        self.bayesian_p.setButtonSymbols(QDoubleSpinBox.NoButtons)
        form.addRow(_help_label("Вероятность выгоды от увльнения",
                    "Вероятность того, что увольнение выгодно (0.5 = 50/50, 1.0 = 100% уверенность)."), self.bayesian_p)

        self.run_button.clicked.connect(self._on_run_clicked)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        self.reset_button.setEnabled(False)

    def _on_run_clicked(self) -> None:
        self.run_requested.emit(self.add_runs.value())

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.add_runs.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy and self.total_runs.value() > 0)

    def update_stats(self, total: int, avg: float, variance: float, p: float) -> None:
        if math.isnan(avg):
            avg = 0.0
        if math.isnan(variance):
            variance = 0.0
        if math.isnan(p):
            p = 0.5

        self.total_runs.setValue(total)
        self.avg_benefit.setValue(avg)
        self.variance.setValue(variance)
        self.bayesian_p.setValue(p)
        self.reset_button.setEnabled(not self._busy and total > 0)


# -------------------------------
# Simulation worker (QThread)
# -------------------------------

class SimulationWorker(QThread):
    """Submits runs to the engine's process pool and polls for completion."""

    # (completed, submitted, mean, variance, p)
    progress = Signal(int, int, float, float, float)
    # (completed, mean, variance, p)
    succeeded = Signal(object)
    failed = Signal(str)

    POLL_INTERVAL_S: float = 0.05

    def __init__(self, engine: Engine, count: int, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._count = count
        self._abort = False

    def stop(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            self._engine.make_runs(self._count)
            while (
                not self._abort
                and self._engine.completed_runs_count < self._engine.submitted_runs_count
            ):
                self._engine.check_pending_results()

                stdev = self._engine.layoff_profit_stdev
                variance = (
                    stdev ** 2) if not math.isnan(stdev) else float("nan")

                self.progress.emit(
                    self._engine.completed_runs_count,
                    self._engine.submitted_runs_count,
                    self._engine.layoff_profit_mean,
                    variance,
                    self._engine.layoff_profit_bayesian_p,
                )
                time.sleep(self.POLL_INTERVAL_S)

            if not self._abort:
                self._engine.check_pending_results()

                stdev = self._engine.layoff_profit_stdev
                variance = (
                    stdev ** 2) if not math.isnan(stdev) else float("nan")

                self.succeeded.emit((
                    self._engine.completed_runs_count,
                    self._engine.layoff_profit_mean,
                    variance,
                    self._engine.layoff_profit_bayesian_p,
                ))
        except Exception as exc:  # noqa: BLE001
            if not self._abort:
                self.failed.emit(str(exc))


# -------------------------------
# Main window
# -------------------------------

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Имитационное моделирование — слесари")
        self.resize(900, 800)

        self._engine: Engine | None = None
        self._worker: SimulationWorker | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        self.constants_panel = ConstantsPanel()
        self.simulation_panel = SimulationPanel()
        self.runs_panel = RunsPanel()
        layout.addWidget(self.constants_panel)
        layout.addWidget(self.simulation_panel)
        layout.addWidget(self.runs_panel)
        layout.addStretch(1)

        self.runs_panel.run_requested.connect(self._on_run_requested)
        self.runs_panel.reset_requested.connect(self._on_reset)

        self._load_defaults()

    def _load_defaults(self) -> None:
        defaults = [
            Machine("Экскаватор", 4, 500.0, 4.0, 2.0,      1.0, 0.25),
            Machine("Бульдозер",  6, 300.0, 6.0, math.inf, 2.0, 1.5),
            Machine("Автокран",   3, 650.0, 5.0, math.inf, 2.5, 1.5),
            Machine("Самосвал",   5, 400.0, 8.0, 2.5,      1.5, 0.75),
        ]
        self.constants_panel.set_constants(ConstantParams(
            machines=defaults,
            costs_per_hour_3=60.0,
            costs_per_hour_6=100.0,
            costs_per_hour_base=50.0,
        ))

    def _on_run_requested(self, count: int) -> None:
        if self._worker is not None:
            return

        if self._engine is None:
            try:
                from layoff_calculator.engine import Engine
            except ImportError as exc:
                QMessageBox.critical(
                    self, "Недоступно",
                    f"Модуль симуляции не найден: {exc}")
                return
            try:
                constants = self.constants_panel.get_constants()
                simulation = self.simulation_panel.get_simulation()
                self._engine = Engine(constants, simulation)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(
                    self, "Ошибка параметров",
                    f"Не удалось создать движок:\n{exc}")
                return

        self._lock_panels(True)
        self.runs_panel.set_busy(True)

        worker = SimulationWorker(self._engine, count)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_worker_succeeded)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_thread_done)
        self._worker = worker
        worker.start()

    def _on_progress(self, completed: int, submitted: int, mean: float, variance: float, p: float) -> None:
        self.runs_panel.update_stats(completed, mean, variance, p)

    def _on_worker_succeeded(self, stats: tuple) -> None:
        completed, mean, variance, p = stats
        self.runs_panel.update_stats(completed, mean, variance, p)
        self.runs_panel.set_busy(False)

    def _on_worker_failed(self, message: str) -> None:
        self.runs_panel.set_busy(False)
        if self._engine is not None and self._engine.completed_runs_count > 0:
            stdev = self._engine.layoff_profit_stdev
            variance = (stdev ** 2) if not math.isnan(stdev) else 0.0
            self.runs_panel.update_stats(
                self._engine.completed_runs_count,
                self._engine.layoff_profit_mean,
                variance,
                self._engine.layoff_profit_bayesian_p,
            )
        QMessageBox.critical(self, "Ошибка симуляции", message)

    def _on_worker_thread_done(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _on_reset(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if self._engine is not None:
            self._engine.close()
            self._engine = None
        self.runs_panel.update_stats(0, 0.0, 0.0, 0.5)
        self._lock_panels(False)

    def _lock_panels(self, locked: bool) -> None:
        self.constants_panel.setEnabled(not locked)
        self.simulation_panel.setEnabled(not locked)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(5000)

        if self._engine is not None:
            self._engine.close()
            self._engine = None

        super().closeEvent(event)


# -------------------------------
# Entry point
# -------------------------------

def main() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
