# PaperMiner

> 面向科研工作者的 Windows 论文内容提取工作台：批量处理 PDF，并把正文、公式、图片、表格和论文章节整理成可继续编辑的 Markdown、Excel 与 Word 文件。

[![Latest release](https://img.shields.io/github/v/release/Given-Dream/PaperMiner?display_name=tag&sort=semver)](https://github.com/Given-Dream/PaperMiner/releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows)](#系统要求)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](#从源码运行)
[![License](https://img.shields.io/badge/License-查看协议-green)](docs/LICENSE)

当前版本：**v1.4.2** · [下载 PaperMiner v1.4.2](https://github.com/Given-Dream/PaperMiner/releases/tag/v1.4.2)

![PaperMiner v1.4.2 横向工作台](docs/images/paperminer-v1.4.2-dashboard.png)

## 适合做什么

PaperMiner 以 MinerU 为解析后端，在一个界面中完成 PDF 批处理、结构化提取与结果归档。它适合把论文转换为可检索、可引用、可二次加工的个人素材库。

| 能力 | 输出 |
| --- | --- |
| 正文提取 | 修复资源路径后的 Markdown |
| 图片提取 | JPG/PNG、图号识别与映射表 |
| 表格提取 | 表格图片与 Excel（`.xlsx`） |
| 公式提取 | 公式图片与 LaTeX 汇总 |
| 章节归类 | `Abstract`、`Introduction`、`Methods`、`Results & Discussion`、`Conclusion` 等独立 Markdown |
| 图表汇总 | 按原文顺序生成 Word 与 Markdown |

章节归类采用“正则规则优先、LLM 按需补充”的方式。不配置 API 也能工作；配置 DeepSeek 或 OpenAI 兼容接口后，可对缺失或异常章节进行辅助识别。

## v1.4.2 更新内容

- 修复 Conda 主程序与 `MinerU` 环境位于不同磁盘或不同 `envs_dirs` 时，依赖安装成功却被误报失败的问题。
- 安装器通过 `conda env list --json` 获取真实环境路径，并把精确的 Python 路径写入运行时配置。
- 重装和卸载按 Conda 已注册的精确 `MinerU` 前缀操作，不再假设环境固定在 `<Conda根>\envs\MinerU`。
- 明确支持安装到 C、D、E、F 等任意可写目录；为防止误覆盖，仍禁止直接选择磁盘根目录。

### v1.4.1 界面更新

- 主界面升级为“处理配置 / 任务看板 / 实时日志”三栏横向布局，分隔线可以拖动。
- PowerShell 输出已收进软件右侧实时日志区；正常启动 `PaperMiner.exe` 不再弹出外部 PowerShell 窗口。
- 新增 DeepSeek 与 OpenAI 兼容自定义接口配置、模型发现和真实请求测试。
- 自定义模型改为真正的单选列表：普通单击即可更换模型，测试和保存只作用于当前选择。
- Setup 内置现代界面依赖，并在安装阶段完成 MinerU/Python 环境检查与修复。
- 更新安装时保留 `.env`、`input`、`output` 和 `logs` 等用户数据。

完整记录见 [CHANGELOG.md](CHANGELOG.md)。

## 快速安装

### 1. 准备 Conda

安装 [Miniconda](https://docs.conda.io/projects/miniconda/en/latest/) 或 Anaconda。推荐 Python 3.12；安装位置可以在 C、D、E 等任意磁盘。

### 2. 下载并运行 Setup

1. 打开 [v1.4.2 Release](https://github.com/Given-Dream/PaperMiner/releases/tag/v1.4.2)。
2. 下载 `PaperMiner-v1.4.2-Setup.exe`，可使用同页的 `SHA256SUMS.txt` 校验文件。
3. 双击安装包并选择安装目录。默认目录为：

   ```text
   %LOCALAPPDATA%\Programs\PaperMiner
   ```

4. 安装阶段会打开日志窗口，检查 Conda、安装或修复依赖，并记录可用的 MinerU 运行环境。首次安装还可能下载 PyTorch 和 MinerU 模型，需要较长时间与数 GB 磁盘空间。
5. 安装完成后，从桌面快捷方式或安装目录中的 `PaperMiner.exe` 启动。

安装目录可以选择 `D:\PaperMiner`、`E:\Apps\PaperMiner` 等非 C 盘位置，但不能直接选择 `D:\` 这类磁盘根目录。Conda 与 `MinerU` 环境也可以分处不同磁盘。

> PowerShell 只在安装、重装和卸载阶段使用。正常运行 PaperMiner 时，日志直接显示在软件界面中，并同步写入 `logs\PaperMiner_*.log`。

### 3. 处理 PDF

1. 把 PDF 放入软件显示的 `input` 目录。
2. 点击“刷新文件”，选择完整流程或仅提取已有 raw 结果。
3. 勾选需要的文字、公式、图片、表格和章节功能。
4. 点击“开始处理”，在右侧查看实时日志和任务统计。
5. 从“打开 raw”或“打开 extract”进入输出目录。

## 界面与工作流

```text
PDF
 └─ MinerU 解析
     ├─ output/raw       原始 Markdown、图片、布局与模型结果
     └─ output/extract   正文、图片、表格、公式、章节和 Word 汇总
```

主界面提供两种处理模式：

- **完整流程**：PDF → MinerU → 结构化提取。
- **仅提取 raw**：复用已有 MinerU 结果，不重复解析 PDF。

勾选“跳过已处理结果”后，已经生成 `extract` 结果的同名论文不会重复处理。

## LLM 接口与模型

LLM 是可选项。不开启时，PaperMiner 仍会使用规则识别论文结构。

### DeepSeek

打开右上角“接口与模型设置”，选择 DeepSeek，填写 API Key 和模型 ID，测试成功后保存。

### OpenAI 兼容接口

自定义服务需要兼容：

- `GET /models`
- `POST /chat/completions`

填写到 `/v1` 层级的 API 根地址和 API Key，然后按以下顺序操作：

1. 点击“读取模型”。
2. 在列表中普通单击一个模型。
3. 点击“测试当前模型”。
4. 测试通过后点击“保存并启用自定义接口”。
5. 最后点击设置窗口右下角“应用并保存”。

![PaperMiner v1.4.2 单选模型列表](docs/images/paperminer-v1.4.2-model-selector.png)

模型列表是**单选**：任何时刻只有一个模型会被测试、保存并用于主界面。`bge-*`、`nomic-embed-*` 等通常属于嵌入模型，可能不支持 `/chat/completions`；章节提取应选择 Qwen、DeepSeek、Llama 等可对话模型，并以“测试当前模型”的结果为准。

API Key 保存在项目目录的 `.env` 中，不会显示在运行日志中，也不应提交到 Git。

## 输出目录

```text
output/
├─ raw/
│  └─ [论文名]/auto/
│     ├─ [论文名].md
│     ├─ images/
│     └─ *.json / *.pdf
└─ extract/
   └─ [论文名]/
      ├─ [论文名].md
      ├─ Figure/
      ├─ Tables/
      ├─ Formula/
      ├─ Sections/
      └─ Word/
```

`Sections` 会保留论文中实际识别出的章节。不同论文结构并不总是固定为五章；若标题写法特殊、原始 Markdown 缺失或模型补充失败，请结合完整 Markdown 与实时日志人工核查。

## 重装与卸载

安装后运行 `Uninstall.exe`，可以选择：

- **取消**：退出，不修改任何内容。
- **重装**：重建名为 `MinerU` 的 Conda 环境并重新安装依赖。
- **卸载**：移除程序登记、桌面快捷方式和对应 Conda 环境。

重装与卸载会保留模型缓存、`.env`、`input`、`output` 和历史日志；确认数据无误后，再由用户手工清理不再需要的目录。

## 系统要求

- Windows 10 或 Windows 11（64 位）
- Miniconda 或 Anaconda
- Python 3.12（推荐）
- 内存 8 GB 以上；CPU 处理建议 16 GB 以上
- 可用磁盘空间至少 10 GB（环境、PyTorch、模型和输出会持续占用空间）
- NVIDIA GPU 可选；没有可用 CUDA 时可以使用 CPU
- 首次安装和下载模型需要网络连接

## 从源码运行

Windows 用户优先使用 Release 安装包。开发或调试时可执行：

```powershell
git clone https://github.com/Given-Dream/PaperMiner.git
cd PaperMiner
conda create -n MinerU python=3.12 -y
conda activate MinerU
pip install -U "mineru[core]>=3.1.0,<4.0"
pip install -r requirements.txt
python scripts/batch_pdf_processor_gui.py
```

如需 GPU，请根据显卡驱动安装匹配的 PyTorch CUDA 版本。国内网络可设置：

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
```

不要提交以下运行数据：

- `.env` 与任何 API Key
- `input/` 中的论文原件
- `output/` 中的解析结果
- `logs/`、缓存和 Python `__pycache__`

## 常见问题

### 安装后启动没有反应

先查看安装目录下最新的 `logs\Setup_*.log`，确认 Setup 已记录可用的 MinerU 环境。若环境损坏，运行 `Uninstall.exe` 并选择“重装”。

### 右侧日志停止在 `All core dependencies are present.`

这表示核心依赖检查通过。等待后续运行环境和模型检查；如果长时间没有变化，请保留完整日志并重启安装程序，避免直接删除 Conda 或模型目录。

### 模型能读取但测试失败

`/models` 可用只代表模型发现成功，并不代表该模型能调用 `/chat/completions`。请检查模型类型、服务端权限、余额和上下文限制，并改选可对话模型测试。

### 章节数量比论文目录少

PaperMiner 会归并同类标题，并且章节结果依赖 MinerU 生成的 Markdown。请先检查 `output/raw` 中标题是否完整，再查看实时日志确认是规则识别还是 LLM 补充；最终结果建议与原文人工核对。

## 数据与安全

- 更新载荷不覆盖 `.env`、`input`、`output` 和 `logs`。
- 被替换的旧程序文件会备份到 `%LOCALAPPDATA%\PaperMiner\SetupBackups\时间戳`。
- Setup 会拒绝磁盘根目录、绝对载荷路径和 `..` 路径穿越。
- 发布页提供 SHA-256 校验文件，下载后可验证安装包完整性。

## 许可证与联系

许可证见 [docs/LICENSE](docs/LICENSE)。PaperMiner 基于 [MinerU](https://github.com/opendatalab/MinerU) 构建，请同时遵守 MinerU 及相关依赖的许可证。

问题反馈请使用 [GitHub Issues](https://github.com/Given-Dream/PaperMiner/issues)，或联系：`2878705044@qq.com`。
