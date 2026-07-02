import sys
import os
import json
import re
import urllib.request
import webbrowser
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QTextEdit,
    QListWidget, QListWidgetItem, QMessageBox, QSplitter, QTabWidget,
    QFileDialog, QInputDialog, QDialog, QCheckBox, QFormLayout,
    QDialogButtonBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from config.config import Settings
from service.path_service import validate_llamacpp_file, validate_gguf_file
from service.script_service import ScriptService
from service.process_service import ProcessService
from service.monitor_service import MonitorService
from model.script import ScriptEntry
from ui.model_tab import ModelTab
from ui.monitor_tab import MonitorTab


class NewScriptDialog(QDialog):
    CATEGORIES = [
        {
            "title": "通用参数",
            "note": "",
            "checked": True,
            "switches": [
                {"key": "gpu_layers", "label": "--gpu-layers (GPU 层数)", "default": "99"},
                {"key": "port", "label": "--port (端口号)", "default": "8080"},
                {"key": "ctx_size", "label": "--ctx-size (上下文大小)", "default": "32768"},
                {"key": "alias", "label": "--alias (模型别名)", "default": "qwen"},
                {"key": "host", "label": "--host (监听地址)", "default": "0.0.0.0"},
            ],
        },
        {
            "title": "模型参数",
            "note": "",
            "checked": False,
            "switches": [
                {"key": "no_mmproj_offload", "label": "--no-mmproj-offload (不加载视觉模型)", "default": ""},
                {"key": "mmproj", "label": "--mmproj (是否启用外挂视觉模型)", "default": ""},
                {"key": "reasoning", "label": "--reasoning off (关闭模型思考)", "default": ""},
                {"key": "main_gpu", "label": "--main-gpu (指定主推理gpu，单显卡忽略该参数)", "default": "0"},
                {"key": "ts", "label": "-ts (混合gpu负载, 例如1,3，意思为两张显卡负载比例为1:3，单显卡忽略该参数)", "default": "1,3"},
            ],
        },
        {
            "title": "MTP 参数",
            "note": "需要支持MTP的模型才能开启",
            "checked": False,
            "switches": [
                {"key": "spec_type", "label": "--spec-type (是否开启MTP预测-需模型支持)", "default": "draft-mtp"},
                {"key": "spec_draft_n_max", "label": "--spec-draft-n-max (额外预测token数)", "default": "2"},
            ],
        },
        {
            "title": "模型量化参数",
            "note": "",
            "checked": True,
            "switches": [
                {"key": "cache_type_k", "label": "--cache-type-k (是否开启k量化)", "default": "q8_0"},
                {"key": "cache_type_v", "label": "--cache-type-v (是否开启v量化)", "default": "q8_0"},
            ],
        },
        {
            "title": "MOE 模型参数",
            "note": "如果你不清楚什么是MOE模型，则下列参数均保持默认就好",
            "checked": False,
            "switches": [
                {"key": "n_cpu_moe", "label": "--n-cpu-moe (分配cpu线程数，需小于等于cpu物理核心数)", "default": "", "show_input": True},
                # {"key": "moe_router_type", "label": "--moe-router-type (指定MOE路由类型)", "default": "topk"},
                # {"key": "top_k", "label": "--top-k (激活专家数)", "default": "9"},
                {"key": "mmap", "label": "--mmap (启用内存映射，动态加载权重)", "default": "", "checked": True},
                {"key": "no_mmap_fallback", "label": "--no-mmap-fallback (禁用回退加载模式，但可能导致显存爆炸，可尝试开启)", "default": ""},
            ],
        },
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建启动脚本 - 选择参数")
        self.setFixedWidth(620)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        tip = QLabel("勾选需要启用的参数，并填写对应值，需要注意llama.cpp版本，某些参数需要新版才能支持。如果发现某些参数启用后报错，则需要升级llamacpp版本，或者关闭该参数。")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        self.checkboxes = {}
        self.value_inputs = {}

        for cat in self.CATEGORIES:
            if cat["title"]:
                label = QLabel(cat["title"])
                label.setStyleSheet(
                    "font-weight: bold; font-size: 12px; padding: 8px 0 2px 0;"
                )
                form.addRow(label)

            if cat["note"]:
                note = QLabel(cat["note"])
                note.setStyleSheet(
                    "color: #cc6600; font-size: 11px; padding: 0 0 4px 0;"
                )
                note.setWordWrap(True)
                form.addRow(note)

            for sw in cat["switches"]:
                cb = QCheckBox(sw["label"])
                cb.setChecked(sw.get("checked", cat["checked"]))
                self.checkboxes[sw["key"]] = cb

                if sw.get("show_input", sw["default"] != ""):
                    val_widget = QLineEdit(sw["default"])
                else:
                    val_widget = None
                self.value_inputs[sw["key"]] = val_widget

                row = QHBoxLayout()
                row.addWidget(cb)
                if val_widget:
                    row.addWidget(val_widget)
                row.addStretch()

                form_row = QWidget()
                form_row.setLayout(row)
                form.addRow(form_row)

        scroll = QWidget()
        scroll.setLayout(form)
        scroll_area = QScrollArea()
        scroll_area.setMinimumHeight(300)
        scroll_area.setWidget(scroll)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_config(self):
        result = {}
        for cat in self.CATEGORIES:
            for sw in cat["switches"]:
                cb = self.checkboxes[sw["key"]]
                if cb.isChecked():
                    if sw.get("show_input", sw["default"] != ""):
                        val = self.value_inputs[sw["key"]].text().strip()
                        if not val:
                            continue
                    else:
                        val = ""
                    result[sw["key"]] = val
        return result


class LogWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    server_ready_signal = pyqtSignal(str)
    tps_signal = pyqtSignal(float)

    def __init__(self, bat_path, process_service):
        super().__init__()
        self.bat_path = bat_path
        self.process_service = process_service
        self._running = False
        self._url_emitted = False
        self._url_pattern = re.compile(r"https?://\d+\.\d+\.\d+\.\d+:\d+")
        self._tps_pattern = re.compile(
            r"([\d.]+)\s+tokens?\s+per\s+second"
        )

    def run(self):
        self._running = True
        result = self.process_service.start_script(self.bat_path)
        if result["success"]:
            self.log_signal.emit(f"进程已启动，PID: {result['pid']}")
        else:
            self.log_signal.emit(f"启动失败: {result.get('error', '未知错误')}")

        while self._running:
            line = self.process_service.read_output()
            if line:
                if not self._url_emitted:
                    m = self._url_pattern.search(line)
                    if m:
                        self._url_emitted = True
                        self.server_ready_signal.emit(m.group())
                tps_m = self._tps_pattern.search(line)
                if tps_m:
                    try:
                        self.tps_signal.emit(float(tps_m.group(1)))
                    except ValueError:
                        pass
                self.log_signal.emit(line)
            if not self.process_service.is_process_alive():
                break
            self.msleep(200)

        self.log_signal.emit("进程已结束")
        self.finished_signal.emit()


class CheckUpdateWorker(QThread):
    result_signal = pyqtSignal(str, str)

    def run(self):
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
                headers={"User-Agent": "llamacpp-gui/1.0", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                published = data.get("published_at", "")
                if published:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    self.result_signal.emit(dt.strftime("%Y-%m-%d"), "")
                    return
            self.result_signal.emit("", "未能获取到版本信息")
        except Exception as e:
            self.result_signal.emit("", str(e))


class CheckAppUpdateWorker(QThread):
    result_signal = pyqtSignal(str, str)

    def run(self):
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/kkblank/Llamacpp-gui/releases/latest",
                headers={"User-Agent": "llamacpp-gui/1.0", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                published = data.get("published_at", "")
                if published:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    self.result_signal.emit(dt.strftime("%Y-%m-%d"), "")
                    return
            self.result_signal.emit("", "未能获取到版本信息")
        except Exception as e:
            self.result_signal.emit("", str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.get_instance()
        self.script_service = ScriptService()
        self.process_service = ProcessService()
        self.current_script_name = ""
        self.is_running = False
        self.log_worker = None
        self._server_url = ""

        self.setWindowTitle("llama.cpp GUI Client")
        self.resize(960, 700)

        self.monitor_service = MonitorService()
        self.monitor_tab = MonitorTab(self.monitor_service)

        self._init_ui()
        self._load_saved_paths()

        self.monitor_service.start()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        tabs = QTabWidget()

        # 主控制标签
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)

        # 路径配置面板
        control_layout.addWidget(self._create_path_panel())

        # 脚本管理面板
        control_layout.addWidget(self._create_script_panel())

        # 控制面板
        control_layout.addWidget(self._create_control_panel())

        # 日志面板
        control_layout.addWidget(self._create_log_panel(), stretch=1)

        tabs.addTab(control_widget, "主控制")

        # 模型搜索与下载标签
        self.model_tab = ModelTab()
        tabs.addTab(self.model_tab, "模型搜索与下载")

        # 性能监控标签
        tabs.addTab(self.monitor_tab, "性能监控")

        main_layout.addWidget(tabs)

    def _create_path_panel(self):
        group = QGroupBox("路径配置")
        layout = QVBoxLayout(group)

        # llama.cpp 路径
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("llama-server.exe 路径:"))
        self.llamacpp_path_edit = QLineEdit()
        self.llamacpp_path_edit.setReadOnly(True)
        row1.addWidget(self.llamacpp_path_edit)
        browse_btn1 = QPushButton("选择...")
        browse_btn1.clicked.connect(self._select_llamacpp_path)
        row1.addWidget(browse_btn1)
        layout.addLayout(row1)

        # 模型文件路径
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("模型文件 (.gguf):"))
        self.model_path_edit = QLineEdit()
        self.model_path_edit.setReadOnly(True)
        row2.addWidget(self.model_path_edit)
        browse_btn2 = QPushButton("选择...")
        browse_btn2.clicked.connect(self._select_model_file)
        row2.addWidget(browse_btn2)
        layout.addLayout(row2)

        # 外挂视觉模型路径
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("外挂视觉模型 (.gguf):"))
        self.visual_model_path_edit = QLineEdit()
        self.visual_model_path_edit.setReadOnly(True)
        row3.addWidget(self.visual_model_path_edit)
        browse_btn3 = QPushButton("选择...")
        browse_btn3.clicked.connect(self._select_visual_model_file)
        row3.addWidget(browse_btn3)
        layout.addLayout(row3)

        return group

    def _create_script_panel(self):
        group = QGroupBox("启动脚本")
        layout = QHBoxLayout(group)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：脚本列表 + 操作按钮
        left_layout = QVBoxLayout()
        self.script_list = QListWidget()
        self.script_list.currentItemChanged.connect(self._on_script_selected)
        left_layout.addWidget(self.script_list)

        btn_layout = QHBoxLayout()
        new_btn = QPushButton("新建")
        new_btn.clicked.connect(self._new_script)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_script)
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._delete_script)
        btn_layout.addWidget(new_btn)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(delete_btn)
        left_layout.addLayout(btn_layout)

        left_panel = QWidget()
        left_panel.setLayout(left_layout)

        # 右侧：脚本内容编辑器
        self.script_editor = QTextEdit()
        self.script_editor.setPlaceholderText("在此输入启动脚本内容。")

        splitter.addWidget(left_panel)
        splitter.addWidget(self.script_editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)
        return group

    def _create_control_panel(self):
        group = QGroupBox("控制面板")
        layout = QHBoxLayout(group)

        self.run_btn = QPushButton("运行")
        self.run_btn.clicked.connect(self._run_script)
        layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("结束")
        self.stop_btn.clicked.connect(self._stop_script)
        layout.addWidget(self.stop_btn)

        self.status_label = QLabel("● 就绪")
        self.status_label.setStyleSheet(
            "color: green; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self.status_label)

        self.chat_btn = QPushButton("聊天窗口")
        self.chat_btn.setEnabled(False)
        self.chat_btn.clicked.connect(self._open_chat_window)
        layout.addWidget(self.chat_btn)

        layout.addStretch()

        self.check_update_btn = QPushButton("检查llama.cpp更新")
        self.check_update_btn.clicked.connect(self._check_update)
        layout.addWidget(self.check_update_btn)

        self.update_date_label = QLabel("")
        self.update_date_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.update_date_label)

        self.check_app_update_btn = QPushButton("检查软件更新")
        self.check_app_update_btn.clicked.connect(self._check_app_update)
        layout.addWidget(self.check_app_update_btn)

        self.app_update_date_label = QLabel("")
        self.app_update_date_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.app_update_date_label)

        return group

    def _create_log_panel(self):
        group = QGroupBox("日志输出")
        layout = QVBoxLayout(group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.log_text.clear)
        btn_layout.addWidget(clear_btn)
        layout.addLayout(btn_layout)

        return group

    def _load_saved_paths(self):
        if self.settings.llamacpp_path:
            self.llamacpp_path_edit.setText(self.settings.llamacpp_path)
        if self.settings.model_path:
            self.model_path_edit.setText(self.settings.model_path)
        if self.settings.visual_model_path:
            self.visual_model_path_edit.setText(self.settings.visual_model_path)
        self._refresh_script_list()

    def _select_llamacpp_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 llama-server.exe", "", "Executable Files (*.exe)"
        )
        if path:
            if validate_llamacpp_file(path):
                self.llamacpp_path_edit.setText(path)
                self.settings.llamacpp_path = path
                self.settings.save()
                self._append_log(f"llama-server.exe 路径已设置: {path}")
            else:
                QMessageBox.warning(
                    self, "验证失败",
                    "请选择 llama-server.exe 文件。",
                )

    def _select_model_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 GGUF 模型文件", "", "GGUF Files (*.gguf)"
        )
        if path:
            if validate_gguf_file(path):
                self.model_path_edit.setText(path)
                self.settings.model_path = path
                self.settings.save()
                self._append_log(f"模型文件已设置: {path}")
            else:
                QMessageBox.warning(self, "验证失败", "请选择 .gguf 格式的模型文件。")

    def _select_visual_model_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择外挂视觉模型文件", "", "GGUF Files (*.gguf)"
        )
        if path:
            if validate_gguf_file(path):
                self.visual_model_path_edit.setText(path)
                self.settings.visual_model_path = path
                self.settings.save()
                self._append_log(f"外挂视觉模型已设置: {path}")
            else:
                QMessageBox.warning(self, "验证失败", "请选择 .gguf 格式的模型文件。")

    def _refresh_script_list(self):
        self.script_list.clear()
        scripts = self.script_service.load_scripts()
        for script in scripts:
            self.script_list.addItem(script.name)

    def _on_script_selected(self, current, previous):
        if current:
            name = current.text()
            self.current_script_name = name
            content = self.script_service.load_script_content(name)
            self.script_editor.setPlainText(content)

    def _new_script(self):
        self.current_script_name = ""
        self.script_list.clearSelection()
        llamacpp_path = self.settings.llamacpp_path
        model_path = self.settings.model_path

        if not llamacpp_path or not model_path:
            QMessageBox.warning(
                self, "提示",
                "请先设置 llama-server.exe 和模型文件的路径。",
            )
            self.script_editor.clear()
            self.script_editor.setPlaceholderText(
                "请先在上方路径配置中选择 llama-server.exe 和 .gguf 模型文件。"
            )
            return

        name, ok = QInputDialog.getText(self, "新建脚本", "请输入脚本名称:")
        if not ok or not name:
            return

        exe_dir = os.path.dirname(llamacpp_path)
        dialog = NewScriptDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.get_config()
            bat_content = self._build_bat_content(exe_dir, model_path, config)
            self.script_editor.setPlainText(bat_content)
            self.current_script_name = name
            entry = ScriptEntry(name=name, content=bat_content, model_path=model_path)
            bat_path = self.script_service.save_script(entry)
            self._refresh_script_list()
            item = self.script_list.findItems(name, Qt.MatchFlag.MatchExactly)
            if item:
                self.script_list.setCurrentItem(item[0])
            self._append_log(f"脚本已新建并保存: {bat_path}")

    def _build_bat_content(self, exe_dir, model_path, config):
        lines = [
            "@echo off",
            f'cd /d "{exe_dir}"',
            "llama-server.exe ^",
            f'-m "{model_path}" ^',
        ]

        parts = []
        if "gpu_layers" in config:
            parts.append(f"--gpu-layers {config['gpu_layers']} ^")
        if "port" in config:
            parts.append(f"--port {config['port']} ^")
        if "ctx_size" in config:
            parts.append(f"--ctx-size {config['ctx_size']} ^")
        if "alias" in config:
            parts.append(f'--alias "{config["alias"]}" ^')
        if "no_mmproj_offload" in config:
            parts.append("--no-mmproj-offload ^")
        if "mmproj" in config:
            vpath = self.settings.visual_model_path
            if vpath:
                parts.append(f'--mmproj "{vpath}" ^')
        if "reasoning" in config:
            parts.append("--reasoning off ^")
        if "main_gpu" in config:
            parts.append(f"--main-gpu {config['main_gpu']} ^")
        if "ts" in config:
            parts.append(f"-ts {config['ts']} ^")
        if "spec_type" in config:
            parts.append(f"--spec-type {config['spec_type']} ^")
        if "spec_draft_n_max" in config:
            parts.append(f"--spec-draft-n-max {config['spec_draft_n_max']} ^")
        if "cache_type_k" in config:
            parts.append(f"--cache-type-k {config['cache_type_k']} ^")
        if "cache_type_v" in config:
            parts.append(f"--cache-type-v {config['cache_type_v']} ^")
        if "n_cpu_moe" in config:
            parts.append(f"--n-cpu-moe {config['n_cpu_moe']} ^")
        if "moe_router_type" in config:
            parts.append(f"--moe-router-type {config['moe_router_type']} ^")
        if "top_k" in config:
            parts.append(f"--top-k {config['top_k']} ^")
        if "mmap" in config:
            parts.append("--mmap ^")
        if "no_mmap_fallback" in config:
            parts.append("--no-mmap-fallback ^")
        if "host" in config:
            parts.append(f"--host {config['host']}")

        lines.extend(parts)
        return "\n".join(lines)

    def _save_script(self):
        if self.current_script_name:
            content = self.script_editor.toPlainText()
            if not content.strip():
                QMessageBox.warning(self, "提示", "脚本内容为空，无法保存。")
                return
            entry = ScriptEntry(
                name=self.current_script_name,
                content=content,
                model_path=self.settings.model_path,
            )
            bat_path = self.script_service.save_script(entry)
            if bat_path:
                self._append_log(f"脚本已保存: {bat_path}")
        else:
            name, ok = QInputDialog.getText(self, "保存脚本", "请输入脚本名称:")
            if ok and name:
                content = self.script_editor.toPlainText()
                entry = ScriptEntry(name=name, content=content, model_path=self.settings.model_path)
                bat_path = self.script_service.save_script(entry)
                if bat_path:
                    self._refresh_script_list()
                    item = self.script_list.findItems(name, Qt.MatchFlag.MatchExactly)
                    if item:
                        self.script_list.setCurrentItem(item[0])
                    self._append_log(f"脚本已保存: {bat_path}")

    def _delete_script(self):
        current = self.script_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择一个脚本。")
            return
        name = current.text()
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除脚本 '{name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.script_service.delete_script(name)
            self._refresh_script_list()
            self.script_editor.clear()
            self.current_script_name = ""
            self._append_log(f"脚本已删除: {name}")

    def _run_script(self):
        if self.is_running:
            QMessageBox.warning(self, "提示", "已有进程在运行，请先结束。")
            return

        if not self.current_script_name:
            if self.script_list.count() > 0:
                self.script_list.setCurrentRow(0)
                if not self.current_script_name:
                    return
            else:
                QMessageBox.warning(self, "提示", "没有可运行的脚本，请先新建脚本。")
                return

        content = self.script_editor.toPlainText()
        if not content.strip():
            QMessageBox.warning(self, "提示", "脚本内容为空，请先编写或生成脚本。")
            return

        bat_path = self.script_service.get_script_path(self.current_script_name)
        if not os.path.exists(bat_path):
            # 如果脚本文件不存在，先保存
            entry = ScriptEntry(
                name=self.current_script_name,
                content=content,
                model_path=self.settings.model_path,
            )
            bat_path = self.script_service.save_script(entry)

        self._server_url = ""
        self.chat_btn.setEnabled(False)
        self.log_worker = LogWorker(bat_path, self.process_service)
        self.log_worker.log_signal.connect(self._append_log)
        self.log_worker.server_ready_signal.connect(self._on_server_ready)
        self.log_worker.tps_signal.connect(self.monitor_tab.update_tps)
        self.log_worker.finished.connect(self._on_run_finished)
        self.log_worker.finished.connect(self.monitor_tab.on_server_stopped)
        self.log_worker.start()

        self.is_running = True
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("● 运行中")
        self.status_label.setStyleSheet(
            "color: orange; font-size: 12px; font-weight: bold;"
        )
        self.monitor_tab.on_server_started()

    def _on_server_ready(self, url):
        url = url.replace("0.0.0.0", "127.0.0.1")
        self._server_url = url
        self.chat_btn.setEnabled(True)
        self._append_log(f"检测到服务已就绪: {url}")

    def _on_run_finished(self):
        self.is_running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.chat_btn.setEnabled(False)
        self.status_label.setText("● 就绪")
        self.status_label.setStyleSheet(
            "color: green; font-size: 12px; font-weight: bold;"
        )

    def _open_chat_window(self):
        if self._server_url:
            webbrowser.open(self._server_url)
            self._append_log(f"已打开浏览器: {self._server_url}")

    def _stop_script(self):
        if not self.is_running:
            return

        result = self.process_service.stop_all()
        if result["pid_stopped"] or result["name_stopped"]:
            self._append_log("进程已终止")
        else:
            self._append_log("尝试终止进程，但可能未找到相关进程")

        self.is_running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.chat_btn.setEnabled(False)
        self.status_label.setText("● 就绪")
        self.status_label.setStyleSheet(
            "color: green; font-size: 12px; font-weight: bold;"
        )

    def _check_update(self):
        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("检查中...")
        self.update_date_label.setText("")
        self.worker = CheckUpdateWorker()
        self.worker.result_signal.connect(self._on_update_result)
        self.worker.start()

    def _on_update_result(self, date_str, error_msg):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("检查llama.cpp更新")
        if date_str:
            self.update_date_label.setText(f"最后更新: {date_str}")
            self._append_log(f"llama.cpp 最新版本发布日期: {date_str}")
        else:
            self.update_date_label.setText("获取失败")
            reason = f"检查llama.cpp更新失败: {error_msg}" if error_msg else "检查llama.cpp更新失败，请检查网络连接"
            self._append_log(reason)

    def _check_app_update(self):
        self.check_app_update_btn.setEnabled(False)
        self.check_app_update_btn.setText("检查中...")
        self.app_update_date_label.setText("")
        self.app_worker = CheckAppUpdateWorker()
        self.app_worker.result_signal.connect(self._on_app_update_result)
        self.app_worker.start()

    def _on_app_update_result(self, date_str, error_msg):
        self.check_app_update_btn.setEnabled(True)
        self.check_app_update_btn.setText("检查软件更新")
        if date_str:
            self.app_update_date_label.setText(f"最新发行: {date_str}")
            self._append_log(f"软件最新版本发布日期: {date_str}")
        else:
            self.app_update_date_label.setText("获取失败")
            reason = f"检查软件更新失败: {error_msg}" if error_msg else "检查软件更新失败，请检查网络连接"
            self._append_log(reason)

    def _append_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
