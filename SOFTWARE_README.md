# PaperMiner 1.4.21 软件版

## 发布与安装

正式发布包只有一个 `Setup.exe`。它内部包含完整程序载荷；不要从安装载荷目录手工复制 EXE。

1. 双击 `Setup.exe`。
2. 等待 Setup 依次检查明确传入的 Conda 路径和 PaperMiner 已保存的运行环境配置。检测到时只显示复用路径。
3. 自动检测不到时，可直接勾选“我确认本机没有 Conda”；也可先选择“检测此目录”或“全盘检索 Conda”进行额外核查。全盘检索是用户主动触发的只读操作，不是安装前置条件。
4. 选择 PaperMiner 安装位置和（无 Conda 时的）Anaconda 下载目标。两个目录不能重叠或直接使用磁盘根目录。
5. 安装器解包后打开 PowerShell 日志窗口；没有 Conda 时先从中国镜像下载并校验 Anaconda，再完成 MinerU 环境安装或修复。
6. 安装阶段不会自动启动主程序。
7. 安装完成后，安装目录中才会出现 `PaperMiner.exe` 和 `Uninstall.exe`，桌面会生成 PaperMiner 快捷方式。Setup 底部“安装”位于左侧，“取消”位于右侧；Enter 安装、Esc 取消。

Conda 主程序和 `MinerU` 环境可以位于不同磁盘。Setup 优先复用已有 Conda；新电脑没有 Conda 时，对清华、北外、南大和 Anaconda 官方源读取短样本测速，优先使用当前网络最快的可用来源，下载并校验 Anaconda 2026.07-1，再安装到用户在 Setup 中指定的独立目录。下载源失败或持续过慢时会自动切换。MinerU 环境路径来自 Conda JSON，不假设固定在 `<Conda根>\envs\MinerU`。

自动下载约 1.04 GiB，SHA-256 必须等于 `b545f4bd8ab3bf32d99002a0779a887668ebfe479ee32ecbf060375670d5ee09`。PaperMiner 与 Anaconda 目录不能重叠；已有 Conda 时不会使用或创建备用 Anaconda 目录。

安装 MinerU 前会并行测试清华、阿里云、中科大、腾讯和 PyPI 官方索引的短 wheel 样本，只使用测速最快的单一索引；镜像缺包或未同步时重试官方 PyPI。PyTorch CUDA 主 wheel 仍来自 PyTorch 官方仓库，普通依赖可以从测速选出的 PyPI 源获取。

GPU 阶段会列出每张 NVIDIA 显卡的型号、显存和驱动版本。二进制 PyTorch wheel 已包含所需 CUDA 用户态运行库和 cuDNN，Setup 不安装完整 CUDA Toolkit，也不静默修改系统显卡驱动。驱动缺失或版本过旧时先安装 CPU 版并显示 NVIDIA 官方驱动地址；驱动就绪后运行“重装”即可切换。安装后日志显示 PyTorch、CUDA runtime、cuDNN 和全部可用 GPU，并以 `torch.cuda.is_available()` 作为最终判定。

## 正常运行

`PaperMiner.exe` 直接通过 `pythonw.exe` 启动 `scripts\batch_pdf_processor_gui.py`，主界面就是原“运行程序”打开的 GUI。

- 正常启动不调用 PowerShell、`run.bat` 或 `运行程序.bat`，不会出现外部命令窗口。
- `PaperMiner.exe` 持有单实例锁；双击或连续点击不会创建第二个 GUI。
- 启动器在后台监护 GUI，并通过 Windows 作业对象保证 GUI 结束后回收仍存活的 MinerU 后代进程。
- v1.4.17 在 `%LOCALAPPDATA%\PaperMiner\recovery\runs.db` 保存 SQLite WAL 批次队列，并在每篇提取目录原子写入 `.paperminer-complete.json`。
- GUI 异常退出后，启动器在 2 秒后自动重启并续跑未完成文献；已完成的不重跑，当时正在处理的 PDF 从头重跑。
- 批次未完成时，中断输出移到 `<输出目录>\Recovery\Interrupted` 暂存；10 分钟内闪退 3 次后停止自动重启。
- v1.4.18 会在批次仍未完成时继续保留上述半成品；当全部文献已完成、失败或跳过后，只删除当前批次 ID 对应的暂存目录。`raw`、`extract` 正式结果和其他批次不会被清理。
- 正常关闭或“停止”会把未完成批次保存为暂停；下次启动由用户确认是否继续。
- v1.4.3 会在无控制台启动时补建 UTF-8 标准输出流，兼容 MinerU 的 `doclayout_yolo` 日志初始化。
- “代码与数据可用性”会识别文末代码仓库、数据集声明、可见 URL 和 PDF 隐藏超链接；`doi.org` 与出版商 DOI 端点不收录。
- 已配置 LLM 时，只发送候选 URL 和局部上下文进行 `code / data / both / ignore` 分类，模型不能补写地址；未配置或调用失败时使用本地规则。
- 只有至少一个可信地址时才生成 `OpenSource/代码与数据可用性.md`；空结果仅保留 `availability_scan.json` 完成标记。
- “文末参考文献（Markdown）”优先读取 MinerU `content_list.json` 的 `ref_text` 条目，并在 `References/参考文献.md` 中保留原始顺序和编号；结构缺失时才使用严格的 Markdown 标题或文末连续编号兜底。
- 参考文献不会交给 LLM 重写；扫描状态保存在 `References/references_scan.json`，即使没有可信条目也不会在启用“跳过已有结果”后反复扫描。
- “合并同名章节、图表、代码/数据地址和参考文献”会继续按章节名称生成独立汇总文件，把每篇论文 `Word` 文件夹中的 Markdown 合并为 `图表汇总_合并.md`，把非空可用性报告合并为 `代码与数据可用性_合并.md`，并把有效的逐篇参考文献报告按论文分组合并为 `参考文献_合并.md`；图表合并时会自动改写图片和表格的相对路径。
- 不检查后自动安装，也不把安装和运行串联起来。
- 启动环境、Python 路径、模型源、处理进度和异常统一显示在软件主界面的日志区。
- 主界面采用配置 / 任务 / 实时日志三栏横向看板，分隔线可拖动；窄屏仍保留常驻日志。
- 界面由 `ttkbootstrap 2.x` 渲染；Setup 内置 2.2.2 wheel，并会自动安装或升级该依赖。
- 同样的日志按 UTF-8 写入 `logs\PaperMiner_*.log`，避免中文乱码。
- 输入和输出目录可在主界面分别选择；路径保存在 `%LOCALAPPDATA%\PaperMiner\settings.json`，升级后仍然有效。
- 长批次每篇结束后会回收 Python/CUDA 临时内存并记录占用变化；原生崩溃堆栈也会尽可能写入同一日志文件。
- MinerU 对每篇 PDF 使用独立进程；单篇发生 CUDA/原生库硬崩溃时，主界面会记录退出码并保留其余批处理队列。
- v1.4.20 会在 MinerU 启动前估算 Windows 图片输出路径；长论文标题自动映射到可追溯的短 raw 目录，完整原名保存在 `.paperminer-source.json`。最终正文/公式路径仍过长时使用 `全文.md`、`公式.md`，无需人工改论文名。
- 软件会在后台识别全部可用 CUDA 显卡。“GPU 并行设置”允许逐卡启用并设置每卡任务数；每个 MinerU 子进程固定绑定到一张物理显卡。
- 默认安全配置是每张启用显卡 1 个任务。提高每卡任务数会增加吞吐量，也会近似成倍增加显存占用；应根据每张卡的显存峰值分别调整。
- 每轮 GPU 批处理会低频采样逐卡利用率和显存，并结合任务结果在任务看板生成下一轮建议；建议必须由用户点击“应用到下一轮”确认，不会运行中自动改并发。
- 建议每轮每卡最多增减 1 个任务；采样不完整、人工停止或解析失败时不提高，OOM、原生崩溃或显存接近上限时降低一档。
- 再次开始任务时，看板会在后台预检前同步清空上一轮完成状态、100% 进度、文件提示和统计数字。
- GPU 解析与文字、图表、章节和代码地址后处理采用流水线重叠执行；实时日志显示 `[GPU N][槽 M]`，停止按钮会终止所有活动 MinerU 子进程。
- 安装和启动时均验证 MinerU 必须为 `>=3.1.0,<4.0`；已存在的 2.x 环境会由重装流程升级，不再直接跳过。
- PowerShell 仅用于 Setup、重装和卸载阶段。

## 重装与卸载

运行 `Uninstall.exe`。主界面只有三个操作按钮：

- `取消`：不做任何更改并退出。
- `重装`：仅移除名为 `MinerU` 的 Conda 环境，然后重新进入已安装的依赖安装阶段。
- `卸载`：移除 `MinerU` 环境、运行记录、Windows 卸载登记和本程序桌面快捷方式。

重装和卸载均保留模型缓存、项目源码、`.env`、`input`、`output` 与历史日志。Setup 自动安装的 Anaconda 目录及其旁边的 `PaperMinerDownloads` 缓存也会保留，避免误删其他 Conda 环境或约 1.04 GiB 的可复用安装包。应用目录不会被自动递归删除；确认数据后可由用户手工处理。

## 数据安全

- Setup 更新现有安装时，不把 `.env`、运行时记录、`input`、`output` 或 `logs` 放入安装载荷，因此不会覆盖这些可变数据。
- 被更新的旧程序文件会备份到 `%LOCALAPPDATA%\PaperMiner\SetupBackups\时间戳`。
- 安装载荷拒绝绝对路径、`..` 路径穿越和磁盘根目录安装。

联系邮箱：`2878705044@qq.com`
