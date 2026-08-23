# PaperMiner 1.4.5 软件版

## 发布与安装

正式发布包只有一个 `Setup.exe`。它内部包含完整程序载荷；不要从安装载荷目录手工复制 EXE。

1. 双击 `Setup.exe`。
2. 选择安装位置；默认位置是 `%LOCALAPPDATA%\Programs\PaperMiner`。也可选择 `D:\PaperMiner`、`E:\Apps\PaperMiner` 等任意可写的非 C 盘子目录，但不能直接选择磁盘根目录。
3. 安装器解包后打开 PowerShell 日志窗口，完成 MinerU 环境安装或修复。
4. 安装阶段不会自动启动主程序。
5. 安装完成后，安装目录中才会出现 `PaperMiner.exe` 和 `Uninstall.exe`，桌面会生成 PaperMiner 快捷方式。

Conda 主程序和 `MinerU` 环境可以位于不同磁盘。Setup 通过 `conda env list --json` 获取环境的真实路径，不再假设环境必须位于 `<Conda根>\envs\MinerU`。

## 正常运行

`PaperMiner.exe` 直接通过 `pythonw.exe` 启动 `scripts\batch_pdf_processor_gui.py`，主界面就是原“运行程序”打开的 GUI。

- 正常启动不调用 PowerShell、`run.bat` 或 `运行程序.bat`，不会出现外部命令窗口。
- v1.4.3 会在无控制台启动时补建 UTF-8 标准输出流，兼容 MinerU 的 `doclayout_yolo` 日志初始化。
- “合并同名章节和图表到 Markdown”会继续按章节名称生成独立汇总文件，并把每篇论文 `Word` 文件夹中的 Markdown 合并为 `图表汇总_合并.md`；合并时会自动改写图片和表格的相对路径。
- 不检查后自动安装，也不把安装和运行串联起来。
- 启动环境、Python 路径、模型源、处理进度和异常统一显示在软件主界面的日志区。
- 主界面采用配置 / 任务 / 实时日志三栏横向看板，分隔线可拖动；窄屏仍保留常驻日志。
- 界面由 `ttkbootstrap 2.x` 渲染；Setup 内置 2.2.2 wheel，并会自动安装或升级该依赖。
- 同样的日志按 UTF-8 写入 `logs\PaperMiner_*.log`，避免中文乱码。
- 输入和输出目录可在主界面分别选择；路径保存在 `%LOCALAPPDATA%\PaperMiner\settings.json`，升级后仍然有效。
- 长批次每篇结束后会回收 Python/CUDA 临时内存并记录占用变化；原生崩溃堆栈也会尽可能写入同一日志文件。
- MinerU 对每篇 PDF 使用独立进程；单篇发生 CUDA/原生库硬崩溃时，主界面会记录退出码并保留其余批处理队列。
- 安装和启动时均验证 MinerU 必须为 `>=3.1.0,<4.0`；已存在的 2.x 环境会由重装流程升级，不再直接跳过。
- PowerShell 仅用于 Setup、重装和卸载阶段。

## 重装与卸载

运行 `Uninstall.exe`。主界面只有三个操作按钮：

- `取消`：不做任何更改并退出。
- `重装`：仅移除名为 `MinerU` 的 Conda 环境，然后重新进入已安装的依赖安装阶段。
- `卸载`：移除 `MinerU` 环境、运行记录、Windows 卸载登记和本程序桌面快捷方式。

重装和卸载均保留模型缓存、项目源码、`.env`、`input`、`output` 与历史日志。应用目录不会被自动递归删除；确认数据后可由用户手工处理。

## 数据安全

- Setup 更新现有安装时，不把 `.env`、运行时记录、`input`、`output` 或 `logs` 放入安装载荷，因此不会覆盖这些可变数据。
- 被更新的旧程序文件会备份到 `%LOCALAPPDATA%\PaperMiner\SetupBackups\时间戳`。
- 安装载荷拒绝绝对路径、`..` 路径穿越和磁盘根目录安装。

联系邮箱：`2878705044@qq.com`
