# AI Studio V1.0 — TDD（技术设计文档）

> 配套文档：[PRD.md](./PRD.md)（产品需求 + 开发执行规范）
> 本文档只记录**已经实现**的设计与决策，未实现的部分明确标注为「待开发」。

版本：V1.0 Phase 1
最后更新：2026-09-14

---

## 1. 架构总览

```
Browser (Next.js App Router)
   │  fetch + 统一 Envelope 解包
   ▼
FastAPI (app.main:app)
   │  RequestContextMiddleware → request_id
   │  AppError / ValidationError / HTTPException 全局处理器
   ▲
   ├── core/          config · database · logging · security · responses · exceptions
   ├── api/v1/        routers（health）
   ├── models/        SQLAlchemy 2.0 ORM
   ├── schemas/       Pydantic v2（含统一 Envelope）
   ├── repositories/  数据访问层（Phase 2+）
   ├── services/      业务逻辑（Phase 2+）
   ├── agents/        LangGraph 工作流（Phase 3+）
   ├── providers/     LLM / Image / Video / TTS 抽象（Phase 1 仅接口）
   ├── tasks/         Celery 任务（Phase 5+）
   └── workers/       Celery worker 入口（Phase 5+）
   ▼
PostgreSQL 16（+ pgvector 待启用） · Redis 7 · 本地存储目录（后续切 S3/OSS）
```

**原则**：路由只做参数校验与序列化；业务规则进 `services/`；只有 `repositories/`
碰数据库；只有 `providers/` 碰外部 AI 厂商。

---

## 2. 分层与依赖规则

| 层 | 目录 | 允许依赖 | 禁止 |
| --- | --- | --- | --- |
| API 层 | `app/api/` | schemas、services | 直接写 SQL、直接调 provider |
| Service 层 | `app/services/` | repositories、providers、schemas | 依赖 `Request` / HTTP 状态码 |
| Repository 层 | `app/repositories/` | models、core.database | 业务规则 |
| Provider 层 | `app/providers/` | 第三方 SDK | 依赖 models、数据库 |
| Agent 层 | `app/agents/` | providers、services | 直接落库（通过 service） |

业务代码里**不允许**出现 `openai.xxx()` 这类散落的厂商调用（PRD §16）。

---

## 3. 配置管理

- 单一入口 `app/core/config.py::Settings`（pydantic-settings）。
- 读取顺序：环境变量 > `backend/.env` > 仓库根 `.env` > 默认值。
- 全部变量样例见仓库根 [`.env.example`](../.env.example)。
- 派生属性：`is_sqlite`、`broker_url`、`result_backend`、`is_production`。
- `CORS_ORIGINS` 同时支持 `a,b` 与 `["a","b"]` 两种写法。
- **密钥只来自环境变量**，源码与镜像内不含任何凭据。

---

## 4. 数据模型（Phase 1 已建表）

```
users ──1:N── projects ──1:N── episodes
```

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `users` | id(UUID PK) · email(唯一) · password_hash · created_at · updated_at | 认证主体 |
| `projects` | id · user_id(FK, CASCADE) · name · genre · style · description · story_bible_json(JSON) · status | Story Bible 结构化存储，**不做自由文本字段** |
| `episodes` | id · project_id(FK, CASCADE) · episode_number · title · summary · duration · script_json(JSON) · storyboard_json(JSON) · status | 同项目内 `(project_id, episode_number)` 唯一 |

设计决策：

1. **主键统一 UUID**（`sa.Uuid`）——避免自增 ID 泄露业务规模，便于后续分库。
2. **枚举字段用 `String(32)` 而非原生 PG enum**——新增状态无需 `ALTER TYPE` 迁移，
   取值在 `app/models/enums.py` 用 `StrEnum` 约束（`EpisodeStatus` 等）。
3. **结构化产物存 JSON 列**——`story_bible_json` / `script_json` / `storyboard_json`
   写入前必须经 Pydantic 校验（Phase 3 落地），杜绝「AI 原文直存数据库」。
4. **级联删除**：删除 user → project → episode 全部级联；大文件永存数据库之外。
5. 约定命名：`MetaData(naming_convention=...)`，保证 Alembic autogenerate 差异稳定。

后续阶段追加：`characters` `locations` `scripts` `storyboards` `shots` `assets`
`generation_tasks` `voices` `story_memories`（PRD §17）。

---

## 5. 数据库迁移策略

- Alembic，脚本位于 `backend/migrations/`。
- `env.py` 的 URL **永远取自 `Settings`**，与运行时同一份配置。
- 迁移文件手写而非 autogenerate 后放任不管：`alembic check` 必须报
  「No new upgrade operations detected.」才算模型与迁移一致（已纳入验证流程）。
- 容器启动时执行 `alembic upgrade head`，不在应用代码里 `create_all()`。

当前迁移：`0001_initial`（users / projects / episodes + 3 个索引）。

---

## 6. 统一响应规范

所有 JSON 接口返回（PRD §23）：

```json
{ "success": true,  "data": {}, "error": null, "request_id": "req_1a2b..." }
{ "success": false, "data": null,
  "error": {"code": "GENERATION_FAILED", "message": "..."},
  "request_id": "req_1a2b..." }
```

实现：`app/core/responses.py`（`build_envelope` / `ok` / `fail`）。

**唯一例外**：`GET /health` 按 PRD §31 返回裸对象 `{"status": "ok"}`，供 Docker
healthcheck 与负载均衡使用。带依赖检查的版本是 `GET /api/v1/health/detail`（走 Envelope）。

### 错误码表（`app/core/exceptions.py`）

| code | HTTP | 触发 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 / 400 | Pydantic 校验失败 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 唯一约束冲突 |
| `UNAUTHORIZED` | 401 | 未认证 / token 失效 |
| `FORBIDDEN` | 403 | 越权访问他人资源 |
| `METHOD_NOT_ALLOWED` | 405 | 方法不支持 |
| `RATE_LIMITED` | 429 | 限流 |
| `PROVIDER_ERROR` | 502 | 上游 AI 厂商失败 |
| `GENERATION_FAILED` | 422 | 生成任务业务失败 |
| `TIMEOUT` | 504 | 超时 |
| `INTERNAL_ERROR` | 500 | 未捕获异常（详情只进日志，不回客户端） |

---

## 7. request_id 与日志

- `RequestContextMiddleware` 为每个请求分配 `req_<16hex>`；请求头已带
  `X-Request-ID` 时沿用调用方的值（便于前后端 / 网关串联）。
- 通过 `contextvars` 传递，日志过滤器与响应封装都能取到，无需逐层透传参数。
- 响应头回写 `X-Request-ID`，响应体 `request_id` 与其一致。
- 日志为单行 JSON（`LOG_JSON=true`）：`timestamp / level / logger / message /
  request_id / http_method / http_path / http_status / latency_ms`。
- **脱敏**：`RedactionFilter` 抹掉 `password`/`token`/`api_key`/`secret` 等字段，
  并对 `sk-...`、`Bearer ...`、`password=...` 文本做正则替换（PRD §28）。

---

## 8. 安全

| 项 | 实现 |
| --- | --- |
| 密码存储 | bcrypt，**先 SHA-256+base64 预哈希**再加密，规避 bcrypt 72 字节静默截断 |
| 会话 | JWT（HS256，`sub`/`iat`/`exp`），密钥来自 `SECRET_KEY` |
| 鉴权依赖 | `app/api/deps.py` 预留；`get_current_user` 于 Phase 2 实现 |
| 资源隔离 | 所有 project 查询必须带 `user_id` 过滤（Phase 2 落地并测试） |
| 密钥 | 全部环境变量；前端只暴露 `NEXT_PUBLIC_*` |
| 文件访问 | Phase 1 本地静态目录；上线前切签名 URL |
| FFmpeg | 后端拼装安全参数，禁止接受用户传入的任意命令（PRD §24） |

---

## 9. 测试策略

- `pytest` + `fastapi.testclient`。
- **不 mock 数据库**：测试跑真实 SQLAlchemy + 文件型 SQLite，
  这样才能真正验证 ORM 映射、唯一约束、JSON 往返与级联删除。
- 测试用环境变量在 `tests/conftest.py` 顶部注入，**早于**任何 `app.*` 导入，
  保证 settings/engine 以测试配置构建。
- 采用文件型 SQLite（而非 `:memory:`）：TestClient 的 lifespan 关闭时会
  `engine.dispose()`，内存库会随之消失导致后续测试报 "no such table"。
- 每个测试后清表，测试之间互不依赖。
- 覆盖范围：健康检查契约、Envelope 形状、request_id 传递、错误处理器、
  ORM 持久化与约束、密码/JWT、日志脱敏、配置解析。

```
37 passed
```

---

## 10. Provider 抽象层（Phase 1 仅接口）

`app/providers/base.py` 定义四组 `Provider` + `Request` + `Result`：

| 抽象 | 方法 | 实现阶段 |
| --- | --- | --- |
| `LLMProvider` | `generate(LLMRequest) -> LLMResult` | Phase 3（含 Mock Provider） |
| `ImageProvider` | `generate(ImageRequest) -> ImageResult` | Phase 5 |
| `VideoProvider` | `generate(VideoRequest) -> VideoResult` | Phase 6 |
| `TTSProvider` | `generate(TTSRequest) -> TTSResult` | Phase 7 |

所有请求对象都带 `prompt_version` 字段，为后续 Prompt 版本化 / A/B 预留（PRD §20）。
`Settings.*_provider` 当前全部为 `mock`，**Phase 1 未接入任何真实 AI 服务**。

---

## 11. 部署拓扑

```
docker compose
├── postgres:16-alpine   healthcheck: pg_isready
├── redis:7-alpine       healthcheck: redis-cli ping
├── backend (Dockerfile) depends_on 两者 healthy → alembic upgrade head → uvicorn
└── frontend (Dockerfile) next build → standalone server.js
```

- 卷：`postgres_data` / `redis_data` / `storage_data` 持久化，
  **重启不丢已生成资产**（PRD §21 幂等与可恢复的前置条件）。
- 后端镜像预装 `curl`（healthcheck）。
  **ffmpeg 刻意不在 Phase 1 镜像里**：它属于 Phase 8（合成），会带来约 135MB
  下载 / 470MB 安装体积并显著拖慢构建；到 Phase 8 再在 Dockerfile 中加回
  （Dockerfile 内已留好注释与现成命令）。
- 前端镜像多阶段构建，`output: "standalone"`，以非 root 用户 `nextjs` 运行。
- 本地开发与容器共用同一套 `.env`，仅 host 名不同（`localhost` ↔ `postgres`/`redis`）。

---

## 12. 前端设计要点

- App Router + TypeScript strict + Tailwind。
- `lib/api.ts`：**唯一** fetch 出口。自动解包 Envelope，失败抛 `ApiError`
  （携带 `code` / `status` / `request_id` / `details`），网络层失败归为
  `NETWORK_ERROR` 并给出「后端不可达」提示，绝不静默吞错。
- `hooks/use-async.ts`：loading / error / reload 三态，Phase 1 不引第三方数据层。
- `components/states.tsx`：`LoadingState`（骨架屏）/ `EmptyState` / `ErrorState`，
  统一 Phase 2 各列表页的空态与错误态。
- 首页实时探测 `GET /api/v1/health/detail`，把后端连通性、版本、延迟直接展示出来
  ——这是 Phase 1 的验收面。

---

## 13. 已知工程坑（Phase 1 实测记录）

1. **`PYTHONPATH` 污染**：宿主环境若预设 `PYTHONPATH` 指向别的 site-packages，
   `pytest` 会加载到错误的 FastAPI/Starlette（表现为启动即 `OperationalError`）。
   运行后端测试前 `unset PYTHONPATH`，或用项目 venv 的 python 直接执行。
2. **pydantic-settings 会先 JSON 解码复杂字段**：`CORS_ORIGINS=http://a,http://b`
   这种写法在 `mode="before"` 校验器跑之前就抛
   `SettingsError: error parsing value for field "cors_origins"`。
   解法是给字段加 `Annotated[list[str], NoDecode]`，把解析权完全交给校验器。
   （只验证「程序化传参」不够，必须测「从 .env 文件读取」——见
   `tests/test_config.py::test_cors_origins_from_dotenv_file`。）
3. **SQLite 内存库 + lifespan**：见 §9 测试策略。
4. **Next.js `output: "standalone"` 与 `next start` 互斥**：`next start` 会直接报
   「does not work with output: standalone」。因此 standalone 只在 Docker 构建时
   通过 `NEXT_OUTPUT_STANDALONE=1` 开启（见 `frontend/next.config.ts`），本地
   `npm start` 保持可用。
5. **Windows/git-bash 下的脚本路径**：curl 是原生 Windows 二进制，无法写入
   MSYS 风格的 `/tmp/...` 绝对路径（报 `client returned ERROR on write`）。
   因此 `scripts/verify_phase1.sh` 使用仓库相对的临时目录。
6. **宿主端口占用**：本机 6379 已被另一套本地栈（wkcrm 的 redis，带密码）占用，
   故 AI Studio 的 redis 宿主端口默认映射为 **6380**（容器内仍是 6379）。
7. **Docker 镜像源**：原 `daemon.json` 中的 `rlmws9iw.mirror.aliyuncs.com` 已失效
   （403），拉取任何镜像都会失败；已切换为 `docker.1ms.run` /
   `docker.m.daocloud.io` / `dockerproxy.net`。若后续再出现 403，先检查镜像源。
   注意：改完 `daemon.json` 必须 `docker desktop restart`（或重启 Docker Desktop）
   才生效，仅在进程内重启不够。
8. **C 盘空间与数据落盘位置**：本机 C 盘容量紧张（曾一度只剩 38MB），而 Docker
   Desktop 的镜像/容器数据默认写在 C 盘用户目录，与项目代码放哪块盘无关。
   处理方式（透明、无需改 Docker 配置）：
   - 关闭 Docker + `wsl --shutdown`（`wslservice` 会占用 vhdx 句柄）
   - `robocopy /MOVE` 把 `%LOCALAPPDATA%\Docker\wsl` 整体搬到 `D:\Docker\wsl`
   - 用目录联接指回原路径：`New-Item -ItemType Junction -Path
     "$env:LOCALAPPDATA\Docker\wsl" -Target "D:\Docker\wsl"`
   - 验证：`(Get-Item ...).LinkType` 为 `Junction`，且 `docker images` 中镜像完好
   另外 uv / pip 缓存已通过用户级环境变量 `UV_CACHE_DIR` / `PIP_CACHE_DIR`
   重定向到 `D:\HermesWorkplace\cache\`，npm cache 在 D 盘 `node_cache`。

---

## 14. Phase 状态

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 1 | 工程基础（前端/后端骨架、PG、Redis、Compose、迁移、/health、统一响应、request_id、异常处理、测试） | ✅ 已完成 |
| 2 | 项目系统（认证、Project CRUD、Story 输入、列表/详情/创建页） | ✅ 已完成 |
| 3 | Story Agent（LangGraph、Story Bible、Character/Location、Mock LLM Provider） | ⏳ 待开发 |
| 4 | Episode Agent（Planner / Script / Storyboard / Consistency） | ⏳ 待开发 |
| 5 | 图片（ImageProvider、参考图、Prompt Builder、异步任务） | ⏳ 待开发 |
| 6 | 视频（VideoProvider、轮询、重试、Asset 存储） | ⏳ 待开发 |
| 7 | TTS（音色绑定、台词音频） | ⏳ 待开发 |
| 8 | 合成（字幕、BGM、FFmpeg、成片） | ⏳ 待开发 |

---

## 15. Phase 2 设计（项目系统）

### 15.1 分层落地

```
请求 → api/v1/*.py       只做参数校验 + 序列化，不含业务规则
        ↓
      services/*.py      鉴权后的业务规则；唯一提交事务的地方
        ↓
      repositories/*.py  唯一触碰 ORM Session 的地方
        ↓
      models/*.py
```

- `repositories/base.py` 提供最小 CRUD 原语（`get` / `add` / `delete` / `save`），
  子类只加自己需要的查询；**读取方法不隐式提交事务**。
- `services/` 是唯一调用 `db.commit()` 的层，便于把同一套逻辑复用到 Celery worker。
- `api/deps.py` 用 `Annotated` 别名（`CurrentUser` / `ProjectServiceDep`）让路由签名保持简洁。

### 15.2 认证

| 项 | 实现 |
| --- | --- |
| 令牌 | JWT（HS256），`sub` = user id，附带 `email` claim |
| 传输 | `Authorization: Bearer <token>`（`HTTPBearer(auto_error=False)`） |
| 口令 | bcrypt，先 SHA-256+base64 预哈希以规避 72 字节静默截断 |
| 校验 | `get_current_user`：解析 → 查库 → 用户必须仍存在 |
| 注册 | 邮箱归一化为小写后存储，唯一约束兜底 |
| 强度 | ≥8 位且不能纯字母或纯数字 |
| 防枚举 | 登录失败时「邮箱不存在」与「密码错误」返回完全相同的错误体 |

`HTTPBearer(auto_error=False)` 是有意为之：默认的 `auto_error=True` 会抛 Starlette 裸
403，绕过统一 Envelope；关掉后由我们抛 `UnauthorizedError`，保证仍是 401 + 统一错误码。

**令牌不携带权限信息**，每次请求都重新查库。这样封禁/删除用户立即生效，代价是每请求一次主键查询 ——
在当前量级下完全可接受，也让「签名有效 ≠ 用户有效」这条边界清晰可见（见
`test_token_for_deleted_user_is_rejected`）。

### 15.3 越权隔离（本项目最关键的安全约束）

```python
# repositories/project.py
def get_for_user(self, project_id, user_id) -> Project | None:
    stmt = select(Project).where(
        Project.id == project_id,
        Project.user_id == user_id,
    )
    return self.db.execute(stmt).scalar_one_or_none()
```

三条规则：

1. **不存在无作用域的 getter**。仓库层不暴露「按 id 查项目」，从 API 表层就无从
   忘记加 `user_id`。
2. **他人项目返回 404 而非 403**。403 等于确认「这个 id 存在但不是你的」，
   可被用来枚举他人的项目 id；404 让两种失败不可区分。
3. **写路径同样受限**：PATCH / DELETE / story 读写全部先走 `get_for_user`。

对应测试：`test_projects_api.py::test_other_user_cannot_*` 与
`verify_phase2.py` 的 isolation 段（含「B 的响应体不含 A 的项目名」这类泄露检查）。

### 15.4 数据模型变更（迁移 `0002_project_story`）

`projects` 增加两列：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `story_source` | `String(32)` 可空 | `SYNOPSIS` / `NOVEL` / `SCRIPT`（PRD §5.2 故事来源） |
| `story_text` | `Text` 可空 | 原始故事文本，Phase 3 的解析输入 |

选择直接加列而非建 `stories` 表：V1 一项目一故事，多版本历史属于 PRD §2.2 的 P1。
`has_story` 不落库，由 `story_text` 是否非空派生，避免两个字段不同步。

### 15.5 前端

| 文件 | 职责 |
| --- | --- |
| `lib/session.ts` | 令牌与用户信息的 localStorage 读写；401 广播事件 |
| `lib/api.ts` | 唯一 fetch 出口，两个内部原语：`request`（返回 `data`）与 `requestEnvelope`（需要 `meta` 时用） |
| `components/auth-provider.tsx` | 登录态 Context；挂载时校验存量令牌；监听 401 事件 |
| `components/states.tsx` | `LoadingState` / `EmptyState` / `ErrorState` / `FormError` / `SignInRequired` |
| `app/page.tsx` | 首页项目列表（PRD §5.1）：卡片、搜索（300ms 防抖）、状态筛选、分页 |
| `app/login/page.tsx` | 登录/注册同表单切换，按 `next` 回跳 |
| `app/projects/new/page.tsx` | 创建项目（PRD §5.2 全部字段） |
| `app/projects/[id]/page.tsx` | 详情 + 左侧导航（PRD §5.3） |

前端设计要点：

- **令牌先校验再用**：`AuthProvider` 挂载时调 `GET /auth/me`。存量过期令牌若直接使用，
  会让后续每个请求都 401。网络错误时保留缓存的用户信息（后端可能只是挂了）。
- **401 全局处理**：`lib/api.ts` 在收到 401 时清理本地会话并派发
  `ai-studio:unauthorized`，`AuthProvider` 据此登出，避免「看起来已登录但请求全失败」。
- **错误可见**：`ApiError` 携带 `code` / `request_id` / 字段级 `details`，
  `FormError` 把 422 的字段校验信息逐条展示，而不是笼统提示「请求失败」。
- 详情页对未实现模块显式渲染「计划在 Phase N 交付」，不画不可用的假交互。
- 原有的 `hooks/use-async.ts` 在 Phase 2 已删除：各页面需要分页/重取等细粒度控制，
  统一的 hook 反而更绕，避免留下无引用的死代码。

### 15.6 已知限制

- **令牌存于 `localStorage`**：任何同源脚本都能读取，XSS 即等价于令牌泄露。
  httpOnly Cookie + CSRF 防护是正确解法，列为后续工作项。
- 未实现刷新令牌，令牌过期即需重新登录（`ACCESS_TOKEN_EXPIRE_MINUTES` 默认 1 天）。
- 未做登录失败频率限制（Phase 2 范围内不含防爆破）。

---

## 16. Windows/git-bash 验收脚本的编码坑

用 `curl -d '{"name":"中文"}'` 在 Windows/git-bash 下会把中文按本地代码页重新编码，
后端拿到非法 UTF-8 后返回 **400 `There was an error parsing the body`** ——
看起来像应用 bug，实际是测试载体的坑。表现为：纯 ASCII 载荷全部通过、含中文的载荷全部 400。

因此：

- `scripts/verify_phase1.sh` 载荷全为 ASCII，可以继续用 curl+bash；
- `scripts/verify_phase2.sh` 改成 `scripts/verify_phase2.py`（stdlib `urllib`），
  由 Python 显式编码 UTF-8，从根上消除这类假失败。

排查提示：遇到「同一接口 ASCII 通过、中文 400」时先怀疑 shell 编码，不要改后端。
