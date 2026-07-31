"""llama.cpp GUI 主窗口。"""
import sys
import os
import webbrowser
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QTextEdit,
    QListWidget, QListWidgetItem, QMessageBox, QSplitter, QTabWidget,
    QFileDialog, QInputDialog, QDialog,
    QSystemTrayIcon, QMenu, QStyle,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from config.config import Settings
from utils.validator import validate_llamacpp_file, validate_gguf
from service.script_service import ScriptService
from service.script_builder import build_bat_content
from service.process_service import ProcessService
from service.monitor_service import MonitorService
from service.path_service import ensure_webui
from chat import start_bridge
from model.script import ScriptEntry
from ui.model_tab import ModelTab
from ui.monitor_tab import MonitorTab
from ui.dialogs.new_script_dialog import NewScriptDialog
from ui.workers.log_worker import LogWorker
from ui.workers.update_workers import CheckUpdateWorker, CheckAppUpdateWorker


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
        self._bridge_server = None
        self._bridge_port = None
        # 是否真正退出（托盘菜单「退出」触发时为 True，此时 closeEvent 走完整清理）
        self._really_quit = False
        # 系统托盘图标，必须持有引用防止被 GC 回收导致图标消失
        self.tray_icon = None

        self.setWindowTitle("llama.cpp GUI Client")
        self.resize(960, 700)

        self.monitor_service = MonitorService()
        self.monitor_tab = MonitorTab(self.monitor_service)

        self._init_ui()
        self._load_saved_paths()

        self.monitor_service.start()
        ensure_webui()
        self._start_bridge()
        self._init_tray()

    def closeEvent(self, event):
        # 仅当真正退出（托盘菜单「退出」）或系统托盘不可用时才关闭窗口，
        # 否则拦截关闭事件：隐藏到系统托盘，程序继续后台运行。
        if self._really_quit or self.tray_icon is None:
            self._cleanup()
            event.accept()
            # setQuitOnLastWindowClosed(False) 下窗口关闭不会自动退出，
            # 此处必须显式退出事件循环，否则进程会无窗口挂起。
            QApplication.instance().quit()
            return

        event.ignore()
        self.hide()
        self._show_tray_message()

    def _cleanup(self):
        """程序真正退出前的完整清理流程。

        依次：停止 llama-server 子进程 → 等待工作线程结束 →
        关闭聊天桥 HTTP 服务 → 停止性能监控定时器。
        该流程与原有 closeEvent 的清理逻辑保持一致，并补全了
        子进程/线程的收尾，避免退出后残留后台进程。
        """
        # 1. 停止 llama-server 等子进程（若仍在运行）
        if self.is_running:
            result = self.process_service.stop_all()
            if result["pid_stopped"] or result["name_stopped"]:
                self._append_log("退出：已终止 llama-server 进程")
            else:
                self._append_log("退出：未发现需要终止的进程")
            self.is_running = False

        # 2. 等待日志工作线程结束（进程被杀后其 run 循环会自行退出）
        if self.log_worker is not None and self.log_worker.isRunning():
            self.log_worker.wait(3000)

        # 3. 等待版本检查线程结束（最多等 2 秒，避免阻塞退出）
        for attr in ("worker", "app_worker"):
            w = getattr(self, attr, None)
            if w is not None and w.isRunning():
                w.wait(2000)

        # 4. 关闭聊天桥 HTTP 服务
        if self._bridge_server:
            try:
                self._bridge_server.shutdown()
            except Exception as e:
                self._append_log(f"退出：聊天桥关闭异常: {e}")
            self._bridge_server = None

        # 5. 停止性能监控定时器
        self.monitor_service.stop()

    def _init_tray(self):
        """初始化系统托盘图标与右键菜单。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._append_log("系统托盘不可用，关闭窗口将直接退出程序")
            return

        # 项目暂无自定义图标资源，复用系统标准图标（计算机图标），
        # 若后续有 app.ico 可替换为 QIcon("app.ico")。
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("llama.cpp GUI Client")

        # 右键菜单：显示主界面 / 退出
        self.tray_menu = QMenu()
        show_action = self.tray_menu.addAction("显示主界面")
        show_action.triggered.connect(self._show_main_window)
        self.tray_menu.addSeparator()
        quit_action = self.tray_menu.addAction("退出")
        quit_action.triggered.connect(self._quit_app)
        self.tray_icon.setContextMenu(self.tray_menu)

        # 单击 / 双击托盘图标 → 恢复显示主窗口
        self.tray_icon.activated.connect(self._on_tray_activated)

        self.tray_icon.show()
        self._append_log("系统托盘已启用，关闭窗口将最小化到托盘")

    def _show_main_window(self):
        """从托盘恢复显示主窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        """托盘图标被单击/双击时恢复主窗口。"""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_main_window()

    def _quit_app(self):
        """托盘菜单「退出」：走完整退出清理流程后真正退出程序。"""
        self._really_quit = True
        # 若窗口可见则通过 closeEvent 完成清理；若已隐藏在托盘则直接清理
        if self.isVisible():
            self.close()
        else:
            self._cleanup()
        # 隐藏托盘图标，避免退出后系统托盘残留图标
        if self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.instance().quit()

    def _show_tray_message(self):
        """关闭窗口隐藏到托盘时弹出一次托盘气泡提示。"""
        try:
            self.tray_icon.showMessage(
                "llama.cpp GUI Client",
                "程序已最小化到系统托盘，仍将继续后台运行。",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        except Exception:
            pass

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

        control_layout.addWidget(self._create_path_panel())
        control_layout.addWidget(self._create_script_panel())
        control_layout.addWidget(self._create_control_panel())
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

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("llama-server.exe 路径:"))
        self.llamacpp_path_edit = QLineEdit()
        self.llamacpp_path_edit.setReadOnly(True)
        row1.addWidget(self.llamacpp_path_edit)
        browse_btn1 = QPushButton("选择...")
        browse_btn1.clicked.connect(self._select_llamacpp_path)
        row1.addWidget(browse_btn1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("模型文件 (.gguf):"))
        self.model_path_edit = QLineEdit()
        self.model_path_edit.setReadOnly(True)
        row2.addWidget(self.model_path_edit)
        browse_btn2 = QPushButton("选择...")
        browse_btn2.clicked.connect(self._select_model_file)
        row2.addWidget(browse_btn2)
        layout.addLayout(row2)

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

        self.status_label = QLabel("\u25cf 就绪")
        self.status_label.setStyleSheet(
            "color: green; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self.status_label)

        self.chat_btn = QPushButton("聊天窗口")
        self.chat_btn.setEnabled(True)
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
            if validate_gguf(path):
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
            if validate_gguf(path):
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
            bat_content = build_bat_content(
                exe_dir, model_path, config,
                visual_model_path=self.settings.visual_model_path,
            )
            self.script_editor.setPlainText(bat_content)
            self.current_script_name = name
            entry = ScriptEntry(name=name, content=bat_content, model_path=model_path)
            bat_path = self.script_service.save_script(entry)
            self._refresh_script_list()
            item = self.script_list.findItems(name, Qt.MatchFlag.MatchExactly)
            if item:
                self.script_list.setCurrentItem(item[0])
            self._append_log(f"脚本已新建并保存: {bat_path}")

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
            entry = ScriptEntry(
                name=self.current_script_name,
                content=content,
                model_path=self.settings.model_path,
            )
            bat_path = self.script_service.save_script(entry)

        self._server_url = ""
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
        self.status_label.setText("\u25cf 运行中")
        self.status_label.setStyleSheet(
            "color: orange; font-size: 12px; font-weight: bold;"
        )
        self.monitor_tab.on_server_started()

    def _on_server_ready(self, url):
        url = url.replace("0.0.0.0", "127.0.0.1")
        self._server_url = url
        self._append_log(f"检测到服务已就绪: {url}")

    def _on_run_finished(self):
        self.is_running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("\u25cf 就绪")
        self.status_label.setStyleSheet(
            "color: green; font-size: 12px; font-weight: bold;"
        )

    def _open_chat_window(self):
        if self._bridge_port:
            url = f"http://127.0.0.1:{self._bridge_port}/chat.html"
            webbrowser.open(url)
            self._append_log(f"已打开聊天页面: {url}")
        else:
            QMessageBox.warning(self, "提示", "聊天桥服务未启动。")

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
        self.status_label.setText("\u25cf 就绪")
        self.status_label.setStyleSheet(
            "color: green; font-size: 12px; font-weight: bold;"
        )

    def _start_bridge(self):
        try:
            self._bridge_server, self._bridge_port = start_bridge()
            self._append_log(f"聊天桥服务已启动，端口: {self._bridge_port}")
        except Exception as e:
            self._bridge_server = None
            self._bridge_port = None
            self._append_log(f"聊天桥服务启动失败: {e}")

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
    app.setFont(QFont())
    # 关键：默认 setQuitOnLastWindowClosed(True)，主窗口隐藏到托盘后
    # 若无其他窗口，应用会自动退出 —— 必须改为 False 才能常驻托盘。
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
