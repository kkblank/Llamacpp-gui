# LlamaCPP GUI

  
  


LlamaCPP GUI 是一个基于 PyQt6 的桌面图形界面客户端，专为 [llama.cpp](https://github.com/ggml-org/llama.cpp) 打造。它提供了完整的本地大语言模型推理服务器管理功能，让你无需命令行即可配置、启动和管理 llama.cpp 推理服务。

## 功能特性

### 核心功能

- **路径配置**：可视化选择 `llama-server.exe` 和本地 `.gguf` 模型文件路径，自动验证文件有效性，配置跨会话持久化保存。
- **启动脚本管理**：

  - 通过引导式参数选择对话框创建新脚本，支持分类参数配置（通用参数、模型参数、MTP 参数、量化参数、MOE 参数）
  - 内置脚本编辑器，可直接查看和修改生成的 `.bat` 脚本内容
  - 支持脚本的保存、删除和加载，所有脚本持久化存储在本地

- **推理服务器控制**：

  - 一键启动/停止 llama.cpp 推理服务器
  - 实时后台日志监控，自动检测服务器就绪状态
  - 服务器就绪后自动启用"聊天窗口"按钮，一键在浏览器中打开 Web UI

- **模型搜索与下载（ModelScope）**：

  - 集成 ModelScope AI 模型社区，支持关键词搜索模型
  - 分页浏览搜索结果，显示参数量、下载次数等关键信息
  - 浏览模型仓库中的文件列表，快速定位 `.gguf` 模型文件
  - 支持断点续传的分块下载，实时显示下载进度和速度
  - 下载队列管理，支持暂停、恢复、取消和重试操作

- **版本更新检查**：

  - 检查 llama.cpp 最新版本（GitHub）
  - 检查本应用最新版本（GitHub）

- **性能监控面板**：
  - 实时显示 CPU 使用率、内存使用率，带阈值变色进度条
  - 多 GPU 监控：每张显卡的利用率和显存占用，支持多卡
  - 推理速度（tokens/s）实时数据 + 60 秒滚动折线图
  - 服务器运行时长记录
  - 采样频率可调（0.5 秒 / 1 秒 / 2 秒）

### 支持的推理参数

| 类别     | 参数                                                                                                                                                |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 通用参数 | GPU 层数 (`--gpu-layers`)、端口 (`--port`)、上下文大小 (`--ctx-size`)、别名 (`--alias`)、主机 (`--host`)                                            |
| 模型参数 | 不卸载多模态投影 (`--no-mmproj-offload`)、多模态投影模型 (`--mmproj`)、推理模式 (`--reasoning off`)、主 GPU (`--main-gpu`)、多 GPU 负载均衡 (`-ts`) |
| MTP 参数 | 指定类型 (`--spec-type`)、草稿长度 (`--spec-draft-n-max`)                                                                                           |
| 量化参数 | KV 缓存类型 (`--cache-type-k`)、V 缓存类型 (`--cache-type-v`)                                                                                       |
| MOE 参数 | CPU MOE 层数 (`--n-cpu-moe`)、内存映射 (`--mmap`)、禁用 mmap 回退 (`--no-mmap-fallback`)                                                            |

## 系统要求

- **操作系统**：Windows 10/11
- **Python**：3.10 或更高版本
- **依赖**：PyQt6 >= 6.5、psutil >= 5.9、nvidia-ml-py >= 12.0、PyQt6-Charts >= 6.5

## 安装指南

### 从源码运行

1. **克隆项目仓库**

   ```bash
   git clone https://github.com/kkblank/Llamacpp-gui.git
   cd Llamacpp-gui
   ```

2. **安装依赖**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **启动应用**

   ```bash
   python main.py
   ```


### 打包为独立可执行文件

如果你希望在没有 Python 环境的机器上运行，可以使用 PyInstaller 打包：

```bash
pip install pyinstaller
pyinstaller -D -w --name='Lammacpp启动器' main.py
```

打包完成后，可在 `dist/Lammacpp启动器/` 目录中找到独立的 `Lammacpp启动器.exe` 文件，无需安装 Python 即可运行。

## 使用说明

### 首次使用

1. **配置 llama-server 路径**

   - 在主控制标签页中，点击"llama-server.exe 路径"旁的"选择..."按钮
   - 浏览并选择你的 `llama-server.exe` 文件
   - 该路径会自动保存到配置文件中

2. **配置模型文件路径**

   - 点击"模型文件 (.gguf)"旁的"选择..."按钮
   - 选择你要使用的 `.gguf` 格式模型文件
   - 可选：配置视觉模型路径以支持多模态推理

3. **创建启动脚本**

   - 点击"新建"按钮，输入脚本名称
   - 在弹出的参数选择对话框中，勾选需要的参数类别和具体参数
   - 确认后会生成对应的 `.bat` 启动脚本

4. **启动推理服务器**

   - 从脚本列表中选择一个已保存的脚本
   - 点击"运行"按钮启动服务器
   - 在下方日志窗口查看启动过程和实时输出
   - 服务器就绪后，点击"聊天窗口"按钮在浏览器中打开 Web UI

5. **搜索和下载模型**

   - 切换到"模型搜索与下载"标签页
   - 在搜索框中输入关键词（如模型名称、架构类型等）
   - 点击"搜索"按钮查找模型
   - 点击模型旁的"查看文件"按钮浏览该模型的可用文件
   - 选择下载目录，点击"下载"或"下载选中项"开始下载
   - 下载完成后，将下载的模型路径配置到应用中即可使用

6. **性能监控**

   - 切换到"性能监控"标签页
   - 系统资源区实时显示 CPU 和内存使用率，进度条按阈值变色（绿 < 50% / 橙 < 80% / 红 ≥ 80%）
   - GPU 区域显示每张显卡的利用率和显存占用，无显卡时显示"未检测到 NVIDIA GPU"
   - 启动推理服务器后，服务器状态区自动显示推理速度和运行时长
   - TPS 折线图展示最近 60 秒的推理速度趋势
   - 可通过顶部的"采样频率"下拉框调整数据刷新频率


### 配置文件位置

应用的所有持久化数据存储在 `data/` 目录下：

| 文件路径                    | 说明                       |
| --------------------------- | -------------------------- |
| `data/app_config.json`      | 应用配置（路径设置等）     |
| `data/scripts.json`         | 已保存的启动脚本索引       |
| `data/scripts/*.bat`        | 各启动脚本的实际批处理文件 |
| `data/downloads/queue.json` | 下载队列状态               |
| `data/last_pid.pid`         | 当前运行的服务器进程 ID    |

## 项目结构

````
llamacpp-gui/
├── main.py                      # 应用入口
├── requirements.txt             # Python 依赖
├── config/
│   └── config.py                # 应用配置管理（单例模式）
├── model/
│   ├── script.py                # 启动脚本数据模型
│   └── download_entry.py        # 下载条目数据模型
├── service/
│   ├── path_service.py          # 路径验证服务
│   ├── script_service.py        # 脚本管理服务
│   ├── process_service.py       # 进程管理服务
│   ├── modelscope.py            # ModelScope API 集成
│   └── monitor_service.py       # 性能数据采集服务（CPU/内存/GPU）
├── ui/
│   ├── app.py                   # 主窗口和主控制标签页
│   ├── model_tab.py             # 模型搜索与下载标签页
│   └── monitor_tab.py           # 性能监控标签页
├── utils/
│   ├── logger.py                # 日志工具
│   └── validator.py             # 验证工具
└── data/                        # 运行时数据目录
    ├── app_config.json
    ├── scripts.json
    ├── scripts/
    └── downloads/
````

## 许可证

MIT License