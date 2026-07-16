# AGENTS.md

LlamaCPP GUI —— 一个基于 PyQt6 的桌面客户端（仅支持 Windows 10/11），用于管理本地的
llama.cpp 推理服务器。仅面向 Windows 平台。

## 运行

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

程序入口：`main.py` → `ui.app.main()`。本仓库没有命令行工具或 Web 服务。

## 容易被忽略的约定

- **仅支持 Windows。** 生成的启动脚本是 Windows `.bat` 文件
  （`model/script.py` 生成 `data/scripts/*.bat`）；不要把相关逻辑改写成 POSIX shell。
- **配置为单例模式。** 应用配置位于 `config/config.py`，通过
  `Settings.get_instance()` 访问（懒加载自 `data/app_config.json`）。不要直接
  实例化 `Settings()` —— 始终使用单例。
- **`data/` 是运行时状态，不是源码。** 已被 gitignore，首次运行时自动创建
  （配置文件、已保存脚本、下载队列、`last_pid.pid`）。不要提交它。
- **没有测试、CI 或 lint/typecheck。** 均未配置。修改后应通过手动运行 GUI 验证
  （需要 PyQt6 和真实显示环境）。
- **GPU 监控仅支持 NVIDIA。** 通过 `nvidia-ml-py` 实现；未检测到显卡时在监控页
  会优雅降级显示。

## 打包

使用 PyInstaller 打包独立 `.exe`，**在 PowerShell 中执行**（见 `打包命令.txt`）：

```powershell
pyinstaller -D -w --name='Lammacpp启动器' main.py
```

产物位于 `dist/Lammacpp启动器/`。

## 项目结构（职责划分）

- `ui/` —— PyQt6 窗口与标签页：`app.py`（主窗口 + 控制标签页）、`model_tab.py`、
  `monitor_tab.py`
- `service/` —— 后端逻辑：`path_service`、`script_service`、
  `process_service`（服务生命周期）、`modelscope`（模型搜索/下载）、
  `monitor_service`（CPU/内存/GPU 采样）
- `model/` —— 纯数据模型（`script.py`、`download_entry.py`）
- `config/` —— `config.py` 单例
- `utils/` —— `logger.py`、`validator.py`
