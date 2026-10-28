# 叙音工坊 · 小说配音

一个本地运行的 Python 小说配音应用。它会把 TXT/Markdown 小说按章节解析，再按旁白和角色切成独立片段，为每个角色分配稳定的中文声线，最后生成带 `manifest.json` 的章节音频 ZIP。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

打开 <http://127.0.0.1:8765>，点击“新增章节”，上传 TXT/Markdown 或直接粘贴文本：

1. 应用识别 `第一章`、`Chapter 1` 等章节标题。
2. 识别 `角色：对白`、`“对白”` 和常见“某某说道”格式。
3. 在“角色声线”面板切换角色声音。
4. 点击“生成本章音频”，等待任务完成后下载 ZIP。

`edge-tts` 使用微软在线语音服务，因此首次生成需要网络。解析、角色识别和声线配置不依赖网络。每个章节的 ZIP 内包含按顺序编号的 MP3 片段和 `manifest.json`，便于后续合并或剪辑。

## 命令行 API

```python
from voice_smiths import create_project, parse_novel

project = parse_novel("第一章 初见\n林默：你好。")
create_project("第一章 初见\n林默：你好。", "data/demo", title="我的小说")
```

核心解析模块位于 `backend/core.py`，JSON 门面位于 `voice_smiths/project.py`。不启动 Web 服务也可以直接调用它们。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
