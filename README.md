# 一表通（OneSheet）

> 多表归一：从 Excel / Word / PDF / CSV 中批量抽取「表单（标签:值）」数据，汇总成一张表，再把校对后的值反向写回 Excel 源文件。

**当前版本：v2.0** · [更新日志](CHANGELOG.md) · [下载 Release](https://github.com/sorrowchao/onesheet/releases/latest)

Windows 桌面应用（PySide6），单机本地运行，无需服务端。适用于「单位详细名称：……」「姓名：张三」这类表单、统计报表的批量整理。

## 功能

- **多格式混合输入**：Excel（`.xlsx` / `.xls` / `.xlsm`）、Word（`.docx`）、PDF（文字型 / 扫描件）、CSV 可以放在同一个文件列表中一起抽取。
- **多种配置方式**：启发式「扫描表单」、AI 扫描（OpenAI 兼容接口）、手动配对、手动添加字段，也可以从文件名自动生成一列。
- **模板复用**：把字段映射、取值位置和输出列顺序保存为模板，下次直接打开使用。
- **批量抽取与汇总**：多文件结果按表名合并，自动补齐并集列、排序、生成「序号」列。
- **反向写入**：用复合主键把汇总行匹配回各个 Excel 分表，按原格式回填并另存到指定目录，不覆盖原件。
- **结果可编辑**：结果表支持 Excel 式复制粘贴（TSV）、撤销/重做、增删行、清除单元格，改完再回写。
- **导入文件夹筛选**：包含子文件夹、每个文件夹数量上限、排序、大小范围、文件名正则，实时预览。
- **界面与主题**：VSCode 风格深色 / 浅色主题、应用图标切换、窗口状态记忆。

## 支持的文件格式

| 格式 | 读取 | 反向写入 | sheet 命名 |
|---|:---:|:---:|---|
| Excel `.xlsx` / `.xls` / `.xlsm` | ✅ | ✅ | 原工作表名 |
| Word `.docx` | ✅ | — | 表格依次为 `表1`、`表2`…；段落为 `正文` |
| PDF（文字型 / 扫描件） | ✅ | — | `表1`、`正文`、`扫描`（跨页同种表格按页序拼接） |
| CSV | ✅ | — | 固定为 `CSV` |

文件按真实格式识别（魔数），WPS 另存后改名为 `.xlsx` 的旧版 `.xls` 也能正常读取。

## 快速开始

环境要求：Windows 10/11，Python 3.10+（开发与测试使用 3.14.3）。

```bash
pip install -r requirements.txt
python main.py
```

也可以直接下载打包好的 [`onesheet.exe`](https://github.com/sorrowchao/onesheet/releases/latest)。

### 使用流程

1. **导入文件 / 文件夹**（或直接拖入窗口）。
2. 双击文件预览，切换到包含表单的 sheet。
3. 配置字段：
   - 「扫描表单」按标签:值规则自动识别；
   - 「AI 扫描表单」让模型返回字段映射；
   - 或「手动配对」/「添加字段」逐个指定；
   - 需要文件名时点「添加文件名」。
4. 保存模板，之后同类文件可重复使用。
5. 「批量抽取」生成汇总表，可在结果区直接校对修改。
6. 「反向写入」把修改后的值写回 Excel 分表，或「导出」为 xlsx / csv。

## AI 接口配置

菜单 **数据 → AI 接口设置（OpenAI 兼容）…** 可填写：

- API Key
- API 地址（基础地址如 `https://api.deepseek.com/v1`，或完整 `…/chat/completions` 端点）
- 模型
- 视觉模型（用于扫描件 PDF，留空则沿用普通模型）

默认使用 DeepSeek。支持 OpenAI / Qwen / Kimi / 本地兼容服务。也支持环境变量：

| 环境变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` | API Key |
| `OPENAI_BASE_URL` | API 地址 |
| `OPENAI_MODEL` | 模型 |
| `OPENAI_VISION_MODEL` | 视觉模型 |

未配置环境变量时读取 `data/settings.json`。该文件以明文保存 Key，仅适合单机本地使用。

## 数据目录

源码运行时位于项目根目录，打包运行时位于 exe 所在目录（或上一级已有 `data/templates` 的目录）：

```
data/
├─ settings.json      # AI 配置、主题、窗口状态、上次导入目录等
├─ templates/         # 模板 JSON
├─ icons/             # 用户自定义应用图标（可选）
└─ logs/              # ai_scan.log / pdf_vision.log
```

`data/` 已被 `.gitignore` 排除，不会提交到仓库。

## 开发

```bash
# 运行全部单元测试（353 个）
python -m unittest discover -s tests

# 仅运行某个测试文件
python -m unittest discover -s tests -p "test_writer.py"

# 离屏运行 UI 测试
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests

# 打包单文件 exe（输出 dist/onesheet.exe，约 52 MB）
python -m PyInstaller --noconfirm --clean onesheet.spec
```

### 目录结构

```
main.py                 # 程序入口
app/
├─ core/                # 读取/解析、识别、抽取、汇总、导出、回写、AI 扫描
│  ├─ reader.py         # Excel 读取与格式检测
│  ├─ csv_reader.py     # CSV
│  ├─ docx_reader.py    # Word
│  ├─ pdf_reader.py     # PDF（含扫描页视觉识别与跨页拼接）
│  ├─ document_reader.py# 多格式分发
│  ├─ detector.py       # 表单字段启发式识别
│  ├─ extractor.py      # 按模板抽取
│  ├─ aggregator.py     # 多文件汇总
│  ├─ exporter.py       # 导出 xlsx / csv
│  ├─ writer.py         # 反向写入 Excel
│  └─ ai_scan.py        # AI 字段推荐
├─ service/             # 本地设置、后台线程 worker
├─ template/            # 模板 schema 与存取
├─ ui/                  # 面板、对话框、主题、字体、图标
└─ icons/               # 内置应用图标
tests/                  # 单元测试
```

更详细的架构说明见 [`CLAUDE.md`](CLAUDE.md)，需求与设计见 [`PRD.md`](PRD.md)、[`M1技术方案.md`](M1技术方案.md)，用户手册见 [`使用说明.txt`](使用说明.txt)。

## 已知限制

- 反向写入只支持 Excel；Word / PDF / CSV 是只读输入。
- 旧版 Word（`.doc`）不支持，请先另存为 `.docx`。
- 加密的 PDF / Word 暂不支持，请先移除密码。
- 扫描件 PDF 需要配置支持图片输入的视觉模型；文字型 PDF 不需要。
- 仅处理「表单（标签:值）」这一类数据结构。

## 致谢

- 图标来自 [阿里巴巴矢量图标库](https://www.iconfont.cn/)
- 代码：忧凉 & DeepSeek-V4.1-Flash-1017
- 联系邮箱：13074050195@163.com

如有侵权，联系删除。
