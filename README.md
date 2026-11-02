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

## Docker 镜像与打包

需要 Docker Engine / Docker Desktop、Docker Compose v2+ 和 Make。在项目根目录运行：

```bash
make build
make up
```

访问 <http://127.0.0.1:8080>。`make up` 也会构建镜像，可以单独运行。前端使用 Node 构建后由 Nginx 托管，后端使用 Python 3.12 和系统 FFmpeg；两个镜像分别为 `voice-smiths-frontend:latest`、`voice-smiths-backend:latest`。Nginx 将 `/api` 转发到后端，不限制上传文件大小，后端端口仅在容器网络内使用。镜像构建上下文只包含代码和依赖清单，不包含本机小说、音频、虚拟环境或环境配置文件。

容器默认使用宿主机 `docker-data/` 保存数据：

```text
docker-data/
  uploads/
  audio/
  voice-smiths.sqlite3
```

可指定端口、数据根目录，以及分别指定原稿和音频保存目录：

```bash
make up WEB_PORT=8088 STORAGE_DIR=/srv/voice-smiths
make up STORAGE_DIR=/srv/voice-smiths UPLOAD_DIR=/srv/novels AUDIO_DIR=/srv/audio
```

这些是宿主机目录，容器内固定为 `/data`、`/data/uploads`、`/data/audio`。为便于在新机器恢复，保持相同的容器内路径；备份和迁移时同时保存数据库、原稿和音频目录。容器数据独立于本地开发的 `data/`；本地开发数据库记录了宿主机绝对路径，不能直接当作容器数据库使用。

默认只监听本机。需要其他机器访问时，运行 `make up WEB_BIND=0.0.0.0`。生成并发与超时仍可使用 `VOICE_SMITHS_WORKERS`、`VOICE_SMITHS_CONNECT_TIMEOUT`、`VOICE_SMITHS_RECEIVE_TIMEOUT` 配置。Compose 可从根目录 `.env` 读取这些配置和目录、端口参数，镜像名与版本使用 Make 参数指定。

打包镜像并在另一台机器加载：

```bash
make save TAG=v1.0.0 PLATFORM=linux/amd64
make load TAG=v1.0.0 ARCHIVE=dist/images/voice-smiths-v1.0.0.tar
make start TAG=v1.0.0
```

`make save` 会构建两个镜像并导出到 `dist/images/voice-smiths-<TAG>.tar`，不包含运行数据。目标机器需要复制 `compose.yaml`、`Makefile` 和镜像包，再执行 `make load`、`make start`；生成语音时仍需访问在线语音服务。省略 `PLATFORM` 时按当前 Docker 引擎架构构建，Apple Silicon 构建 Linux x86 服务器镜像时指定 `PLATFORM=linux/amd64`。`make start` 不构建、不拉取镜像，适合离线导入后启动。

推送到镜像仓库时先登录，再使用相同的镜像前缀和版本：

```bash
make build IMAGE_PREFIX=registry.example.com/team/voice-smiths TAG=v1.0.0
make push IMAGE_PREFIX=registry.example.com/team/voice-smiths TAG=v1.0.0
```

若构建环境无法访问 Docker Hub，可通过 `PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE` 参数指定可访问的基础镜像地址，例如 `make build PYTHON_IMAGE=registry.example.com/library/python:3.12-slim-bookworm NODE_IMAGE=registry.example.com/library/node:22-alpine NGINX_IMAGE=registry.example.com/library/nginx:1.28-alpine`。基础镜像需保持相同的运行环境。

`make logs` 查看日志，`make ps` 查看健康状态，`make down` 停止并移除容器，宿主机的数据文件会保留。`make help` 可查看全部命令。

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
