import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class MonitorService(QObject):
    metrics_updated = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._collect)
        self._gpu_handles = []
        self._gpu_available = False
        self._init_gpu()

    def _init_gpu(self):
        try:
            from pynvml import (
                nvmlInit,
                nvmlDeviceGetHandleByIndex,
                nvmlDeviceGetCount,
            )
            nvmlInit()
            count = nvmlDeviceGetCount()
            if count > 0:
                self._gpu_handles = [
                    nvmlDeviceGetHandleByIndex(i) for i in range(count)
                ]
                self._gpu_available = True
        except Exception:
            self._gpu_handles = []
            self._gpu_available = False

    def set_interval(self, ms):
        self._timer.setInterval(ms)

    def start(self):
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def is_gpu_available(self):
        return self._gpu_available

    def _collect(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        gpus = self._get_all_gpu_stats()
        self.metrics_updated.emit({
            "cpu": cpu,
            "ram_percent": mem.percent,
            "ram_used": mem.used,
            "ram_total": mem.total,
            "gpus": gpus,
        })

    def _get_all_gpu_stats(self):
        if not self._gpu_available:
            return []
        try:
            from pynvml import (
                nvmlDeviceGetUtilizationRates,
                nvmlDeviceGetMemoryInfo,
                nvmlDeviceGetName,
            )
            results = []
            for handle in self._gpu_handles:
                util = nvmlDeviceGetUtilizationRates(handle)
                mem = nvmlDeviceGetMemoryInfo(handle)
                name_raw = nvmlDeviceGetName(handle)
                if isinstance(name_raw, bytes):
                    name = name_raw.decode("utf-8", errors="replace")
                else:
                    name = name_raw
                results.append({
                    "name": name,
                    "util": util.gpu,
                    "mem_used": mem.used,
                    "mem_total": mem.total,
                })
            return results
        except Exception:
            return []
