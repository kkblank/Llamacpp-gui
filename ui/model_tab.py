import os
import time
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QFileDialog,
    QMessageBox, QProgressBar, QStackedWidget, QCheckBox, QSplitter,
    QAbstractItemView, QGroupBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from config.config import Settings
from service.modelscope import search_models, list_model_files, get_download_url, download_file
from model.download_entry import DownloadEntry, DownloadQueue


def _format_size(size_bytes):
    if size_bytes <= 0:
        return ""
    if size_bytes >= 10 ** 12:
        return f"{size_bytes / 10 ** 12:.1f}TB"
    if size_bytes >= 10 ** 9:
        return f"{size_bytes / 10 ** 9:.1f}GB"
    if size_bytes >= 10 ** 6:
        return f"{size_bytes / 10 ** 6:.1f}MB"
    return f"{size_bytes / 10 ** 3:.1f}KB"


def _format_params(params):
    if params <= 0:
        return ""
    if params >= 10 ** 9:
        return f"{params / 10 ** 9:.1f}B"
    return f"{params / 10 ** 6:.1f}M"


def _format_date(iso_str):
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso_str[:10]


class PauseException(Exception):
    pass


class DownloadWorker(QThread):
    progress_signal = pyqtSignal(str, int, int)
    speed_signal = pyqtSignal(str, float)
    finished_signal = pyqtSignal(str, bool, str)

    def __init__(self, url, dest_path, file_path, resume_pos=0):
        super().__init__()
        self.url = url
        self.dest_path = dest_path
        self.file_path = file_path
        self.resume_pos = resume_pos
        self._paused = False
        self._cancelled = False

    def run(self):
        last_time = time.time()
        last_bytes = self.resume_pos

        def on_chunk(current, total):
            nonlocal last_time, last_bytes
            if self._paused:
                raise PauseException
            if self._cancelled:
                raise StopIteration
            self.progress_signal.emit(self.file_path, current, total)
            now = time.time()
            elapsed = now - last_time
            if elapsed >= 1.0:
                speed = (current - last_bytes) / elapsed
                self.speed_signal.emit(self.file_path, speed)
                last_time = now
                last_bytes = current

        try:
            current, total = download_file(
                self.url, self.dest_path,
                resume_pos=self.resume_pos,
                chunk_callback=on_chunk,
            )
            if self._cancelled:
                if os.path.exists(self.dest_path):
                    os.remove(self.dest_path)
                self.finished_signal.emit(self.file_path, False, "已取消")
            else:
                self.finished_signal.emit(self.file_path, True, "")
        except PauseException:
            self.finished_signal.emit(self.file_path, False, "已暂停")
        except StopIteration:
            self.finished_signal.emit(self.file_path, False, "已取消")
        except Exception as e:
            self.finished_signal.emit(self.file_path, False, str(e))

    def pause(self):
        self._paused = True

    def cancel(self):
        self._cancelled = True


class ModelTab(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = Settings.get_instance()
        self.download_queue = DownloadQueue()
        self._workers = {}
        self._current_page = 1
        self._current_keyword = ""
        self._total_count = 0
        self._current_model_id = ""
        self._init_ui()
        self._restore_queue()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        layout.addWidget(self._build_search_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_results_page())
        self.stack.addWidget(self._build_filelist_page())
        self.stack.setCurrentIndex(0)
        top_layout.addWidget(self.stack)
        splitter.addWidget(top_widget)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(QLabel("下载队列"))
        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setHorizontalHeaderLabels(["文件名", "进度", "速度", "状态", "操作"])
        self.queue_table.horizontalHeader().setStretchLastSection(False)
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.queue_table.setColumnWidth(1, 160)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.queue_table.setColumnWidth(2, 80)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.queue_table.setColumnWidth(3, 70)
        self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.queue_table.setColumnWidth(4, 120)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        bottom_layout.addWidget(self.queue_table)
        splitter.addWidget(bottom_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    def _build_search_bar(self):
        bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索 ModelScope 模型...")
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self._do_search)
        bar.addWidget(self.search_input)
        bar.addWidget(self.search_btn)
        w = QWidget()
        w.setLayout(bar)
        return w

    def _build_results_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(["模型ID", "参数", "下载量", "更新日期", "操作"])
        self.result_table.horizontalHeader().setStretchLastSection(False)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(1, 80)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(2, 70)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(3, 100)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(4, 80)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.result_table)

        pagination_bar = QHBoxLayout()
        self.prev_btn = QPushButton("< 上一页")
        self.prev_btn.clicked.connect(self._prev_page)
        pagination_bar.addWidget(self.prev_btn)

        self.page_label = QLabel("第 0/0 页")
        pagination_bar.addWidget(self.page_label)
        pagination_bar.addStretch()

        self.next_btn = QPushButton("下一页 >")
        self.next_btn.clicked.connect(self._next_page)
        pagination_bar.addWidget(self.next_btn)

        w = QWidget()
        w.setLayout(pagination_bar)
        layout.addWidget(w)
        return page

    def _build_filelist_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        self.back_btn = QPushButton("← 返回搜索结果")
        self.back_btn.clicked.connect(self._back_to_results)
        top_bar.addWidget(self.back_btn)
        self.filelist_model_label = QLabel("")
        self.filelist_model_label.setStyleSheet("font-weight: bold;")
        top_bar.addWidget(self.filelist_model_label)
        top_bar.addStretch()
        w = QWidget()
        w.setLayout(top_bar)
        layout.addWidget(w)

        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(["", "文件名", "大小", "操作"])
        self.file_table.horizontalHeader().setStretchLastSection(False)
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.file_table.setColumnWidth(0, 30)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.file_table.setColumnWidth(2, 100)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.file_table.setColumnWidth(3, 80)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.file_table)

        dl_bar = QHBoxLayout()
        self.dl_path_edit = QLineEdit()
        self.dl_path_edit.setReadOnly(True)
        saved = self.settings.download_path
        if saved:
            self.dl_path_edit.setText(saved)
        self.dl_path_btn = QPushButton("选择...")
        self.dl_path_btn.clicked.connect(self._select_dl_path)
        dl_bar.addWidget(QLabel("下载目录:"))
        dl_bar.addWidget(self.dl_path_edit)
        dl_bar.addWidget(self.dl_path_btn)

        self.dl_selected_btn = QPushButton("下载选中项")
        self.dl_selected_btn.clicked.connect(self._download_selected)
        dl_bar.addWidget(self.dl_selected_btn)

        w2 = QWidget()
        w2.setLayout(dl_bar)
        layout.addWidget(w2)
        return page

    def _do_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入搜索关键词")
            return
        self._current_keyword = keyword
        self._current_page = 1
        self._load_search_page()

    def _load_search_page(self):
        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中...")
        result = search_models(self._current_keyword, self._current_page)
        self.search_btn.setEnabled(True)
        self.search_btn.setText("搜索")
        self._total_count = result.get("total_count", 0)
        models = result.get("models", [])
        page_size = result.get("page_size", 20)

        total_pages = max(1, (self._total_count + page_size - 1) // page_size)
        self.page_label.setText(f"第 {self._current_page}/{total_pages} 页")
        self.prev_btn.setEnabled(self._current_page > 1)
        self.next_btn.setEnabled(self._current_page < total_pages)

        self.result_table.setRowCount(0)
        for row, m in enumerate(models):
            self.result_table.insertRow(row)
            mid = m.get("id", "")
            self.result_table.setItem(row, 0, QTableWidgetItem(mid))
            self.result_table.setItem(row, 1, QTableWidgetItem(_format_params(m.get("params", 0))))
            self.result_table.setItem(row, 2, QTableWidgetItem(str(m.get("downloads", 0))))
            self.result_table.setItem(row, 3, QTableWidgetItem(_format_date(m.get("last_modified", ""))))

            view_btn = QPushButton("查看文件")
            view_btn.clicked.connect(lambda checked, x=mid: self._show_file_list(x))
            self.result_table.setCellWidget(row, 4, view_btn)

        self.stack.setCurrentIndex(0)

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._load_search_page()

    def _next_page(self):
        page_size = 20
        total_pages = max(1, (self._total_count + page_size - 1) // page_size)
        if self._current_page < total_pages:
            self._current_page += 1
            self._load_search_page()

    def _show_file_list(self, model_id):
        self._current_model_id = model_id
        self.filelist_model_label.setText(f"当前模型: {model_id}")
        self.filelist_model_label.setStyleSheet("font-weight: bold;")

        self.file_table.setRowCount(0)
        files = list_model_files(model_id)
        gguf_files = [f for f in files if f.get("Path", "").lower().endswith(".gguf")]

        if not gguf_files:
            self.file_table.insertRow(0)
            self.file_table.setItem(0, 1, QTableWidgetItem("该模型下没有 .gguf 文件"))
            self.stack.setCurrentIndex(1)
            return

        for row, f in enumerate(gguf_files):
            self.file_table.insertRow(row)
            cb = QCheckBox()
            w = QWidget()
            wl = QHBoxLayout(w)
            wl.addWidget(cb)
            wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wl.setContentsMargins(0, 0, 0, 0)
            self.file_table.setCellWidget(row, 0, w)

            self.file_table.setItem(row, 1, QTableWidgetItem(f.get("Path", "")))
            self.file_table.setItem(row, 2, QTableWidgetItem(_format_size(f.get("Size", 0))))

            dl_btn = QPushButton("下载")
            dl_btn.clicked.connect(
                lambda checked, x=model_id, p=f.get("Path", ""), s=f.get("Size", 0): self._start_single_download(x, p, s)
            )
            self.file_table.setCellWidget(row, 3, dl_btn)

        self.stack.setCurrentIndex(1)

    def _back_to_results(self):
        self.stack.setCurrentIndex(0)

    def _select_dl_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择模型下载目录")
        if path:
            self.dl_path_edit.setText(path)
            self.settings.download_path = path
            self.settings.save()

    def _download_selected(self):
        dl_path = self.dl_path_edit.text().strip()
        if not dl_path:
            QMessageBox.warning(self, "提示", "请先设置下载目录")
            return
        if not os.path.isdir(dl_path):
            QMessageBox.warning(self, "提示", "下载目录不存在")
            return

        started = 0
        for row in range(self.file_table.rowCount()):
            w = self.file_table.cellWidget(row, 0)
            if w is None:
                continue
            cb = w.findChild(QCheckBox)
            if cb and cb.isChecked():
                file_path = self.file_table.item(row, 1).text()
                size_text = self.file_table.item(row, 2).text()
                size = 0
                if size_text:
                    try:
                        if "GB" in size_text:
                            size = int(float(size_text.replace("GB", "")) * 10 ** 9)
                        elif "MB" in size_text:
                            size = int(float(size_text.replace("MB", "")) * 10 ** 6)
                        elif "KB" in size_text:
                            size = int(float(size_text.replace("KB", "")) * 10 ** 3)
                    except ValueError:
                        pass
                self._start_download(self._current_model_id, file_path, size, dl_path)
                started += 1
        if started == 0:
            QMessageBox.warning(self, "提示", "请先勾选要下载的文件")

    def _start_single_download(self, model_id, file_path, file_size):
        dl_path = self.dl_path_edit.text().strip()
        if not dl_path:
            QMessageBox.warning(self, "提示", "请先设置下载目录")
            return
        if not os.path.isdir(dl_path):
            QMessageBox.warning(self, "提示", "下载目录不存在")
            return
        self._start_download(model_id, file_path, file_size, dl_path)

    def _start_download(self, model_id, file_path, file_size, dl_path):
        existing = self.download_queue.find(model_id, file_path)
        active_worker = self._workers.get(file_path)
        if active_worker and active_worker.isRunning():
            QMessageBox.warning(self, "提示", "该文件已在下载队列中")
            return

        filename = os.path.basename(file_path)
        dest_path = os.path.join(dl_path, filename)

        if existing and existing.status in ("paused", "downloading", "pending"):
            entry = existing
            entry.status = "downloading"
            resume_pos = entry.downloaded
        elif existing and existing.status in ("completed", "failed", "cancelled"):
            entry = existing
            entry.status = "downloading"
            entry.downloaded = 0
            resume_pos = 0
        else:
            entry = DownloadEntry(
                model_id=model_id,
                file_path=file_path,
                file_size=file_size,
                dest_path=dest_path,
                downloaded=0,
                status="downloading",
            )
            self.download_queue.add(entry)

        url = get_download_url(model_id, file_path)
        resume_pos = entry.downloaded
        worker = DownloadWorker(url, dest_path, file_path, resume_pos)
        self._workers[file_path] = worker

        worker.progress_signal.connect(self._on_dl_progress)
        worker.speed_signal.connect(self._on_dl_speed)
        worker.finished_signal.connect(lambda fp, ok, err, e=entry: self._on_dl_finished(fp, ok, err, e))
        worker.start()
        self._add_queue_row(entry)
        self.download_queue.update(entry)

    def _add_queue_row(self, entry):
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item and item.text() == entry.filename and item.data(Qt.ItemDataRole.UserRole) == entry.file_path:
                self._update_queue_row(row, entry)
                self._set_queue_actions(row, entry)
                return

        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)

        name_item = QTableWidgetItem(entry.filename)
        name_item.setData(Qt.ItemDataRole.UserRole, entry.file_path)
        self.queue_table.setItem(row, 0, name_item)

        prog = QProgressBar()
        prog.setMinimum(0)
        prog.setMaximum(100)
        prog.setValue(entry.progress)
        self.queue_table.setCellWidget(row, 1, prog)

        self.queue_table.setItem(row, 2, QTableWidgetItem(""))
        self.queue_table.setItem(row, 3, QTableWidgetItem(entry.status))

        self._set_queue_actions(row, entry)

    def _update_queue_row(self, row, entry):
        prog = self.queue_table.cellWidget(row, 1)
        if isinstance(prog, QProgressBar):
            prog.setValue(entry.progress)
        self.queue_table.item(row, 3).setText(entry.status)

    def _set_queue_actions(self, row, entry):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        worker = self._workers.get(entry.file_path)
        if entry.status == "downloading" and worker and worker.isRunning():
            pause_btn = QPushButton("暂停")
            pause_btn.clicked.connect(lambda: self._pause_download(entry))
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(lambda: self._cancel_download(entry))
            layout.addWidget(pause_btn)
            layout.addWidget(cancel_btn)
        elif entry.status in ("paused", "pending", "downloading"):
            resume_btn = QPushButton("恢复" if entry.status in ("paused", "downloading") else "开始")
            resume_btn.clicked.connect(lambda: self._resume_download(entry))
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(lambda: self._cancel_download(entry))
            layout.addWidget(resume_btn)
            layout.addWidget(cancel_btn)
        elif entry.status in ("completed", "failed", "cancelled"):
            if entry.status == "failed":
                retry_btn = QPushButton("重试")
                retry_btn.clicked.connect(lambda: self._retry_download(entry))
                layout.addWidget(retry_btn)
            remove_btn = QPushButton("移除")
            remove_btn.clicked.connect(lambda: self._remove_queue_row(row, entry))
            layout.addWidget(remove_btn)

        self.queue_table.setCellWidget(row, 4, container)

    def _on_dl_progress(self, file_path, current, total):
        entry = self.download_queue.find(self._current_model_id, file_path)
        if entry:
            entry.downloaded = current
            if total > 0:
                entry.file_size = total
            self.download_queue.update(entry)
            for row in range(self.queue_table.rowCount()):
                item = self.queue_table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == file_path:
                    self._update_queue_row(row, entry)
                    break

    def _on_dl_speed(self, file_path, speed):
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == file_path:
                if speed >= 10 ** 6:
                    text = f"{speed / 10 ** 6:.1f}MB/s"
                else:
                    text = f"{speed / 10 ** 3:.1f}KB/s"
                self.queue_table.item(row, 2).setText(text)
                break

    def _on_dl_finished(self, file_path, success, error, entry):
        worker = self._workers.pop(file_path, None)
        if success:
            entry.status = "completed"
        elif error == "已暂停":
            entry.status = "paused"
        elif error == "已取消":
            entry.status = "cancelled"
        else:
            entry.status = "failed"
        entry.downloaded = os.path.getsize(entry.dest_path) if os.path.exists(entry.dest_path) else entry.downloaded
        self.download_queue.update(entry)

        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == file_path:
                self._update_queue_row(row, entry)
                self._set_queue_actions(row, entry)
                break

    def _pause_download(self, entry):
        worker = self._workers.get(entry.file_path)
        if worker:
            worker.pause()
            entry.status = "paused"
            self.download_queue.update(entry)
            for row in range(self.queue_table.rowCount()):
                item = self.queue_table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == entry.file_path:
                    self._update_queue_row(row, entry)
                    self._set_queue_actions(row, entry)
                    break

    def _cancel_download(self, entry):
        worker = self._workers.get(entry.file_path)
        if worker:
            worker.cancel()
        entry.status = "cancelled"
        if os.path.exists(entry.dest_path):
            try:
                os.remove(entry.dest_path)
            except OSError:
                pass
        entry.downloaded = 0
        self.download_queue.update(entry)
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == entry.file_path:
                self._update_queue_row(row, entry)
                self._set_queue_actions(row, entry)
                break

    def _resume_download(self, entry):
        dl_path = self.dl_path_edit.text().strip() or os.path.dirname(entry.dest_path)
        self._start_download(entry.model_id, entry.file_path, entry.file_size, dl_path)

    def _retry_download(self, entry):
        entry.downloaded = 0
        self.download_queue.update(entry)
        dl_path = self.dl_path_edit.text().strip() or os.path.dirname(entry.dest_path)
        self._start_download(entry.model_id, entry.file_path, entry.file_size, dl_path)

    def _remove_queue_row(self, row, entry):
        self.queue_table.removeRow(row)
        self.download_queue.remove(entry)
        self._workers.pop(entry.file_path, None)
        if entry.dest_path and os.path.exists(entry.dest_path):
            try:
                os.remove(entry.dest_path)
            except OSError:
                pass

    def _restore_queue(self):
        for entry in self.download_queue.pending_downloads():
            self._add_queue_row(entry)
