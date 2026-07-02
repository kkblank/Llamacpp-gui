import time
from collections import deque

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QProgressBar, QComboBox, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QPainter
from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis


def _bar_style(pct):
    if pct >= 80:
        return "QProgressBar::chunk { background: #e74c3c; border-radius: 3px; }" \
               "QProgressBar { border: 1px solid #bbb; border-radius: 4px; text-align: center; min-height: 18px; }"
    if pct >= 50:
        return "QProgressBar::chunk { background: #f39c12; border-radius: 3px; }" \
               "QProgressBar { border: 1px solid #bbb; border-radius: 4px; text-align: center; min-height: 18px; }"
    return "QProgressBar::chunk { background: #27ae60; border-radius: 3px; }" \
           "QProgressBar { border: 1px solid #bbb; border-radius: 4px; text-align: center; min-height: 18px; }"


def _fmt_bytes(n):
    if n >= 10 ** 12:
        return f"{n / 10 ** 12:.1f}TB"
    if n >= 10 ** 9:
        return f"{n / 10 ** 9:.1f}GB"
    if n >= 10 ** 6:
        return f"{n / 10 ** 6:.1f}MB"
    return f"{n / 10 ** 3:.1f}KB"


class GpuCard(QFrame):
    def __init__(self, index, name, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        header = QLabel(f"GPU {index} ({name})")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        self.util_bar = QProgressBar()
        self.util_bar.setRange(0, 100)
        self.util_bar.setFixedHeight(18)
        self.util_label = QLabel("0%")
        self.util_label.setFixedWidth(60)
        util_row = QHBoxLayout()
        util_row.addWidget(QLabel("  利用率"))
        util_row.addWidget(self.util_bar, 1)
        util_row.addWidget(self.util_label)
        util_row.setSpacing(8)
        layout.addLayout(util_row)

        self.mem_bar = QProgressBar()
        self.mem_bar.setRange(0, 100)
        self.mem_bar.setFixedHeight(18)
        self.mem_label = QLabel("0 / 0 GB")
        self.mem_label.setFixedWidth(150)
        mem_row = QHBoxLayout()
        mem_row.addWidget(QLabel("  显存  "))
        mem_row.addWidget(self.mem_bar, 1)
        mem_row.addWidget(self.mem_label)
        mem_row.setSpacing(8)
        layout.addLayout(mem_row)

    def update(self, util_pct, mem_used, mem_total):
        self.util_bar.setValue(int(util_pct))
        self.util_bar.setStyleSheet(_bar_style(util_pct))
        self.util_label.setText(f"{util_pct:.0f}%")

        pct = (mem_used / mem_total * 100) if mem_total > 0 else 0
        self.mem_bar.setValue(int(pct))
        self.mem_bar.setStyleSheet(_bar_style(pct))
        self.mem_label.setText(f"{_fmt_bytes(mem_used)} / {_fmt_bytes(mem_total)}")


class TpsChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = deque(maxlen=300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._series = QLineSeries()
        self._chart = QChart()
        self._chart.addSeries(self._series)
        self._chart.legend().hide()
        self._chart.setTitle("推理速度 (最近 60 秒)")

        self._axis_x = QValueAxis()
        self._axis_x.setRange(0, 60)
        self._axis_x.setLabelFormat("%d")
        self._axis_x.setTitleText("秒")
        self._axis_x.setTickCount(7)
        self._chart.addAxis(self._axis_x, Qt.AlignmentFlag.AlignBottom)

        self._axis_y = QValueAxis()
        self._axis_y.setRange(0, 100)
        self._axis_y.setLabelFormat("%.0f")
        self._axis_y.setTitleText("t/s")
        self._chart.addAxis(self._axis_y, Qt.AlignmentFlag.AlignLeft)

        self._series.attachAxis(self._axis_x)
        self._series.attachAxis(self._axis_y)

        self._view = QChartView(self._chart)
        layout.addWidget(self._view)

    def add_tps(self, tps):
        now = time.time()
        self._data.append((now, tps))
        self._refresh()

    def _refresh(self):
        now = time.time()
        cutoff = now - 60
        while self._data and self._data[0][0] < cutoff:
            self._data.popleft()

        self._series.clear()
        if not self._data:
            return

        max_tps = max(v for _, v in self._data)
        self._axis_y.setRange(0, max_tps * 1.2 if max_tps > 0 else 100)

        win_start = cutoff if len(self._data) > 1 else self._data[0][0]
        for ts, tps in self._data:
            self._series.append(ts - win_start, tps)


class MonitorTab(QWidget):
    FREQ_OPTIONS = [
        ("0.5 秒", 500),
        ("1 秒 (默认)", 1000),
        ("2 秒", 2000),
    ]

    def __init__(self, monitor_service, parent=None):
        super().__init__(parent)
        self._service = monitor_service
        self._server_running = False
        self._server_start_time = 0.0
        self._gpu_cards = []

        self._setup_ui()
        self._service.metrics_updated.connect(self._on_metrics)

        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._update_uptime)
        self._uptime_timer.setInterval(1000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(self._build_top_bar())
        layout.addWidget(self._build_system_group())

        self._gpu_group = QGroupBox("GPU")
        self._gpu_inner = QVBoxLayout(self._gpu_group)
        self._gpu_inner.setContentsMargins(8, 8, 8, 8)
        self._gpu_inner.setSpacing(4)
        self._gpu_placeholder = QLabel("未检测到 NVIDIA GPU")
        self._gpu_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gpu_placeholder.setStyleSheet("color: #888; padding: 16px;")
        if not self._service.is_gpu_available():
            self._gpu_inner.addWidget(self._gpu_placeholder)
        layout.addWidget(self._gpu_group)

        bottom = QHBoxLayout()
        bottom.addWidget(self._build_status_group())
        self._tps_chart = TpsChart()
        bottom.addWidget(self._tps_chart, 2)
        layout.addLayout(bottom)

    def _build_top_bar(self):
        w = QWidget()
        bar = QHBoxLayout(w)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("采样频率:"))
        self._freq = QComboBox()
        for label, val in self.FREQ_OPTIONS:
            self._freq.addItem(label, val)
        self._freq.setCurrentIndex(1)
        self._freq.setToolTip("数值越小，刷新越频繁，系统开销略增")
        self._freq.currentIndexChanged.connect(self._on_freq_changed)
        bar.addWidget(self._freq)
        bar.addStretch()
        return w

    def _build_system_group(self):
        group = QGroupBox("系统资源")
        grid = QGridLayout(group)
        grid.setVerticalSpacing(6)

        self._cpu_bar = QProgressBar()
        self._cpu_bar.setRange(0, 100)
        self._cpu_text = QLabel("0%")
        self._cpu_text.setFixedWidth(60)
        grid.addWidget(QLabel("CPU"), 0, 0)
        grid.addWidget(self._cpu_bar, 0, 1)
        grid.addWidget(self._cpu_text, 0, 2)

        self._ram_bar = QProgressBar()
        self._ram_bar.setRange(0, 100)
        self._ram_text = QLabel("0%  0 / 0 GB")
        self._ram_text.setFixedWidth(200)
        grid.addWidget(QLabel("RAM"), 1, 0)
        grid.addWidget(self._ram_bar, 1, 1)
        grid.addWidget(self._ram_text, 1, 2)

        return group

    def _build_status_group(self):
        group = QGroupBox("服务器状态")
        v = QVBoxLayout(group)

        self._tps_label = QLabel("推理速度: -- t/s")
        self._tps_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        v.addWidget(self._tps_label)

        self._uptime_label = QLabel("运行时长: --")
        v.addWidget(self._uptime_label)

        self._status_label = QLabel("状态: \u25cf 未运行")
        self._status_label.setStyleSheet("color: #888; font-weight: bold;")
        v.addWidget(self._status_label)

        v.addStretch()
        return group

    def _on_freq_changed(self, index):
        self._service.set_interval(self._freq.currentData())

    @pyqtSlot(float)
    def update_tps(self, tps):
        self._tps_label.setText(f"推理速度: {tps:.1f} t/s")
        self._tps_chart.add_tps(tps)

    def on_server_started(self):
        self._server_running = True
        self._server_start_time = time.time()
        self._status_label.setText("状态: \u25cf 运行中")
        self._status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        self._uptime_timer.start()

    def on_server_stopped(self):
        self._server_running = False
        self._status_label.setText("状态: \u25cf 未运行")
        self._status_label.setStyleSheet("color: #888; font-weight: bold;")
        self._uptime_label.setText("运行时长: --")
        self._uptime_timer.stop()

    def _update_uptime(self):
        if self._server_running:
            e = time.time() - self._server_start_time
            h, r = divmod(int(e), 3600)
            m, s = divmod(r, 60)
            self._uptime_label.setText(f"运行时长: {h:02d}:{m:02d}:{s:02d}")

    @pyqtSlot(dict)
    def _on_metrics(self, m):
        cpu = m["cpu"]
        self._cpu_bar.setValue(int(cpu))
        self._cpu_bar.setStyleSheet(_bar_style(cpu))
        self._cpu_text.setText(f"{cpu:.0f}%")

        rp = m["ram_percent"]
        self._ram_bar.setValue(int(rp))
        self._ram_bar.setStyleSheet(_bar_style(rp))
        self._ram_text.setText(f"{rp:.0f}%  {_fmt_bytes(m['ram_used'])} / {_fmt_bytes(m['ram_total'])}")

        self._update_gpus(m.get("gpus", []))

    def _update_gpus(self, gpus):
        if not gpus:
            if not self._gpu_placeholder.parent():
                for c in self._gpu_cards:
                    c.setParent(None)
                    c.deleteLater()
                self._gpu_cards.clear()
                self._gpu_inner.addWidget(self._gpu_placeholder)
                self._gpu_placeholder.show()
            return

        if self._gpu_placeholder.parent():
            self._gpu_inner.removeWidget(self._gpu_placeholder)
            self._gpu_placeholder.hide()

        while len(self._gpu_cards) < len(gpus):
            i = len(self._gpu_cards)
            card = GpuCard(i, gpus[i]["name"], self._gpu_group)
            self._gpu_cards.append(card)
            self._gpu_inner.addWidget(card)

        while len(self._gpu_cards) > len(gpus):
            c = self._gpu_cards.pop()
            c.setParent(None)
            c.deleteLater()

        for i, info in enumerate(gpus):
            self._gpu_cards[i].update(info["util"], info["mem_used"], info["mem_total"])
