# AI Studio V1.0

**AI 漫剧 / 连续剧自动创作平台** — 输入故事，自动产出剧本、分镜、图片、视频、配音、字幕，最终用 FFmpeg 合成一集可播放的 MP4。

```
故事 → 剧本 → 分镜 → 图片 → 视频 → 配音 → 字幕/BGM → 成片
```

> 当前状态：**Phase 5（图片）已完成** —— 已打通「故事 → 剧本 → 分镜 → 图片」。
> 已实现认证、项目 CRUD、Story Agent（Story Bible / 人物 / 场景）、Episode Agent
> （分集 / 剧本 / 分镜 / 一致性），以及图片流水线：人物与场景参考图、逐镜出图、
> **Redis + Celery 异步任务**（重试 3 次、幂等）、签名 URL 存储。
> LLM 与图片 Provider 默认 `mock`（离线确定性，无需 key），可通过环境变量切换为任意
> OpenAI 兼容端点（LLM 已验证 DeepSeek）。视频 / TTS 仍是 `mock` —— 这是刻意为之，
> 属 Phase 6-7。

- 产品需求与开发规范：[docs/PRD.md](docs/PRD.md)
- 技术设计与分层规则：[docs/TDD.md](docs/TDD.md)

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 15（App Router）· TypeScript · React 19 · Tailwind CSS 3 |
| 后端 | Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic |
| 数据库 | PostgreSQL 16 |
| 缓存 / 队列 | Redis 7 · Celery（Phase 5 起启用，独立 worker 容器） |
| Agent | LangGraph（Phase 3 启用） |
| 图片生成 | ImageProvider：`mock`（离线真 PNG）/ 任意 OpenAI 兼容端点 |
| 存储 | 本地目录 + 签名 URL（Phase 5）→ S3/OSS（上线前） |
| 合成 | FFmpeg（Phase 8） |
| 部署 | Docker Compose |

---

## 目录结构

```
ai-studio/
├── frontend/                  # Next.js
│   ├── app/                   # 首页(项目列表) / login / projects/new / projects/[id]
│   ├── components/            # Navbar、AuthProvider、Loading/Empty/Error 状态组件
│   ├── lib/api.ts             # 唯一 fetch 出口 + Envelope 解包 + 错误分类
│   ├── lib/session.ts         # 访问令牌存取
│   └── Dockerfile
├── backend/                   # FastAPI
│   ├── app/
│   │   ├── api/v1/            # 路由: health / auth / projects
│   │   ├── core/              # config/database/logging/security/responses/exceptions
│   │   ├── models/            # ORM
│   │   ├── schemas/           # Pydantic
│   │   ├── services/          # 业务逻辑: auth_service / project_service
│   │   ├── repositories/      # 数据访问: base / user / project
│   │   ├── providers/         # LLM/Image/Video/TTS 抽象
│   │   ├── agents/            # LangGraph（Phase 3+）
│   │   ├── tasks/ workers/    # Celery（Phase 5+）
│   │   └── main.py
│   ├── migrations/            # Alembic
│   ├── tests/                 # pytest
│   └── Dockerfile
├── prompts/                   # 版本化 Prompt（story/script/storyboard/image/video/tts）
├── docs/                      # PRD.md · TDD.md
├── docker-compose.yml
└── .env.example
```

---

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
cp .env.example .env          # 按需修改，务必替换 SECRET_KEY
docker compose up -d --build
docker compose ps
```

启动后：

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

后端容器启动时会自动执行 `alembic upgrade head`。

```bash
docker compose logs -f backend     # 跟踪日志
docker compose down                # 停止（保留数据卷）
docker compose down -v             # 停止并清空数据
```

### 方式二：本地开发

**后端**

```bash
cd backend
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"         # macOS / Linux

# 只需 PostgreSQL + Redis 用容器起，应用本机跑：
docker compose up -d postgres redis

cp ../.env.example ../.env

.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

**前端**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev            # http://localhost:3000
```

> Windows 上若宿主预设了 `PYTHONPATH`，运行后端测试前先 `unset PYTHONPATH`，
> 否则会加载到错误的 FastAPI/Starlette（详见 TDD §13）。

---

## 测试与验收

仓库根目录提供统一任务入口（`package.json` → `scripts/tasks.py`）。
**统一从这里跑**，不要再手敲命令：脚本会为子进程清掉宿主被污染的 `PYTHONPATH`，
并按平台选择正确的 shell。

```bash
npm run --list      # 查看全部任务
npm run lint        # ruff check + format --check（backend + scripts 全覆盖）
npm run test        # 后端 pytest（hermetic）
npm run typecheck   # 前端 tsc --noEmit
npm run build       # 前端生产构建 + 容器镜像
npm run verify      # 全部端到端验收脚本（Phase 1-4）
npm run verify:phase5  # Phase 5 图片链路（需 worker 容器在跑，走真 Celery）
npm run verify:phase4  # 只跑 Phase 4 的那一份
npm run verify:ui   # 真实 Chrome 渲染 UI（Playwright，Phase 3 + 4 + 5）
npm run seed        # 造演示账号 + 已解析项目
npm run up / down   # 启停 compose 栈
```

当前结果：**442 passed**（健康检查契约、统一响应 Envelope、request_id、错误处理器、
ORM 持久化与约束、密码/JWT、日志脱敏、配置解析、认证 API、项目 CRUD、故事读写、
跨用户越权隔离、Story Agent 与 Bible 别名归一化、溯源落库、
Episode Agent 的分集/剧本/分镜 schema 与 id 绑定、一致性检查器（含 dict 与 Pydantic
两种输入形状的一致性）、剧集 API 与守卫）。

### 端到端验收

```bash
npm run verify                     # 等价于下面四条
bash scripts/verify_phase1.sh      #  18 项：健康检查 / Envelope / request_id / 404
python scripts/verify_phase2.py    #  84 项：认证 / 项目CRUD / 故事 / 越权隔离
python scripts/verify_phase3.py    # 132 项：Story Agent / Bible / 人物场景 CRUD / 隔离
python scripts/verify_phase4.py    #  87 项：分集规划 / 剧本 / 分镜 / 镜头 / 一致性 / 隔离
```

浏览器验收（`npm run verify:ui`）会依次跑两套脚本，各自用真实模型造数据后驱动 Chrome：

| 脚本 | 断言 |
| --- | --- |
| `verify_ui_phase3.py` | 概览 / Story Bible / 人物 / 场景 渲染，18 项 |
| `verify_ui_phase4.py` | 剧集列表 / 剧本 / 分镜 / 一致性面板，以及「改镜头后刷新仍在」 |

> 验收脚本用 Python 而非 curl+bash：在 Windows/git-bash 下用
> `curl -d` 内联中文会被 shell 重新编码，后端直接以 400 拒绝 body，
> 造成大量假失败。见 docs/TDD.md §16。
>
> `verify_phase3.py` 不写死 provider：mock 与真实模型都能跑，
> 只有 mock 才会额外校验「重复解析结果完全一致」这类确定性断言。
>
> `verify_phase1.sh` 是唯一的 bash 脚本；从 Python 调用它必须用 git-bash 的
> 绝对路径（裸 `bash` 在 Windows 会命中 WSL 中继并失败），`npm run verify` 已处理。

---

## API

统一响应信封：

```json
{ "success": true,  "data": {}, "error": null, "request_id": "req_..." }
{ "success": false, "data": null,
  "error": { "code": "NOT_FOUND", "message": "Resource not found" },
  "request_id": "req_..." }
```

每个响应都带 `X-Request-ID` 头；请求头自带 `X-Request-ID` 时沿用调用方的值。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 存活探针，返回 `{"status":"ok"}`（PRD §31 裸契约） |
| GET | `/api/v1/health` | 存活探针（Envelope 版） |
| GET | `/api/v1/health/detail` | 就绪探针：database / redis 状态 + 版本 + 延迟 |
| GET | `/` | 服务元信息 |
| GET | `/docs` | Swagger UI |

### 认证（Phase 2）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | 注册，直接返回访问令牌（201） |
| POST | `/api/v1/auth/login` | 登录，返回访问令牌 |
| GET | `/api/v1/auth/me` | 当前登录用户 |

所有受保护接口使用 `Authorization: Bearer <access_token>`。

### 项目 + 故事（Phase 2）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/projects` | 创建项目（可内联故事文本） |
| GET | `/api/v1/projects` | 列表，支持 `page` / `page_size` / `search` / `status` |
| GET | `/api/v1/projects/{id}` | 详情（含剧集摘要） |
| PATCH | `/api/v1/projects/{id}` | 局部更新（只改传入字段） |
| DELETE | `/api/v1/projects/{id}` | 删除（级联删除剧集） |
| POST | `/api/v1/projects/{id}/story` | 保存 / 替换故事文本 |
| GET | `/api/v1/projects/{id}/story` | 读取已保存的故事 |
| DELETE | `/api/v1/projects/{id}/story` | 清空故事 |

> PRD §22 以 `/api/projects` 描述逻辑路径，本项目统一挂在 `/api/v1` 前缀下。
> 分页信息在 Envelope 的 `meta` 字段：`{total, page, page_size, pages}`。

### Story Agent + Bible（Phase 3）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/projects/{id}/analyze` | 运行 Story Agent（可传 `story_text` 试算；`?replace=true` 重新解析） |
| GET | `/api/v1/projects/{id}/analyze/status` | 解析状态 + 人物/场景数量 + 当前 provider |
| GET | `/api/v1/projects/{id}/bible` | Story Bible（未解析时 `story_bible` 为 `null`） |
| GET | `/api/v1/projects/{id}/characters` | 人物列表 |
| POST | `/api/v1/projects/{id}/characters` | 手动新增人物 |
| PATCH | `/api/v1/characters/{character_id}` | 局部修改（外貌 / 角色定位等） |
| DELETE | `/api/v1/characters/{character_id}` | 删除人物 |
| GET | `/api/v1/projects/{id}/locations` | 场景列表 |
| POST | `/api/v1/projects/{id}/locations` | 手动新增场景 |
| PATCH | `/api/v1/locations/{location_id}` | 局部修改（描述 / 时间 / 光线） |
| DELETE | `/api/v1/locations/{location_id}` | 删除场景 |

说明：

- **同名冲突返回 409**：人物/场景在项目内按名字唯一，避免重复解析堆叠副本。
- **越权一律 404**：人物与场景归属需穿过 `project.user_id` 判定，
  他人资源返回 404 而非 403（403 会泄露资源是否存在）。
- **`analyze` 是同步阻塞的**，真实模型约 20–90 秒；异步化在 Phase 5。
- `replace=true` 按名字 upsert，**不会**改变已有记录的 `id`，
  因此用户手改的外貌不会在重新解析后丢失。

```bash
# 注册并拿到令牌
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"storytime2026"}' | python -m json.tool

# 带令牌创建项目
curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"kaitou","genre":"urban"}' | python -m json.tool
```

### Episode Agent（Phase 4）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/projects/{id}/episodes` | 分集列表（含 `shot_count` 等派生字段与规划溯源） |
| POST | `/api/v1/projects/{id}/episodes` | 手动新增一集（不填编号则取下一个） |
| POST | `/api/v1/projects/{id}/episodes/plan` | 运行 `episode_planner`（`?replace=true` 才覆盖已有计划） |
| DELETE | `/api/v1/projects/{id}/episodes` | 清空分集计划 |
| GET/PATCH/DELETE | `/api/v1/episodes/{id}` | 剧集详情 / 修改 / 删除 |
| GET | `/api/v1/episodes/{id}/script` | 剧本（含 `characters` 的 id→name 查表） |
| POST | `/api/v1/episodes/{id}/script/generate` | 生成剧本 |
| PATCH | `/api/v1/episodes/{id}/script` | 修改剧本（`scenes` 整体替换） |
| GET | `/api/v1/episodes/{id}/storyboard` | 分镜文档 + 扁平镜头表 + 一致性报告 |
| POST | `/api/v1/episodes/{id}/storyboard/generate` | 生成分镜并自动跑一致性检查 |
| PATCH | `/api/v1/episodes/{id}/storyboard` | 修改分镜文档 |
| GET | `/api/v1/episodes/{id}/shots` | 镜头列表 |
| PATCH | `/api/v1/shots/{id}` | 修改单个镜头 |
| GET | `/api/v1/episodes/{id}/consistency` | 复检一致性（不调用模型，可随时跑） |

说明：

- **id 必须绑定到真实数据**：剧本里的 `character_id` / `location_id` 若不在
  Character/Scene Bible 中，节点会**重试模型**；重试用尽则本次生成失败，
  **不会**把悬空 id 落库（PRD §10）。
- **先剧本后分镜**：未生成剧本就请求分镜返回 409。
- **`plan` 的守卫**：故事未解析返回 409；已有计划而不传 `replace=true` 也返回 409，
  避免静默删掉已有剧本与分镜。
- **重新生成剧本会作废分镜**（旧 shots 全部删除）。因为镜头挂在 `scene_id` 上，
  剧本一改旧镜头就指向不存在的场次。
- **失败不销毁旧产出**：`script_status=FAILED` 时上一次的剧本仍在。
- **`PATCH /shots/{id}` 严格校验枚举**：`shot_size` / `camera_movement` 传未知值返回 422，
  不会被静默改成默认值（与模型输出不同 —— 模型的草稿值允许兜底）。
- **越权一律 404**：剧集归属需穿过 `project.user_id` 判定。

Phase 3 起按 PRD §22 补齐 `/analyze`、`/bible`、characters、locations、episodes、
script、storyboard、shots、compose、tasks 等接口。

---

## 环境变量

完整清单见 [`.env.example`](.env.example)，关键项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | `change-me-in-env` | **必须替换**，`openssl rand -hex 32` |
| `DATABASE_URL` | `postgresql+psycopg://ai_studio:ai_studio@localhost:5432/ai_studio` | 容器内 host 为 `postgres` |
| `REDIS_URL` | `redis://localhost:6380/0` | 容器内 host 为 `redis:6379`（宿主端口默认 6380，避开本机已有 Redis） |
| `CORS_ORIGINS` | `http://localhost:3000` | 支持逗号分隔或 JSON 数组 |
| `STORAGE_BACKEND` | `local` | 后续 `s3` / `oss` |
| `LLM_PROVIDER` | `mock` | Phase 3 起可切换为任意 OpenAI 兼容端点 |
| `IMAGE_PROVIDER` / `IMAGE_API_KEY` / `IMAGE_BASE_URL` / `IMAGE_MODEL` | `mock` | Phase 5 起图片可切换；`mock` 产出离线真 PNG |
| `IMAGE_WIDTH` / `IMAGE_HEIGHT` | `1024` | 请求尺寸（mock 会按 `MOCK_IMAGE_MAX_PIXELS` 等比缩小并如实上报实际尺寸）|
| `MOCK_IMAGE_FAIL_TIMES` | `0` | 让 mock 前 N 次故意失败，用于验证重试路径 |
| `ASSET_URL_TTL_SECONDS` | `3600` | 签名 URL 有效期（读取时自动续签）|
| `VIDEO_PROVIDER` / `TTS_PROVIDER` | `mock` | Phase 6-7 |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | **构建期**（非运行时）：容器内装 Python 依赖用的索引。容器到 PyPI 的路由常比宿主差，卡住时指向镜像源即可 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 空 / OpenAI / `gpt-4o-mini` | 仅 `LLM_PROVIDER != mock` 时使用 |
| `LLM_MAX_RETRIES` | `3` | Schema 校验失败后的重试上限 |
| `LOG_JSON` / `LOG_LEVEL` | `true` / `INFO` | 单行 JSON 日志，自动脱敏 |

`.env` 已在 `.gitignore` 中，不会被提交。

> 接真实模型（以 DeepSeek 为例）：
> ```bash
> LLM_PROVIDER=openai
> LLM_BASE_URL=https://api.deepseek.com
> LLM_MODEL=deepseek-flash
> LLM_API_KEY=sk-...
> ```
> 改完需 `docker compose up -d backend` 重建容器才能生效（环境变量不是热更新的）。
> 只改 `LLM_PROVIDER` 而忘了填 key，后端会在启动选 provider 时直接报错 —— 这是刻意的。

---

## 已完成能力

### Phase 1 — 工程基础

- [x] `frontend/` + `backend/` 双工程骨架（Next.js + TS + Tailwind / FastAPI）
- [x] PostgreSQL + Redis 的 Docker Compose 编排与健康检查
- [x] `.env.example` 全量配置 + 已生成真实 `.env`（含随机 `SECRET_KEY`）
- [x] SQLAlchemy 2.0（UUID 主键、时间戳 Mixin、命名约定）+ Alembic 迁移
- [x] `users` / `projects` / `episodes` 三张表 + 索引 + 级联删除
- [x] `GET /health` 裸契约 + `GET /api/v1/health/detail` 依赖检查
- [x] 统一 API Response Envelope + 完整错误码表
- [x] 全局异常处理（AppError / Pydantic 校验 / HTTPException / 未捕获异常）
- [x] `request_id` 生成、透传、响应头回写、日志关联
- [x] 结构化 JSON 日志 + 敏感信息脱敏过滤器
- [x] Provider 抽象层接口（LLM / Image / Video / TTS），**未接真实厂商**
- [x] 前端 API 客户端（Envelope 解包 + 错误分类）+ 加载/空/错误三态组件

### Phase 2 — 项目系统

- [x] 注册 / 登录 / 当前用户（JWT，bcrypt 预哈希口令）
- [x] `get_current_user` 统一鉴权依赖，受保护路由一律 401 而非裸 403
- [x] Repository / Service 分层落地（`base` / `user` / `project`）
- [x] Project CRUD：创建 / 列表（分页·搜索·筛选）/ 详情 / 局部更新 / 删除
- [x] 故事文本录入与保存（`story_source` + `story_text`，迁移 `0002`）
- [x] **跨用户越权隔离**：他人项目一律 404（非 403），不泄露资源是否存在
- [x] 口令强度校验、邮箱大小写归一化、错误信息不泄露账号是否注册
- [x] 前端：首页项目列表（卡片 / 搜索 / 状态筛选 / 分页 / 空态）
- [x] 前端：登录注册页（同一表单切换、按 `next` 参数回跳）
- [x] 前端：创建项目页（题材·画风·故事来源·故事文本，即时校验）
- [x] 前端：项目详情页（左侧导航，概览 / 故事设定 / 设置 可用，其余标注 Phase）
- [x] 删除二次确认；401 自动清理本地会话并回登录页
- [x] 迁移 `0002_project_story`；SQLite 与 Postgres 双验证零漂移
- [x] pytest **113 项**全绿；ruff 全通过
- [x] 端到端验收脚本：`verify_phase1.sh`（18 项）+ `verify_phase2.py`（84 项）

**未做（刻意）**：AI Story Parser、`/analyze` 与 `/bible` 接口、图片/视频/TTS、
异步任务、任何真实模型调用。

### Phase 3 — Story Agent

- [x] LangGraph 工作流：`story_parser → character_extractor → location_extractor`
- [x] `LLMProvider` 抽象 + **Mock Provider**（离线确定性，无需 key / 无需网络）
- [x] OpenAI 兼容 Provider（纯 httpx）：OpenAI / DeepSeek / Moonshot / vLLM / Ollama
- [x] 结构化输出：JSON 提取 → Pydantic 校验 → **失败把错误回灌并重试** → 超限不写库
- [x] 字段别名归一化 + `extensions` 兜底，模型自创字段名不再导致内容丢失
- [x] Prompt 外置为版本化文件（`prompts/story/*.md`），每次生成记录 `prompt_version`
- [x] `characters` / `locations` 两张表 + 迁移 `0003`（双库零漂移、可回滚）
- [x] 接口：`/analyze`、`/analyze/status`、`/bible`、人物与场景的 CRUD
- [x] 重新解析按名字 **upsert**：主键稳定、用户手改内容不丢、未再产出者被清理
- [x] 分析状态机（`NOT_ANALYZED` / `RUNNING` / `SUCCEEDED` / `FAILED`）+ 失败原因落库
- [x] 前端：`Story Agent 解析`面板 + Story Bible 展示（含「AI 补充设定」与运行详情）
- [x] 前端：人物 / 场景 tab，可查看、编辑外貌与光线、删除
- [x] **跨用户越权隔离覆盖到人物/场景**（需穿过 join，他人资源一律 404）
- [x] 用户显式填写的题材/画风会被**钉住**，不被模型的推断改写（`_meta.pinned_from_user`）
- [x] pytest **316 项**全绿；ruff 全通过
- [x] 端到端验收脚本：`verify_phase3.py`（132 项，真实 HTTP + 真实模型下 **0 失败**）
- [x] 前端在真实浏览器中渲染验证（Playwright + 系统 Chrome，18 项断言，无 console 错误）

**未做（刻意）**：剧本 / 分镜 / 图片 / 视频 / TTS、Celery 异步化、token 成本计量。
解析目前是同步的（真实模型 20–90 秒阻塞请求），异步化属 Phase 5。

---

### Phase 4 — Episode Agent

- [x] LangGraph 全链：`story_parser → character_extractor → location_extractor
      → episode_planner → script_generator → storyboard_generator → consistency_checker`
- [x] 四个**单节点图**（规划 / 剧本 / 分镜），只重跑某一集不必从故事解析开始
- [x] `generate_structured()` 增加 `post_validate` 回调，表达 schema 之外的硬约束
- [x] **id 绑定校验**：剧本里的 `character_id` / `location_id` 必须存在于数据库，
      模型写角色名而非 id 会被识别并重试（PRD §10）
- [x] **分镜必须覆盖剧本的每个场景**，不多不少；缺场景会重试而不是静默丢戏
- [x] 重试用尽即失败，**绝不把带悬空 id 的数据落库**
- [x] 确定性一致性检查器（不调模型）：人物 / 场景 / 画风 / 光照 / 时长 / 台词逐项核对
- [x] `shots` 表 + 迁移 `0004`（双库零漂移、可回滚）；`shot_number`（场内）与
      `sequence`（全篇绝对序）并存，为 Phase 5-7 挂媒体预留 `*_asset_id`
- [x] 14 个接口：分集 CRUD、规划、剧本读写与生成、分镜读写与生成、镜头列表与修改、一致性复检
- [x] 守卫：未解析 / 重复规划 / 先分镜后剧本均 409；重新生成剧本会作废旧分镜
- [x] 失败不销毁旧产出：`script_status=FAILED` 时上一次的剧本仍可查看
- [x] `PATCH /shots/{id}` 严格校验枚举 —— 用户输入永不被静默改写（与模型输出策略不同）
- [x] 前端：剧集 tab（分集列表 / 剧本视图 / 分镜卡片 / 一致性面板，镜头可手改）
- [x] 前端：长时间生成显示已用秒数（剧本约 25s、分镜约 60s），避免重复点击
- [x] pytest **442 项**全绿；ruff 全通过
- [x] 端到端验收脚本：`verify_phase4.py`（87 项，真实 HTTP + 真实模型下 **0 失败**）
- [x] 浏览器验收 `verify_ui_phase4.py`：剧集列表 / 剧本 / 分镜 / 改镜头后刷新仍在，无 console 错误

**未做（刻意）**：图片 / 视频 / TTS / 合成、Celery 异步化、token 成本计量、
分镜的局部重生成、真正的视觉一致性比对（现为文本子串证据）。

已知限制：生成仍是**同步阻塞**的；一致性检查里的「像不像」判定是子串匹配而非视觉理解
（详见 docs/TDD.md §18.9）。

---

## 下一步：Phase 5（图片生成）

1. `ImageProvider` 抽象 + Mock 实现（沿用 Phase 1 接口，见 docs/TDD.md §10）
2. 参考图与 Prompt Builder：把 Character/Scene/Style Bible 拼进绘图提示词
3. Celery + Redis 异步任务：图片生成不能阻塞 HTTP
4. `assets` 表；把生成结果挂到 `shots.image_asset_id`（列**已存在**，无需新迁移）
5. 前端：素材 tab（`素材` / `生成任务` 两个 tab 仍是 Phase 5 占位）

> 注意：Phase 5 **不要**碰视频与 TTS —— 那些属 Phase 6/7。

---

## 开发约定

- 只按 Phase 推进，一个 Phase 完成 → 跑测试 → 修错 → 更新文档/迁移 → git commit。
- AI 输出必须结构化（Pydantic 校验），禁止把 LLM 原文直接写入数据库。
- 业务代码不得直接依赖具体模型厂商，一律走 `providers/`。
- 视频/图片/TTS 等长任务必须异步，绝不阻塞 HTTP 请求。
- 不留「无法运行的伪代码」——每个功能都要能独立运行和验证。

### Phase 5 — 图片

- [x] `assets` + `generation_tasks` 两张表（迁移 `0005`），含幂等用的部分唯一索引
- [x] Storage 抽象 + **签名 URL**（PRD §27）：未签名访问一律 403，签名可过期不可伪造
- [x] 移除 Phase 1 的公开 `/static` 挂载（URL 即凭证，不符合越权要求）
- [x] ImageProvider 抽象：`mock`（纯标准库真 PNG，像素内嵌提示词哈希条码）/ OpenAI 兼容
- [x] **Prompt Builder**：按 PRD §19 六层确定性拼装（画风 / 人物 / 场景+光线 / 本镜 / 运镜 / 情绪 / 参考图）
- [x] Prompt 措辞全在 `prompts/image/*.md`（PRD §20 版本化），空层整行丢弃不留半句话
- [x] Character Reference / Location Reference 参考图（写入 `reference_image_url`，读取时续签）
- [x] 逐镜出图 + 整集批量补齐 + 单镜重生成（保留旧图）
- [x] **Redis + Celery 独立 worker 容器**（PRD §21），状态机 PENDING→RUNNING→SUCCESS / FAILED→RETRY
- [x] 幂等双保险：在途任务复用（DB 部分唯一索引）+ 已成功任务不重复执行
- [x] 失败不销毁已有产出：重生成失败时镜头仍是 COMPLETED
- [x] API（PRD §22）：`shots/{id}/image/generate`、`shots/{id}/regenerate`、`tasks/{id}`、
      `projects/{id}/tasks`、`tasks/{id}/retry`；➕ 4 个附加端点（参考图 ×2、整集批量、
      **素材列表**）已在 TDD §19.7 标注
- [x] 前端：镜头卡片内联图片 + 生成/重生成/重试 + 整集工具栏 + 参考图按钮；轮询到终态自动停止
- [x] 前端：**素材页**（素材网格 + 类型筛选）与**生成任务页**（任务状态 + 失败重试），
      对应 PRD §5.3 左导航中标注 Phase 5 的两页
- [x] 分镜响应一次带回每镜 `media`（图片、尝试次数、待轮询任务），避免 N+1 请求
