# AI Studio V1.0 — TDD（技术设计文档）

> 配套文档：[PRD.md](./PRD.md)（产品需求 + 开发执行规范）
> 本文档只记录**已经实现**的设计与决策，未实现的部分明确标注为「待开发」。

版本：V1.0 Phase 3
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

### 9.1 前端在真实浏览器中验证（Phase 3 起）

单元/API 测试无法证明「页面上真的长这样」。Phase 3 起增加一层浏览器验证：

- Playwright（独立 venv，不与项目依赖混用）+ **系统已装的 Chrome**
  （`channel="chrome"`，不额外下载浏览器内核）。
- 脚本用真实 HTTP 造数据（注册 → 建项目 → 跑真实解析），
  再注入 `localStorage` 的 token 直接进项目详情页，
  逐个 tab 断言关键元素可见，并**收集 console 错误**。
- 截屏留证，便于人工复核视觉结果。

三个必须避开的假绿：

1. **镜像里的前端是构建期产物**（`frontend` 服务没有挂载源码），
   改完前端**必须 `--build` 重建**，否则验的是旧 bundle。
2. **宿主残留的 dev server 会抢 3000**，让验收连到旧进程（见 §13.13）。
3. **locator 歧义**：`人物` 同时命中侧栏 tab 与「查看人物」按钮，
   要把定位范围收敛到 `nav[aria-label="项目导航"]` 内。

```
UI checks: passed=18 failed=0
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
9. **SQLite 默认不启用外键 → 级联删除静默失效**（Phase 3 实测）。
   关系用 `passive_deletes=True` 交给数据库级联，Postgres 会执行、**SQLite 不会**，
   于是删项目后留下孤儿人物/场景，且测试库行为与生产不一致、级联路径从未被测到。
   已在 `build_engine` 注册 `PRAGMA foreign_keys=ON` 的 connect 事件修正。
   教训：SQLite 与 PG 的语义差异会让「测试全绿但生产出错」，级联这类 DB 侧行为必须有测试。
10. **测试套件不得依赖 `.env`**（Phase 3 实测）。`Settings` 会读仓库根 `.env`，
    把 `LLM_PROVIDER` 指向真实厂商后，**整套测试会去调真实 API** ——
    有 key 时挂起在网络上，无 key 时失败。`tests/conftest.py` 现在把 LLM 相关变量
    钉死为 `mock`，并把 base_url 指向不可路由地址（意外外呼会快速失败而非挂起），
    另有 `test_suite_is_hermetic` 守卫防止回退。
11. **健康检查把 401 当健康**（Phase 3 实测）。`status_code < 500` 会让密钥失效的
    provider 显示为绿色，而每次真实调用都失败 —— 运维最容易被误导的场景。
    现用显式映射：2xx 健康，401/403 不健康，404/405 视为「路由未实现但主机可达」。
12. **测试 mock 会掩盖真实模型的字段命名差异**（Phase 3 实测，见 §17.4）。
    mock provider 的输出来自我们自己的代码，天然符合我们的 schema，
    因此真实模型用别名 key 导致字段被丢弃的问题只有接真模型才暴露。
    结论：涉及「外部系统的实际契约」的部分，必须至少跑一次真实调用。
13. **宿主残留 dev server 会让验收变成假绿**（Phase 3 实测）。先前 `npm run dev`
    起的 node 进程即使被 kill 也可能留下子进程继续占用 3000，
    于是 `docker compose up` 的 frontend 容器**启动失败**，
    而 `verify_phase1.sh` 的「frontend serves HTML」仍然 PASS —— 它连到的是那个
    旧进程，验的根本不是交付物。
    识别方法：`docker compose ps` 里没有 frontend，但 `netstat` 显示 3000 在监听。
    处理：用 PowerShell `Get-NetTCPConnection -LocalPort 3000` 找到 OwningProcess
    并 `Stop-Process`，再起容器；然后**重新跑一遍**验收。
14. **SQLAlchemy JSON 列：先赋值、再原地改字典 → 修改丢失**（Phase 3 实测，最隐蔽的一个）。
    `project.story_bible_json = {...}` 之后又 `project.story_bible_json["_meta"] = {...}`，
    中间创建人物时触发 **autoflush**，把该列按当时的内容写了一次；
    而 SQLAlchemy 不追踪 JSON 的原地变更，之后的 `_meta` 再也不会被 flush。
    结果：Postgres 上 `_meta`（provider / model / prompt_versions / usage / mock 标记）
    **从未落库**，`GET /bible` 的 `meta` 恒为 `null`，前端因此永远无法提示「这是 mock 输出」。
    为什么测试没抓到：断言读的是**同一个内存对象**（identity map 命中），
    只有 ``expire_all()`` 或换一个 Session 重新 SELECT 才看得到丢失。
    修法：**先把 dict 组装完整（含 `_meta`）再赋值**，且赋值放在最后；
    并用 `dict(...)` 复制，避免污染工作流返回的 state。
    教训：凡是「写库后还要再读」的字段，回归测试必须换 Session 读。

---

## 14. Phase 状态

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 1 | 工程基础（前端/后端骨架、PG、Redis、Compose、迁移、/health、统一响应、request_id、异常处理、测试） | ✅ 已完成 |
| 2 | 项目系统（认证、Project CRUD、Story 输入、列表/详情/创建页） | ✅ 已完成 |
| 3 | Story Agent（LangGraph、Story Bible、Character/Location、Mock LLM Provider） | ✅ 已完成 |
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

---

## 17. Phase 3 设计（Story Agent）

### 17.1 工作流

```
START → story_parser → character_extractor → location_extractor → END
```

严格对应 PRD §12。**媒体生成刻意不在图内**：PRD §12 要求 LLM 流程与长耗时任务分离，
图片/视频/TTS 属 Phase 5+ 的异步任务。`EXECUTION_ORDER` 与 mermaid 输出都有测试锁定。

节点用工厂函数闭包持有注入的 `LLMProvider`，因此图本身对厂商无感知，测试可注入脚本化 provider。

### 17.2 Provider 抽象（PRD §16）

| 实现 | 用途 |
| --- | --- |
| `MockLLMProvider` | 确定性离线启发式，**无需 key、无需网络**；输出带 `"_mock": true` |
| `OpenAICompatibleLLMProvider` | 纯 httpx，适配 OpenAI / DeepSeek / Moonshot / vLLM / Ollama |

由 `LLM_PROVIDER` 选择；业务代码只见 `LLMProvider` 接口。选真实 provider 但缺 key 时
**在构建期就报错**，而不是等第一个用户请求失败。

实测（DeepSeek `deepseek-flash`）：`LLM_BASE_URL=https://api.deepseek.com`，
`LLM_MODEL=deepseek-flash`。带 `/v1` 与不带 `/v1` 都可用（已实测 401 而非 404）。

### 17.3 结构化输出与重试（PRD §6）

`app/agents/structured.py::generate_structured()` 是唯一把 LLM 自由文本变成校验后对象的入口：

1. `extract_json()` 剥掉 Markdown 围栏与前后解释文字，取第一个完整 JSON 对象；
2. Pydantic 校验；
3. 失败时**把具体校验错误回灌进下一次 prompt**（盲目重发很少有用）；
4. 超过 `LLM_MAX_RETRIES` 抛 `GenerationFailedError`，**不写库**。

容错与严格的边界：**缺失的真实数据必须失败**（否则无法触发重试），
**纯格式差异必须被强制转换**（否则白白浪费一次重试）。因此
`"personality": "冷静"` 会被包装成 `["冷静"]`，而 `name` 缺失会报错。

### 17.4 字段别名归一化（实测坑，v2 prompt 的由来）

真实模型不遵守字段名。DeepSeek 实测返回 `core_conflict`（非 `main_conflict`）、
`setting`（非 `background`）、`visual_style`（非 `style`），
由于 schema 是 `extra="ignore"`，**约 30 个字段被静默丢弃**，`main_conflict` 直接是 `None`。

关键教训：**Mock provider 完全没暴露这个 bug** —— 因为它被写成只吐我自己定义的键。
这是「mock 掩盖真实缺陷」的典型案例。

三层修复：

1. `StoryBibleContent._normalize_keys` 把已知同义词折叠到规范字段；
2. 未能识别的字段进 `extensions`（`dict[str, Any]`）**保留而非丢弃**；
   赢过别名的规范键，其落选别名也一并保留；
3. prompt 升到 `story_parser_v2`，明确要求「严格使用下列键名」。

`extensions` 让「模型自发多给的设定」（主题、人物弧光、故事引擎…）在 UI 上以
「AI 补充设定」展示，不浪费模型的产出。

### 17.5 重新解析的语义

`replace=true` **按名字 upsert，不删表重建**：

- 主键稳定 —— Phase 4 的 shots 要引用 `character_id`；
- 用户手改过的外貌描述在重新解析后不丢；
- `replace=true` 只删除本次未再产出的人物/场景。

冲突守卫依据**分析状态**而非行数：改完故事会把状态置回 `NOT_ANALYZED` 但旧人物仍在，
此时重新解析正是用户的意图，不能报 409。已加回归测试。

### 17.6 Prompt 版本化（PRD §20）

prompt 是 `prompts/<domain>/<name>_v<N>.md` 文件，不写在 Python 里。
每次生成都记录 `prompt_version` 到 `_meta`，便于后续 A/B。
**改 prompt 内容必须升版本号**（v1 → v2），否则以 `story_parser_v1` 标注的历史结果会产生误导。

### 17.7 Story Bible 的存储

- `projects.story_bible_json`（JSON 列）存世界设定；
- `characters` / `locations` 各自建表 —— PRD §6 虽把二者列在同一 JSON 里，
  但作为独立表 + API 内联返回，保证**只有一个数据源**。
- `_meta`（provider/model/prompt_versions/usage）存在 JSON 列内，
  以 `_meta` 命名标记「不属于 Bible 本身」。

### 17.8 未做 / 已知限制

- 解析是**同步**的：真实模型 20–90 秒，请求会一直挂着。
  PRD §22/§25 的 Celery 异步化属 Phase 5，当前前端以「解析中…」提示覆盖。
- 无 token 成本计量（`estimated_cost` 恒为 0），PRD §26 待实现。
- `analysis_status` 的 `RUNNING` 只在同步执行期间可见，页面上几乎捕捉不到。

### 17.9 用户显式填写的内容必须钉住（genre / style）

`genre` 与 `style` 是用户在项目里**主动填写**的，属于决策而非模型的推断结果。
把它们放进 prompt 只是「建议」：实测真实模型在用户填「都市」时会返回「都市奇幻」，
于是页面上显示的是用户没选过的值，且会顺着 prompt 一路漂到 Phase 5 的绘图提示词。

`AgentService._pin_user_hints()` 在写库前把这两个字段强制覆盖为用户值，
并把实际钉住的字段记到 `_meta.pinned_from_user`，
因此调用方始终能区分「哪些来自模型、哪些来自用户」。

只钉**用户真正填了**的字段（空白/未填则留给模型），否则会把空值注入 Bible。

> 又是 mock 掩盖的一类问题：启发式引擎会把 hint 原样吐回，所以它永远「通过」。
> 回归测试用一个**故意与用户不一致**的 provider 来锁定该行为。

### 17.10 溯源信息（provenance）

`_meta`（provider / model / mock / prompt_versions / usage / max_retries / pinned_from_user）
存在 `story_bible_json` 列内，API 上提到响应顶层的 `meta` 字段。

两点值得记住：

1. 它是「输出是否可信」的唯一依据 —— `mock: true` 是前端提示「这不是真实模型输出」的开关，
   也是避免 mock 结果被误当成真实产出的防线。
2. 它曾经**从未落库**（见 §13.14 的 JSON 原地修改坑），
   所以 `GET /bible` 一直返回 `meta: null` 而无人察觉。
   现在有换 Session 读取的回归测试守着。
