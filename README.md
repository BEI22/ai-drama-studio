# AI Studio V1.0

**AI 漫剧 / 连续剧自动创作平台** — 输入故事，自动产出剧本、分镜、图片、视频、配音、字幕，最终用 FFmpeg 合成一集可播放的 MP4。

```
故事 → 剧本 → 分镜 → 图片 → 视频 → 配音 → 字幕/BGM → 成片
```

> 当前状态：**Phase 1（工程基础）已完成**。
> 尚未接入任何真实 AI Provider（`*_PROVIDER=mock`），这是刻意为之 —— 先把地基跑通。

- 产品需求与开发规范：[docs/PRD.md](docs/PRD.md)
- 技术设计与分层规则：[docs/TDD.md](docs/TDD.md)

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 15（App Router）· TypeScript · React 19 · Tailwind CSS 3 |
| 后端 | Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic |
| 数据库 | PostgreSQL 16（pgvector 待 Phase 4 启用） |
| 缓存 / 队列 | Redis 7 · Celery（Phase 5 启用） |
| Agent | LangGraph（Phase 3 启用） |
| 存储 | 本地目录（Phase 1）→ S3/OSS（上线前） |
| 合成 | FFmpeg（Phase 8） |
| 部署 | Docker Compose |

---

## 目录结构

```
ai-studio/
├── frontend/                  # Next.js
│   ├── app/                   # layout / 首页
│   ├── components/            # Navbar、Loading/Empty/Error 状态组件
│   ├── hooks/                 # use-async
│   ├── lib/api.ts             # 唯一 fetch 出口 + Envelope 解包
│   └── Dockerfile
├── backend/                   # FastAPI
│   ├── app/
│   │   ├── api/v1/            # 路由
│   │   ├── core/              # config/database/logging/security/responses/exceptions
│   │   ├── models/            # ORM
│   │   ├── schemas/           # Pydantic
│   │   ├── services/          # 业务逻辑（Phase 2+）
│   │   ├── repositories/      # 数据访问（Phase 2+）
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

## 测试

```bash
cd backend
unset PYTHONPATH                      # Windows/git-bash 必要
.venv/Scripts/python.exe -m pytest -q

# 类型与静态检查
.venv/Scripts/python.exe -m ruff check app tests
cd ../frontend && npm run typecheck && npm run build
```

当前结果：**37 passed**（健康检查契约、统一响应 Envelope、request_id、错误处理器、
ORM 持久化与约束、密码/JWT、日志脱敏、配置解析）。

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

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/health/detail | python -m json.tool
```

Phase 2 起按 PRD §22 逐步补齐 projects / characters / episodes / script / storyboard /
shots / compose / tasks 等接口。

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
| `LLM_PROVIDER` 等 | `mock` | Phase 1 不接真实厂商 |
| `LOG_JSON` / `LOG_LEVEL` | `true` / `INFO` | 单行 JSON 日志，自动脱敏 |

`.env` 已在 `.gitignore` 中，不会被提交。

---

## Phase 1 已完成能力

- [x] `frontend/` + `backend/` 双工程骨架（Next.js + TS + Tailwind / FastAPI）
- [x] PostgreSQL + Redis 的 Docker Compose 编排与健康检查
- [x] `.env.example` 全量配置 + 已生成真实 `.env`（含随机 `SECRET_KEY`）
- [x] SQLAlchemy 2.0（UUID 主键、时间戳 Mixin、命名约定）+ Alembic 迁移 `0001_initial`
- [x] `users` / `projects` / `episodes` 三张表 + 索引 + 级联删除
- [x] `GET /health` 裸契约 + `GET /api/v1/health/detail` 依赖检查
- [x] 统一 API Response Envelope + 完整错误码表
- [x] 全局异常处理（AppError / Pydantic 校验 / HTTPException / 未捕获异常）
- [x] `request_id` 生成、透传、响应头回写、日志关联
- [x] 结构化 JSON 日志 + 敏感信息脱敏过滤器
- [x] Provider 抽象层接口（LLM / Image / Video / TTS），**未接真实厂商**
- [x] pytest 测试套件 37 项全绿；Alembic 迁移与模型零漂移
- [x] 前端 API 客户端（Envelope 解包 + 错误分类）+ 加载/空/错误三态组件
- [x] 首页实时展示后端连通性（Phase 1 验收面）
- [x] README / TDD / PRD 文档

**未做（刻意）**：AI Story Parser、图片/视频/TTS、异步任务、任何真实模型调用。

---

## 下一步：Phase 2（项目系统）

1. 用户注册 / 登录（JWT，`get_current_user` 依赖）
2. Project CRUD + **所有查询强制 `user_id` 过滤**（越权返回 403）
3. Story 文本输入与保存
4. 前端：登录页、项目列表页、创建项目页、项目详情页
5. Repository / Service 分层落地，Pydantic 输入输出 Schema
6. 单元测试 + API 测试；前端 loading / empty / error 三态接入真实接口

> 注意：Phase 2 **不要**实现 AI Story Parser —— 先把纯 CRUD 跑通并测试。

---

## 开发约定

- 只按 Phase 推进，一个 Phase 完成 → 跑测试 → 修错 → 更新文档/迁移 → git commit。
- AI 输出必须结构化（Pydantic 校验），禁止把 LLM 原文直接写入数据库。
- 业务代码不得直接依赖具体模型厂商，一律走 `providers/`。
- 视频/图片/TTS 等长任务必须异步，绝不阻塞 HTTP 请求。
- 不留「无法运行的伪代码」——每个功能都要能独立运行和验证。
