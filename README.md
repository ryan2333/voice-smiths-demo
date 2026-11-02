# 叙音工坊 · 小说配音

React + Vite 前端与 Python FastAPI 后端独立运行。小说按章节、旁白和角色拆分，后台异步生成不同声线，再把每章合并为一个 MP3。

## 启动

需要 Python 3.10+、Node.js 20.19+ 或 22.12+。

后端，在项目根目录运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

后端地址为 <http://127.0.0.1:8765>，接口文档为 <http://127.0.0.1:8765/docs>。后端只提供 API，不再托管 HTML。

另开终端，在项目根目录运行前端：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

浏览器打开 **<http://127.0.0.1:5173>**。前端通过 Vite 代理访问后端 `/api`。

## 使用

1. 点击“导入 TXT”，选择 TXT/Markdown 文件或粘贴文本。
2. 选择“自动识别”或手动指定 UTF-8、GBK/GB18030、Big5、UTF-16。后端保留上传文件的原始字节。
3. 查看章节和角色，选择声线后点击“试听声音”，用该角色的一小段原文试听。试听结果缓存在音频目录的 `previews/` 下，不计入章节生成记录；修改声线后重新试听。点击“保存全书声线”持久保存角色配置。
4. 生成当前章节，或在“章节管理”勾选章节并批量生成，支持全选当前搜索结果和整本小说加入队列。批量提交会先检查所有章节，避免因无效章节提交部分任务；相同配置的活动任务会复用。
5. 在“生成与音频”查看排队、配音、合并和完成状态；完成后可直接播放、下载本章 MP3。音频使用章节名称命名，例如 `初见.mp3`，保留中文、空格；文件名中的非法字符自动替换，不同任务分别保存以避免重名覆盖。历史音频下载时同样使用章节名。
6. 播放器支持 0.5×–2× 倍速，也可在“存储与设置”中设置默认播放速度，自动记住并用于章节播放和角色试听。倍速仅影响收听，下载文件保持合成时的语速。

任务提交后立即返回 `202` 和任务编号，前端每 1.5 秒查询一次进度，**不再设置整章 84 秒等待限制**。关闭浏览器不会停止后台任务，刷新页面可继续查看记录。网络查询失败时前端会自动重新连接。

## 指定保存目录

默认目录：

```text
data/
  uploads/<作品编号>/<原文件名>.txt
  audio/<任务编号>/chapter_001/
    0001_旁白.mp3
    0002_角色.mp3
    章节标题.mp3
    manifest.json
  voice-smiths.sqlite3
```

在启动后端前设置环境变量，即可分别指定目录（支持绝对路径）：

```bash
export VOICE_SMITHS_DATA_DIR="$PWD/storage/metadata"
export VOICE_SMITHS_UPLOAD_DIR="$PWD/storage/novels"
export VOICE_SMITHS_AUDIO_DIR="$PWD/storage/audio"
.venv/bin/python app.py
```

也可复制 `.env.example` 为 `.env`，修改后在终端加载；应用读取进程环境变量，不会自动加载 `.env`：

```bash
set -a
source .env
set +a
.venv/bin/python app.py
```

目录不存在时会自动创建，运行账号须有写入权限。在前端“存储与设置”可以查看实际保存位置。旧版本 `exports/` 中已有文件会保留；修改存储目录不会自动搬迁历史文件。

其他可选配置：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `VOICE_SMITHS_HOST` | `127.0.0.1` | API 监听地址 |
| `VOICE_SMITHS_PORT` | `8765` | API 端口 |
| `VOICE_SMITHS_WORKERS` | `2` | 同时生成章节数，范围 1–8 |
| `VOICE_SMITHS_CONNECT_TIMEOUT` | `10` | 语音服务连接超时，秒 |
| `VOICE_SMITHS_RECEIVE_TIMEOUT` | `60` | 语音服务连续未收到数据的超时，秒 |
| `VOICE_SMITHS_CORS_ORIGINS` | localhost/127.0.0.1 的 5173 端口 | 允许访问 API 的前端来源，逗号分隔 |

队列和进度保存在 SQLite；正常退出会把正在生成的任务标记为中断，意外退出后下次启动也会识别中断任务。尚未开始的任务会重新入队。失败、中断的任务可以在页面重新提交，已完成音频在重启后仍可播放下载。**后端使用单个 Uvicorn 进程**，章节并发由 `VOICE_SMITHS_WORKERS` 控制。

`edge-tts` 需要网络访问微软语音服务。上传解析、存储与 MP3 合并在本地完成，`imageio-ffmpeg` 随 Python 依赖提供合并工具。

## 前端构建与独立部署

```bash
npm --prefix frontend run build
npm --prefix frontend run preview
```

生产文件输出到 `frontend/dist/`，可由 Nginx 或其他静态服务器托管；把 `/api` 反向代理到后端。若前后端使用不同域名，在构建前设置 `VITE_API_BASE=https://api.example.com`，并将前端来源加入后端 `VOICE_SMITHS_CORS_ORIGINS`。开发代理目标可通过 `frontend/.env.local` 中的 `VITE_API_PROXY` 修改，示例见 `frontend/.env.example`。

## API

| 方法与路径 | 功能 |
| --- | --- |
| `POST /api/projects/upload` | multipart 上传原文件，`encoding` 字段指定编码 |
| `POST /api/projects` | 保存粘贴的小说文本并解析 |
| `GET /api/projects` | 作品列表 |
| `GET/PATCH /api/projects/{id}` | 查看作品、保存声线配置 |
| `POST /api/jobs` | 提交 `{project_id, chapter_index, voice_map}`，章节索引从 0 开始 |
| `POST /api/jobs/batch` | 提交 `{project_id, chapter_indices, voice_map}`，去重并批量入队 |
| `POST /api/voices/preview` | 提交 `{voice, text, rate, pitch, volume}`，返回试听音频地址；文本最多 160 字 |
| `GET /api/voices/previews/{id}/audio` | 播放缓存的角色声线试听音频 |
| `GET /api/jobs` | 生成记录，可通过 `project_id` 过滤 |
| `GET /api/jobs/{id}` | 状态、已完成片段数与进度 |
| `POST /api/jobs/{id}/retry` | 重试失败或中断任务 |
| `GET /api/jobs/{id}/audio` | 播放完整章节 MP3，支持 Range 请求 |
| `GET /api/jobs/{id}/audio?download=true` | 下载 MP3 |
| `GET /api/config` | 存储目录与生成参数 |

`voice_smiths/` 中的命令行解析和渲染接口仍可直接调用。

## 测试

```bash
.venv/bin/python -m pip install httpx
.venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend test
npm --prefix frontend run build
```
