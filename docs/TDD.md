# AI Studio V1.0 — TDD（技术设计文档）

> 配套文档：[PRD.md](./PRD.md)（产品需求 + 开发执行规范）
> 本文档只记录**已经实现**的设计与决策，未实现的部分明确标注为「待开发」。

版本：V1.0 Phase 5
最后更新：2026-09-16

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

Phase 4 起每个阶段各有一份脚本，`npm run verify:ui` **按顺序全部执行**
（写死单个脚本会让新阶段的 UI 悄悄逃过验证）：

| 脚本 | 断言数 | 覆盖 |
| --- | --- | --- |
| `cache/verify_ui_phase3.py` | 18 | 概览 / Story Bible / 人物 / 场景 / 后阶段占位 |
| `cache/verify_ui_phase4.py` | 见运行输出 | 剧集列表 / 剧本 / 分镜 / 一致性面板 / 改镜头后刷新仍在 |

四个必须避开的假绿：

1. **镜像里的前端是构建期产物**（`frontend` 服务没有挂载源码），
   改完前端**必须 `--build` 重建**，否则验的是旧 bundle。
2. **宿主残留的 dev server 会抢 3000**，让验收连到旧进程（见 §13.13）。
3. **locator 歧义**：`人物` 同时命中侧栏 tab 与「查看人物」按钮，
   要把定位范围收敛到 `nav[aria-label="项目导航"]` 内；
   Phase 4 的「分镜」同时命中面板 tab 与「**生成**分镜」按钮 ——
   用 `.first` 会点到后者并真的发起一次生成，见 §13.22。
   定 tab 一律用 `get_by_role(..., name=..., exact=True)`，不要用 `has_text` 子串。
4. **断言本身要能失败**（见 §13.4 与 §13.19）：先确认「无 console 错误」这条
   监听器是活的（故意 `console.error` 一次能被捕获），
   以及脚本里不要留下断言「某功能尚未实现」这类**会随交付过期**的检查。

```
Phase 3 UI checks: passed=18 failed=0
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
15. **ruff 配置放错位置 → `scripts/` 从未被 lint 过**（Phase 3 收尾时发现）。
    ruff 按「离目标文件最近」的配置逐级向上查找。原先 `[tool.ruff]` 写在
    `backend/pyproject.toml`，而 `scripts/` 在它管辖范围之外：
    - 从 **仓库根** 跑 `ruff check scripts/` → 找不到配置 → 退回内置默认
      （line-length 88），于是报告「需要重新格式化」；
    - 从 **backend/** 跑 `ruff check ../scripts/` → 命中 backend 配置
      （line-length 100）→ 报告「全部通过」。
    同一个文件「干净」还是「脏」取决于你站在哪个目录，**而 scripts/ 实际上
    从来没被真正的项目规则检查过**（隐藏的 `C401` 就是这么漏掉的）。
    修法：配置上移到仓库根 `ruff.toml`，成为唯一事实来源；
    并显式声明 `src = ["backend"]`，否则 isort 认不出 `app.*` 是 first-party，
    backend 里每个 import 块都会被误报为未排序。
    教训：lint 配置应当放在**被检查范围的最上层目录**，并且「lint 干净」这句话
    必须带上「对哪些路径、从哪个 cwd」才成立。
16. **`getattr(x, "f", None) or x.get("f")` 是个定时炸弹**（Phase 4 实测，本轮最严重的线上 500）。
    一致性检查器要同时接受 **Pydantic 对象**（Agent 节点传入）与 **dict**（service/API 从 JSON 列读出），
    于是写了这种「混合访问器」。它在属性**存在但取值为空**时崩溃：
    空列表是 falsy，短路逻辑继续走到 `or` 右边，对 Pydantic 对象调 `.get()` →
    `AttributeError: 'ScriptScene' object has no attribute 'get'`。
    为什么难发现：只在**「有角色出场但一句台词都没有」的纯动作场景**触发，
    所以看起来是间歇性的；而 mock provider 每个场景固定写一句台词，
    **离线永远复现不出来**，只有真实模型产出这种场景才炸。
    修法：抽一个统一的 `_get(obj, name)`（dict 走 `.get`，否则 `getattr`），
    并让所有规则对**两种输入形状**都断言、且结果必须完全一致（`TestConsistencyShapeParity`）。
    教训：**要兼容两种输入形状，就必须在一个地方统一处理**，不要在每个调用点临时判断；
    并且「为空」必须被当成合法值，不能与「不存在」混为一谈。
17. **用户输入被静默改写**（Phase 4 实测，与 §17.9 同源）。
    `ShotUpdate`（用户手改分镜）原先复用了 `ShotDraft` 的枚举 coerce，
    于是用户填 `超宽幅` 会被**悄悄改成 `medium` 并返回 200** —— 界面显示的不是用户选的值。
    这违反了「用户输入只接受或拒绝，绝不改写」这条既有约定。
    修法：`ShotDraft`（模型输出）继续 coerce —— 一个景别不精确好过整个分镜失败；
    `ShotUpdate`（人类输入）改为严格校验，未知值直接 422。
    教训：**「谁在输入」决定了校验策略**。同一份字段，模型输出与用户输入的处理必须分开写清楚。
18. **MSYS 风格路径当「文件参数」传给 Windows Python 会被解析错**（Phase 4 实测）。
    `/d/HermesWorkplace/cache/verify_ui_phase4.py` 传给 `python.exe` 后，
    Python 把开头的 `/d` 当成**相对路径**，解析成 `D:\d\HermesWorkplace\...` → `[Errno 2] No such file or directory`。
    注意：同一路径在 shell 里（cd、重定向）是好的，**只有作为参数交给原生 Windows 程序时才出问题**。
    修法：给 Python 的路径一律写成 `D:/HermesWorkplace/...`。
19. **验收脚本里「某功能尚未实现」的断言会变成定时炸弹**（Phase 4 交付时发现）。
    `verify_ui_phase3.py` 有一条 `check("episodes tab still marked unimplemented")` ——
    在 Phase 3 时它是正确的绿，Phase 4 交付后它**要么开始误报 FAIL，要么在侥幸通过时
    给出一个与产品相矛盾的结论**。这是「过期断言」：断言的是当下的进度，而不是产品的行为。
    发现后已改为指向 Phase 5 的「素材」tab。
    教训：验收脚本只能断言**行为不变量**（这页渲染出这些内容 / 没有 console error），
    不要断言「这块还没做」；每交付一个阶段，都要回头 grep 一次 `尚未实现` 之类的进度断言。
20. **lint 不只是格式问题，它会捞到真实 bug**（Phase 4 实测两例）。
    - `F811`：`app/api/v1/episodes.py` 同时 `from pydantic import ValidationError` 与
      `from app.core.exceptions import ValidationError`，后者**遮蔽**前者，
      于是 `except ValidationError` 抓的是自己的异常类而不是 Pydantic 的 ——
      「JSON 列里存量数据校验失败」这条降级路径实际是失效的。改用 `PydanticValidationError` 别名。
    - `B023`：一致性检查器里的内层 `def add(...)` 闭包**捕获循环变量**而非绑定值。
      一旦有任何延迟调用，问题就会被记到错误的镜头上。改为默认参数显式绑定。
    教训：`ruff check` 是**正确性**工具，不只是风格工具；出现新告警应先判断是不是真 bug，
    而不是无脑加 `noqa`。

21. **「假阳性机器」比没有检查更糟**（Phase 4 交付后实测，本轮最值得记住的一条）。
    一致性检查器原本有两条规则：场景设定的 `description` / `lighting` 若**没有逐字**出现
    在 `image_prompt` 里就报一条。离线（mock / 启发式 provider）它们表现得完美 ——
    因为 mock 的输出就是我们自己拼的字符串，必然包含原文。
    接真实模型后，一份 **54 镜头**的分镜上这两条分别报了 **52** 和 **41** 次，
    而抽查提示词发现：

    ```
    Bible  : 礼堂顶部大灯明亮，舞台聚光灯打在主席台上，座位区光线均匀偏暖
    prompt : ……顶部大灯明亮，座位区暖光均匀……      ← 意思完整，措辞不同
    ```

    也就是说这两条规则测的是「模型有没有照抄我的措辞」，而不是「提示词有没有写环境和光」。
    更荒谬的是 S2 镜 3 是一段**闪回出租屋**的镜头，它本来就不该出现礼堂的光照 ——
    严格匹配在这个场景上连「正确答案」是什么都判错了。
    93 条噪音的后果是：整个面板没人看，真正的问题也埋在噪音里。
    修法：换成一条**弱证据**规则 `SCENE_CONTEXT_MISSING`
    （提示词里一个环境/光线词都没有，才报，INFO 级），
    并为它写了**双向**测试：改写的提示词**不报**、只有人物没有环境的提示词**必须报**、
    衣着词（`白色`/`衬衫`）**不算**环境。第三条尤其重要 ——
    否则词汇表会慢慢放宽到永不触发，那是另一种失效。
    教训：**先问「这条规则在真实输入上误报率多少」，再问「它能不能发现坏情况」。**
    一个只在 mock 上表现良好的检查器是假绿的另一个变种（见 §13.12）。
22. **验收脚本会「触发」被验收的功能，从而破坏被测状态**（Phase 4 实测）。
    UI 验收里写了 `page.locator("button", has_text="分镜").first.click()` 想点「分镜」面板 tab，
    但 `has_text` 是**子串**匹配，页头的「生成分镜」按钮也命中，且 `.first` 取到的是它 ——
    于是脚本在真实浏览器里**发起了一次 104 秒的真实分镜生成**，
    把该剧集留在 `RUNNING` 状态，之后所有断言都在一个正在被写入的对象上跑。
    症状很有迷惑性：读数据库看到 `storyboard_status=RUNNING` 又已写入 `storyboard_generated_at`，
    看起来像「状态更新有 bug」；实际是我自己去点了那个按钮。
    修法：面板 tab 用 `get_by_role("button", name="分镜", exact=True)`，**别用 `has_text` 子串**；
    断言前先确认状态已收敛（`storyboard_status == SUCCEEDED`），
    不要把「进行中」的对象当成被测对象。
    顺带暴露的第三件事：tab 按钮里嵌着镜头数，可访问名是 `剧本8` 而不是 `剧本`，
    `exact=True` 匹配不到。修法不是改测试迁就它，而是把计数标成装饰性
    （`aria-hidden="true"`）—— 读屏本来也不该念出「剧本8」。
    **能被无障碍工具正确识别的名字，通常也是能被测试稳定定位的名字。**
    教训：验收脚本对被测系统是**有副作用的客户端**。
    点之前先问「这个 locator 还可能命中什么」，并让脚本在断言前把状态钉死。
23. **等待「错误的就绪信号」等于没有等待**（Phase 4 实测，两个假 FAIL）。
    脚本用 `wait_for_selector("text=分集规划")` 作为剧集 tab 就绪的标志，
    但「分集规划」这块面板是在 `listEpisodes` 返回**之前**就渲染的
    （`loading` 时列表被 `LoadingState` 替换，面板却已经在页面上）。
    于是后续断言在一个还没渲染列表的页面上跑，`EP01` 与「场戏」两条报 FAIL，
    而 3 秒后手工复测 `get_by_text("EP01")` 有 2 个命中。
    修法：等待**只有目标数据到位才可能存在**的文本（等 `EP01` 本身、等「场戏」那一行），
    而不是等同一屏里那个先渲染的容器标签。
    教训：出现「时快时慢的假 FAIL」时，先怀疑就绪信号选错了，不要先去改断言。

---

## 14. Phase 状态

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 1 | 工程基础（前端/后端骨架、PG、Redis、Compose、迁移、/health、统一响应、request_id、异常处理、测试） | ✅ 已完成 |
| 2 | 项目系统（认证、Project CRUD、Story 输入、列表/详情/创建页） | ✅ 已完成 |
| 3 | Story Agent（LangGraph、Story Bible、Character/Location、Mock LLM Provider） | ✅ 已完成 |
| 4 | Episode Agent（Planner / Script / Storyboard / Consistency） | ✅ 已完成 |
| 5 | 图片（ImageProvider、参考图、Prompt Builder、异步任务） | ✅ 已完成 |
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

---

## 18. Phase 4 设计（Episode Agent）

### 18.1 工作流（PRD §12）

PRD §12 把整条链路画成一条直线，Phase 4 补上后半段：

```
story_parser → character_extractor → location_extractor     (Phase 3)
  → episode_planner                                          (新)
  → script_generator                                         (新)
  → storyboard_generator                                     (新)
  → consistency_checker                                      (新)
```

`app/agents/__init__.py` 导出两个执行序：
`EPISODE_EXECUTION_ORDER`（本阶段四节点）与 `FULL_EXECUTION_ORDER`（七节点全链），
并有 mermaid 断言逐条锁定**边**（不只是节点名）—— 图被改错时测试会立刻报错。

为此提供了四个**单节点图**（`build_planner_graph` / `build_script_graph` /
`build_storyboard_graph` / `build_episode_graph`），让「只重跑某一集」不必从故事解析开始。

### 18.2 数据模型（迁移 `0004_episode_agent`）

- `shots`（新表）：PRD §17 的字段 + `sequence` / `characters_json` / 三个 `*_asset_id` 占位。
- `episodes` 增加 `script_status` / `storyboard_status` / `generation_error` /
  `script_generated_at` / `storyboard_generated_at`。

两个刻意的设计决定：

1. **`shot_number` 与 `sequence` 并存。** PRD §11 规定镜头在**场景内**从 1 编号，
   所以唯一约束是 `(episode_id, scene_id, shot_number)`；而渲染顺序、以及 Phase 5-7
   把生成媒体挂到具体镜头，需要**跨场景的绝对顺序**，这就是 `sequence`。
   两者都保留，避免以后为了排序去解析 `scene_id` 的字符串。
2. **`*_asset_id` 现在就建。** 它们是 Phase 5-7 的挂载点；`shots` 行存在的意义正是
   让之后生成的图片/视频/音频有一个稳定的归属。先建列比之后再迁移便宜。

枚举一律用 String（沿用 Phase 1 约定），vocabulary 由 Pydantic 把关。

### 18.3 结构化输出的两条硬规则

Phase 3 的 `generate_structured()` 只做 schema 校验；Phase 4 加了 `post_validate`
回调，用来表达**schema 表达不了**的约束：

- `script_generator`：每个 `character_id` / `location_id` 必须**存在于数据库**。
  Pydantic 只能校验「是非空字符串」，无法知道 uuid 是否真的存在。
  节点把 roster 的 id 集合传进 `post_validate`，不通过就**重试**（上限见 §18.4）。
- `storyboard_generator`：分镜必须**覆盖剧本的每一个场景**，不多不少。
  少一个场景 = 那一场戏的镜头全部凭空消失，且不会报错。

实测最常见的失败是模型直接写**角色名**而不是 id —— 只检查「非空」的校验会完全放行。

### 18.4 重试与失败语义

- 重试有上限；用尽后抛 `GenerationFailedError`，**绝不把带悬空 id 的数据落库**。
- 失败**不销毁上一次的成功产出**：`script_status=FAILED` 时 `script_json` 仍在，
  `storyboard_status=SUCCEEDED` 的记录照样能看。
  这是刻意的 —— 重生成失败不应该让用户失去已有的东西。
- **重新生成剧本会作废分镜**（shots 全部删除、状态置回 `NOT_GENERATED`）。
  理由：镜头挂在 `scene_id` 上，剧本一改，旧镜头就指向了不存在的场次；
  而 Phase 5-7 会按 shot 行挂媒体，留下旧行会让资产被**静默错误关联**。

### 18.5 一致性检查器（PRD §19）

PRD §19 列的输入是 Story Bible + Character Bible + Scene Bible + Style Bible + 参考图。
V1 只做**能从数据本身判定**的部分，其余明确不装作能判：

| 检查 | 级别 | 判定方式 |
| --- | --- | --- |
| `UNKNOWN_CHARACTER` | ERROR | 镜头里的角色名不在 Character Bible |
| `SCENE_NOT_IN_SCRIPT` | ERROR | 镜头所属场景不在剧本 |
| `SHOT_DURATION_INVALID` | ERROR | 时长 ≤ 0 |
| `SCENE_WITHOUT_SHOTS` | WARNING | 场景没有镜头 |
| `APPEARANCE_NOT_IN_PROMPT` | WARNING | 提示词里找不到该人物的外貌设定片段 |
| `SCENE_CONTEXT_MISSING` | INFO | 提示词完全没提环境或光线（取代了原先两条误报严重的规则，见 §13.21） |
| `STYLE_NOT_IN_PROMPT` | WARNING | 提示词里没有全局画风 |
| `DIALOGUE_NOT_IN_SCRIPT` | WARNING | 镜头台词与剧本不一致 |
| `EPISODE_DURATION_MISMATCH` | WARNING | 总时长偏差 > 35% |
| `SHOT_TOO_LONG` | WARNING | 单镜 > 12s |
| `VIDEO_PROMPT_MISSING` | INFO | 可选字段缺失 |

三条原则：

1. **判定「出现 / 不出现」用 ERROR/WARNING，判定「像不像」只能用 WARNING。**
   子串匹配是证据不是理解，不能因为提示词里少了一个词就让整份分镜「不可用」。
2. **干净输入必须零告警。** 一个「什么都报」的检查器能通过所有「它发现了 X」的测试
   却毫无用处，所以测试里最重要的一条是「干净分镜报告为空」（见 §18.7）。
3. **对自由散文只能用「弱证据」。** 这一条是交付后实测补上的，见 §13.21：
   `description` / `lighting` 是自由散文，模型**必然改写措辞**，
   于是「要求逐字复现某个分句」的检查在真实输出上 54 个镜头误报 93 次。
   凡是**短字段**（`hair` / `clothing` / `name` / `style`）逐字匹配是可信证据；
   凡是**长散文**，只能问「有没有提到环境或光」这种能由文本判定、且模型无法靠改写绕开的弱命题。

检查器**不调用模型**，因此 `GET /consistency` 可以随时免费复检。
该端点同时审剧本与分镜：只审分镜会让它对同一份数据给出与生成时**不一致**的结论
（剧本级的 `SPEAKER_NOT_IN_SCENE` 等会凭空消失）。

### 18.6 API（16 个端点）

PRD §22 为 Phase 4 规定的端点是 **10 个**，全部实现，无遗漏：

`GET/POST /projects/{id}/episodes`、`GET/PATCH /episodes/{id}`、
`GET/POST/PATCH /episodes/{id}/script[/generate]`、
`GET/POST/PATCH /episodes/{id}/storyboard[/generate]`。

另有 **6 个 PRD 未列、为实现 Phase 4 语义所必需的补充端点**（下表标 ➕）。
它们都是「PRD 规定了组件、但没规定触发入口」的补位，不是范围扩张：
Episode Planner 需要一个触发入口；UI 需要独立的复检与镜头读写路径。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/projects/{id}/episodes` | 分集列表（含 shot_count 等派生字段） |
| POST | `/projects/{id}/episodes` | 手动新增一集 |
| ➕ POST | `/projects/{id}/episodes/plan` | 运行 episode_planner（`replace` 需显式传） |
| ➕ DELETE | `/projects/{id}/episodes` | 清空分集计划 |
| GET | `/episodes/{id}` | 剧集详情 |
| PATCH | `/episodes/{id}` | 修改剧集 |
| ➕ DELETE | `/episodes/{id}` | 删除剧集 |
| GET | `/episodes/{id}/script` | 剧本（含 id→name 查表） |
| POST | `/episodes/{id}/script/generate` | 生成剧本 |
| PATCH | `/episodes/{id}/script` | 修改剧本（`scenes` 整体替换） |
| GET | `/episodes/{id}/storyboard` | 分镜文档 + 扁平镜头表 + 一致性报告 |
| POST | `/episodes/{id}/storyboard/generate` | 生成分镜并跑一致性检查 |
| PATCH | `/episodes/{id}/storyboard` | 修改分镜文档 |
| ➕ GET | `/episodes/{id}/shots` | 镜头列表 |
| ➕ PATCH | `/shots/{id}` | 修改单个镜头（枚举**严格**校验） |
| ➕ GET | `/episodes/{id}/consistency` | 复检（不调模型） |

写端点沿用本仓约定：顶层聚合（注册、建项目）返回 201，
**嵌套集合**（`POST /projects/{id}/episodes`）返回 200 —— 与 Phase 2/3 的
`POST /projects/{id}/characters` 一致。

### 18.7 测试策略

`445 passed`（Phase 3 时为 316）。本轮新增的重点：

- `test_episode_consistency.py::TestConsistencyShapeParity` —— 同一规则对
  **Pydantic 对象**与**dict** 两种输入断言，且结果必须完全一致。
  这一组直接对应 §13.16 的真实 500，并已**证伪过**：把修复回退后测试确实复现原始 `AttributeError`。
- **「干净输入零告警」** —— 上面所有「它发现了 X」的测试都无法证伪一个「什么都报」的实现，
  这一条才是它们的锚。
- **弱证据检查要双向测**（`TestSceneContextEvidence`）：改写的提示词**不报**、
  只有人物没有环境的提示词**必须报**、衣着词不算环境。
  并已用变异验证：把词汇表清空成 `()` 后，第一条立刻变成误报 ——
  证明基线那个「通过」是词汇表真的匹配上了，而不是断言恒真。
- **重试用假 provider 制造真实失败**：`ScriptedEpisodeProvider` 第一次返回**编造的 id**，
  第二次返回正确结果；断言不仅看最终产物，还断言**调用次数为 2**。
  若节点静默接受第一次输出，只看产物的断言仍会侥幸通过，所以次数必须一起断言。
- API 层：守卫（未解析/重复规划/先分镜后剧本全部 409）、id 绑定、越权隔离（404 而非 403）、
  重新生成后旧 shots 是否被清掉。

### 18.8 前端（剧集 tab）

`components/episode-agent.tsx`：分集列表 + 剧本视图 + 分镜卡片 + 一致性面板。

- **长时间生成必须显示已用秒数**。真实模型：规划约 6s、剧本约 25s、分镜约 60s。
  没有计时的话，60 秒的等待与「请求挂了」无法区分，用户会重复点击、产生重复工作。
- **id 与名字分别处理**：剧本台词带的是 `character_id`（uuid），
  分镜镜头带的是**角色名**。两者都通过页面下传的 Bible 解析成名字，界面不出现裸 uuid。
- **场景名要靠剧本反查**：`shots` 行只有 `scene_id`（`S3` 这种剧本标签），
  没有 `location_id`，所以分镜里的场景名必须经剧本映射得到。
- **出场角色不可在此编辑**。手输角色名会造出 Character Bible 里不存在的角色，
  正好破坏 §19 的一致性 —— 保持只读。
- 项目概览的流水线进度对「剧本生成 / 分镜生成」显示**「在剧集查看 →」**而不是「待开发」：
  项目详情接口只带一个集数计数，无法知道剧本状态，**不知道就不要给结论**。
- **刷新不能卸载子树。** 同一个症状（「已保存」提示出现即消失）有两个成因，
  都是「刷新时把组件换掉了」：
  1. 详情面板写成 `key={`${id}-${revision}`}`，用递增 `revision` 强制重新拉取 ——
     但改变 `key` 会**卸载并重建**整个子树。改为把 `revision` 作为 **prop**，
     由面板内的 `useEffect` 依赖它重新拉取；
  2. 列表与详情在 `loading` 时 `return <LoadingState/>`，而**任何一次**写入都会触发
     重新拉取并把 `loading` 置回 true —— 于是点一次「保存镜头」就把整个面板换成骨架屏，
     子组件连同刚设置的 `已保存` 状态一起被销毁，其他卡片里改到一半的内容同样被清空。
     改为只在**首次**加载显示骨架屏（`hasLoaded` 标志），后续刷新只显示「正在同步…」。
  代价是要显式处理「服务端值变了」：剧本梗概的 textarea 用 ref 记住
  上次采纳的服务端值，只有服务端真的变了才覆盖用户正在编辑的内容。
  教训：**`key` 是身份，不是刷新按钮；骨架屏是首次加载的状态，不是刷新状态。**
  这两个 bug 都只在浏览器里点一次按钮才暴露 —— 单元测试与 API 验收全绿也照样存在。

### 18.9 未做 / 已知限制

- 生成仍是**同步**的（规划 6s / 剧本 25s / 分镜 60s 都挂在请求上）。
  异步化（Celery）属 Phase 5，见 §17.8。
- `consistency_checker` 的「像不像」类判定是**子串匹配**，不是视觉理解；
  人物外貌只要写了关键片段即通过。真正的视觉一致性要靠 Phase 5 的参考图 + 审核环节。
- 逐镜头的**角色改为按名字绑定**（与剧本按 id 绑定不同）。
  这是 PRD §11 给的字段形态，代价是重命名人物后旧分镜会指向旧名字 —— 
  一致性检查器会把这种情况报成 `UNKNOWN_CHARACTER`，属于可接受的可发现失败。
- 未实现分镜的**局部重生成**（只重画某几个镜头）。

---

## 19. Phase 5 设计（图片流水线）

交付 PRD §31 Phase 5 的四项：**ImageProvider、Character Reference、Location Reference、
Prompt Builder、Image Task**，外加 §21 的异步架构落地。

### 19.1 端到端链路

```text
POST /api/v1/shots/{id}/image/generate      （API 层：只受理，不生成）
  ↓ 校验归属 + 幂等键 + 冲突守卫
generation_tasks 一行 PENDING
  ↓ .delay() → Redis（CELERY_BROKER_URL=redis://redis:6379/1）
Celery worker（独立容器 ai_studio_worker）
  ↓ execute_task()
Prompt Builder：读 Bible + shot，按 §19 六层拼装提示词
  ↓
ImageProvider.generate()（mock 或 openai 兼容）
  ↓ 返回 bytes（Provider 不碰存储）
StorageBackend.save() → storage/project/<pid>/<folder>/<eid>.png
  ↓
assets 一行（storage_key + 签名 url + metadata）+ shots.image_asset_id
  ↓
task → SUCCESS；客户端轮询 GET /api/v1/tasks/{id} 拿到结果
```

**关键分工**：API 层只写任务行并投递；Provider 只产出字节；Service 负责落盘与写
Asset。三者互不知道对方的实现细节，所以换 Provider 不影响 API，换存储不影响
Provider。

### 19.2 数据层（migration `0005_image_agent`）

| 表 | 说明 |
| --- | --- |
| `assets` | PRD §17 列集；`storage_key` 是文件的**持久身份**，`url` 是可再生的签名 URL |
| `generation_tasks` | PRD §17/§21；`status` 走 §21 的状态机 |

`shots.image_asset_id` 列 Phase 4 已建（PRD §17），本阶段开始真正写入。

**幂等**：`generation_tasks` 上有**部分唯一索引** —— 只约束 `status IN
(PENDING, RUNNING, RETRY)` 的行。因此「在途任务唯一」被数据库强制执行，而任务失败后
仍可用同一个 `idempotency_key` 重试（全量唯一索引会把重试也挡掉）。

### 19.3 存储与签名 URL（PRD §25、§27）

- 字节落盘（`STORAGE_LOCAL_DIR`，Docker volume `storage_data`，backend 与 worker
  **共享同一个 volume**：worker 写、API 读）。
- 数据库只存 `storage_key` / `url` / `metadata`，符合 §25「不要把媒体存进 PostgreSQL」。
- `assets.url` 与 `characters/locations.reference_image_url` 都是**签名 + 过期**的 URL
  （§27），HMAC 覆盖 `<key>:<expires>`，密钥为 `SECRET_KEY`。
- Phase 1 的公开 `/static` 挂载**已移除**：它以 URL 本身作为唯一凭证，任何人拿到链接
  就能永久读取他人产出，既不符合 §27 的签名要求，也不符合 §27 的越权要求。改为
  `GET /files/{key}`，未签名或无签名一律 403。

### 19.4 Prompt Builder（PRD §19）

§19 把最终提示词定义为六层的**组合**：System Style + Character Description +
Location Description + Current Shot + Camera + Emotion + Reference Image。

Phase 4 让分镜 LLM 自由写 `shots.image_prompt`，实测结果是**措辞不一致**：人物服装、
场景光照是否出现全凭模型发挥 —— 正是 §19 的「一致性机制」要防的漂移（见 §13.21 的
同类问题）。因此从 Phase 5 起，**最终提示词的作者是 Prompt Builder**：

- 输入取自 Bible 与 shot 行，同样的输入必然产出逐字节相同的输出；
- 措辞全部在 `prompts/image/*.md`（§20 的版本化要求），Python 只做占位符映射；
- `shots.image_prompt` 从「成品」降级为**输入**（`visual_description` 缺失时的回退）。
- 核心来源记录在 `assets.metadata.layers.core_source`，出图异常时可回溯源。

`_assemble()` 按行拼装，**空层连同整行丢弃** —— 否则会在提示词里留下「人物：」这种
半句话，反而干扰模型。

### 19.5 ImageProvider（PRD §16）

| Provider | 用途 |
| --- | --- |
| `mock`（默认） | 离线确定性 **真 PNG**（纯标准库编码器，不引入 Pillow），无需 key、无网络、零成本 |
| `openai` | 任意 OpenAI 兼容 `POST /images/generations` |

mock 产出的不是占位图：像素里嵌了一段 32 位条码，编码 `sha256(prompt)` 的前 4 字节，
因此「这张图确实由该提示词生成」是**可验证**的（`tests/test_image_pipeline.py` 反解
像素并与哈希比对）。

`MOCK_IMAGE_FAIL_TIMES` 让 mock 前 N 次调用抛出与真实 Provider 相同的 `ProviderError`，
这样 §21 的重试路径在离线状态下**可被测试**，而不是只有线上才会走。

**参考图的条件化限制（诚实记录）**：`openai` 适配器发的是纯文本生成请求。可移植的
`/images/generations` 契约无法表达图像条件（那是 `/images/edits` 或各家私有字段），
所以参考图在 **prompt 层**生效（把被引用对象的 Bible 描述合进提示词），并在
`metadata.reference_conditioning = "prompt-level"` 中如实标注。发一个部分端点会拒绝、
部分端点会静默忽略的字段，比说清楚更糟。

### 19.6 异步任务与重试（PRD §21）

§21 点名 **Redis Queue + Celery Worker**，故新增独立 `worker` 容器（与 backend 同镜像，
`CELERY_TASK_ALWAYS_EAGER=false`）。

**重试用循环而不是 `self.retry`**：Celery 的 retry 会重新投递消息，而 eager 模式根本
不会重投 —— 于是 `RUNNING → FAILED → RETRY` 这个**数据库可见**的状态机会随传输方式
改变。改为在 `execute_task()` 内循环，两种模式下行为逐字相同。

``CELERY_TASK_ALWAYS_EAGER=true`` 用于测试与单进程演示：`.delay()` 内联执行，因此测试
跑的是**真实的投递代码路径**（建任务行 → 投递 → 执行 → 写 Asset），只是没有 broker。

**幂等做了两道**：在途任务复用（部分唯一索引）+ 已 `SUCCESS` 的任务不再执行（消息
至少投递一次，重复投递不会二次付费、不会用差图覆盖好图）。

### 19.7 API（PRD §22）

§22 规定的媒体端点全部实现：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/shots/{id}/image/generate` | 受理出图；已有图片时 409 |
| POST | `/api/v1/shots/{id}/regenerate` | `?kind=image\|video\|audio`；video/audio 明确 501 而非静默出图 |
| GET | `/api/v1/tasks/{id}` | 任务详情；SUCCESS 时附带 `asset` |
| GET | `/api/v1/projects/{id}/tasks` | 任务列表 + 状态汇总 |
| POST | `/api/v1/tasks/{id}/retry` | 失败任务重试（重试成功任务 409） |

➕ 4 个超出 §22 的补充端点（§31 Phase 5 要求 Character/Location Reference，但 §22
未给路由；整集批量与逐集汇总同理）：

```text
POST /api/v1/characters/{id}/reference/generate
POST /api/v1/locations/{id}/reference/generate
POST /api/v1/episodes/{id}/images/generate      # 批量补齐缺失的镜头图片
GET  /api/v1/projects/{id}/assets               # 素材页数据源（§22 未给读取素材的路由）
```

**镜头级端点的 404 而非 403**：他人镜头一律返回 404（不泄漏「这条 id 存在」）。

返回码沿用既有约定：顶层聚合 POST 用 201，嵌套集合 POST 用 200。

### 19.8 前端

- `components/media-panel.tsx`：`ShotImagePanel`（单镜图片 + 生成/重生成/重试）、
  `EpisodeImageToolbar`（整集批量 + 汇总）、`ReferenceImageButton`（参考图）。
- **轮询会停**：只在任务可变化（PENDING/RUNNING/RETRY）时轮询，终态清除定时器。否则
  一个 50 镜的分镜板会常驻 50 个定时器。
- **不接受「点了按钮就等于出图」**：生成端点返回的是**任务**不是图片，图片在任务结算
  后由父组件重读分镜响应才出现；子组件报告完成，父组件负责刷新。
- `components/media-tabs.tsx`：**素材页**（素材网格 + 类型筛选，仅列出有内容的类型）与
  **生成任务页**（任务表 + 状态徽章 + 失败重试），对应 §5.3 左导航中的两页。
  §2.1 把「生成任务状态 + 失败重试」列为 MVP 必做，故任务页不是可选件；
  §22 没有读取素材的路由，素材页读上面那条补充端点。
  两页都是**只读为主**（任务页仅能重试），生成物是用户的作品，不放一键误删。
  任务页只在有任务可变化时轮询，终态即停。
- `DELIVERED_PHASE` 4 → 5：该常量驱动「尚未实现」占位，不同步改会出现
  **「声称做完 Phase 5、页面却写着未实现」**的自相矛盾。

### 19.9 实测记录

| 验收 | 结果 |
| --- | --- |
| `pytest`（全量，hermetic） | **497 passed** |
| Phase 5 专项测试 | 素材端点 3；图片流水线 41（提示词 / Provider / mock 字节 / 服务状态机 / 签名 / HTTP） |
| `ruff check` + `ruff format --check` | 全部通过（117 文件） |
| `tsc --noEmit` | 通过 |
| HTTP 端到端（**真 worker**，非 eager） | **44/44 PASS**（`HTTP_ACCEPT_EXIT=0`） |
| 真实读数 | 整集镜头全部出图；34 个任务 SUCCESS / **0 FAILED**；签名 URL 可下载、无签名 403；重生成保留旧图；跨用户 404 |
| 浏览器（真实 Chrome，Playwright） | **27/27 PASS**（`UI_EXIT=0`） |
| 浏览器覆盖 | 镜头卡片内联出图（489×489 真实解码）、整集批量 3/3 全部加载、重生成显示「2 次尝试」、人物参考图、**素材页 5 图块全部加载且带标签**、**生成任务页 5 任务全 SUCCESS**、控制台零错误 |

浏览器截图：`D:\HermesWorkplace\generated\images\ai-studio-phase5-ui\`（6 张，含素材页与任务页）。

**回归**（本轮改了 `extract_json`（Phase 3/4 节点共用）、分镜响应结构（新增 `media`）、
`DELIVERED_PHASE`，故必须复跑既有阶段的验收，不能只看 Phase 5 自己绿）：

| 回归项 | 命令 | 结果 |
| --- | --- | --- |
| 阶段 1–4 HTTP | `npm run verify` | **87 passed / 0 failed**（`VERIFY_EXIT=0`） |
| Phase 3 浏览器 | `npm run verify:ui` 第一段 | **19 / 0** |
| Phase 4 浏览器 | `npm run verify:ui` 第二段 | **18 / 0** |
| Phase 5 浏览器 | `npm run verify:ui` 第三段 | **27 / 27 PASS** |
| 汇总 | `npm run verify:ui` | `VERIFY_UI_EXIT=0` |

回归中查出并修掉的**陈旧测试工件**：`verify_ui_phase3.py` 原本断言「后续阶段 tab 仍是占位」，
并随阶段推进把断言对象从「剧集」挪到「素材」。Phase 5 交付后**已无占位页**，该断言必然失败 ——
它测的是「还没做完」，不是产品对错。已反转为不变量：**声称已交付的 tab 必须渲染自己的内容，
且页面上不得再出现「尚未实现」**。这类断言每交付一阶段就要复核一次，否则会从「绿灯」悄悄
变成「对着正确产品报错」。

端到端验收脚本：`D:\HermesWorkplace\cache\verify_phase5_http.py`（Python + 显式
UTF-8，见 §16）。

### 19.10 本阶段新增的工程坑

**① 会过期的值不能持久化（真 bug，取证后修复）**

`characters.reference_image_url` / `locations.reference_image_url` 是 PRD §17 的列，
而 §27 要求文件 URL 必须签名 + 过期。把签名 URL 直接写库，等于**把一个一小时后失效的
值当成持久事实**：图片一直在磁盘上，但 URL 一小时后变成永久死链。

实测取证：库中值为 `...?expires=<ts>&sig=...`，当时距过期仅剩 3490 秒 —— 一小时内
必然复现。

修法：新增 `resign_storage_url()`，**读取时按 storage_key 重新签名**；通过 schema 的
`field_validator` 挂在 `CharacterOut` / `LocationOut` 上，于是 list / create / update /
storyboard 所有序列化路径自动生效，不需要逐个调用点去改。

教训：**「签名 URL」是凭证不是数据。任何带 exp 的值都不能落库当事实，只能落库其持久
身份（storage_key）。**

**② 配置回退掩盖了改动（假绿风险）**

`STORAGE_PUBLIC_BASE_URL` 同时存在于 `.env`、`.env.example` 与 `docker-compose.yml`。
改了 `config.py` 的默认值后，URL 仍然是旧的 `/static` —— 因为**三处都覆盖了它**。
教训：改默认值前先 `grep` 同名键的所有来源，否则验的是配置不是代码。

**③ PRD 未到的阶段不能静默降级**

`/regenerate?kind=video` 若忽略参数直接出图，会产生「请求视频、拿到图片」的静默错误。
改为显式 501 + 说明 Phase 6 提供。**静默降级比拒绝更危险**，因为调用方会以为成功。

**④ prompt 加载器的章节边界（既有隐患，本轮暴露）**

`## User` 段的正则用 `re.DOTALL` 捕获到**文件末尾**，因此任何写在 `## User` 之后的章节
（如新的 `## Negative`）都会被吞进模板。此前所有 prompt 恰好把 `## User` 放在最后，
所以从未暴露。

修复加了 `(?=^##\s+|\Z)` 前瞻。做了 **A/B 验证**：7 个既有 prompt 的渲染结果与修复前
**逐字节相同**，只有新增文件受影响 —— 证明修复没有改变既有行为。

教训：**改共享解析器必须做 A/B 回归**，否则「顺手修的隐患」可能悄悄改写全部既有行为。

**⑤ 中间产物污染门禁**

在仓库根写的临时诊断脚本（`.p5*.py`）被 `ruff check` 计入，报出 53 个与代码无关的
错误。教训：诊断脚本一律写到仓库外（`D:\HermesWorkplace\cache\`），或收工前先删。

**⑥ worker 健康检查查错了东西（真缺陷）**

新增的 worker 容器沿用同一镜像，于是**继承了镜像里的 HTTP 健康检查**
（`curl http://localhost:8000/health`）。但 Celery worker 不提供 HTTP 服务，因此它
**全程 healthy 不了**：`docker compose ps` 永远显示 `unhealthy`，任何
`depends_on: condition: service_healthy` 的编排都会判它已死。

改动前实测：`FailingStreak: 36`，报错 `curl: (7) Failed to connect to localhost port 8000`。

修法：给 worker 单独的健康检查，问 worker 自己 ——
`celery -A app.workers.celery_app.celery_app inspect ping`，它同时证明进程活着**且**与
broker 连通（比 HTTP 探针语义更强）。

教训：**多容器共用镜像时，镜像里的 HEALTHCHECK 是共享的，必须逐个服务复核**。
「用同一个镜像」不等于「能沿用同一个探针」。

**⑦ 镜像分层顺序错误导致每次改代码都重装依赖（真浪费）**

`backend/Dockerfile` 原先把 `COPY app ./app` 放在 `pip install ".[dev]"` **之前**，
于是**任何源码改动都会作废 pip 层**，每次构建重装全部依赖（本机实测每次数分钟，
Phase 5 迭代中被反复支付）。

修法：依赖层只依赖 `pyproject.toml` —— 先用一小段 `tomllib` 把依赖清单导出成
requirements 再装，然后才 `COPY` 源码，最后 `pip install --no-deps -e .` 装项目本身。

教训：**Dockerfile 的 COPY 顺序就是缓存键**。把「很少变的」放上层、「经常变的」放下层。

**⑧ JSON 抽取的宽松启发式会静默返回错值（真 bug，线上触发后才暴露）**

分镜生成在浏览器验收的 bootstrap 阶段报出 422，后端日志给出了真因：

```text
GenerationFailedError: AI 输出在 3 次尝试后仍无法通过 Schema 校验：
无法从 LLM 输出中解析 JSON：Extra data: line 1 column 11910 (char 11909)
```

`Extra data` 意味着模型输出了**两个 JSON 对象拼接**（约 12KB 的对象后面又跟了一个）。
而 `extract_json` 当时用的是「第一个 `{` 到最后一个 `}`」的最宽跨度启发式 —— 这个跨度
**仍然包含两个值**，`json.loads` 必然拒绝。三次尝试全部走同一条死路，白烧 160 秒后
以 422 失败。

改用 `json.JSONDecoder().raw_decode()` 扫描**第一个能完整解析的值**，尾部内容无关紧要；
从光标处向前推进，还能跳过正文里出现的无关花括号。

写了新旧实现的对照探针（`D:\HermesWorkplace\cache\probe_extract_json_old_vs_new.py`），
结果值得单独记一笔：

| 输入形态 | 旧实现 | 新实现 |
| --- | --- | --- |
| 两个 JSON 拼接（线上真实形态） | ❌ `Extra data` | ✅ |
| 第一个完整、第二个应忽略 | ❌ `Extra data` | ✅ |
| 前缀被截断，完整值在后面 | ❌ `Expecting ',' delimiter` | ✅ |
| **正文含无关花括号** | ⚠️ **静默返回 `[]`（错值，不报错）** | ✅ 正确值 |
| 两个 fenced 代码块 | ✅ | ✅ |

**第 4 行比失败更危险**：旧启发式在这种输入下不抛异常，而是安静地返回一个**空数组**。
如果 schema 恰好接受空列表（分镜的 `shots` 就可以），就会把一份空分镜持久化下去 ——
用户看到「生成成功」，却什么都没有。**报错至少是可见的失败；静默错值是无声的数据损坏。**

教训：**「宽松地把内容抠出来」和「只接受一个完整值」是两回事。** 启发式越宽松，
越容易在解析失败时滑向「解析出了别的东西」，而那比抛异常难发现得多。
用 `raw_decode` 这类有明确语义的解析器，把「解析到哪里结束」交给库去判断。

**⑨ 验收指标选错会造出「假失败」——同一次检查先假失败、后真通过**

`整集图片全部真实加载` 这条检查出现过三次结果：单独跑 **3/3 通过**、全量回归
**2/3 失败**、修好后稳定 **3/3**。同一个产品、同一份数据，结论却随运行时机变化 —— 这类
「飘」的检查必须先当成**检查本身有问题**来查，而不是先当成产品 bug。

根因是**观测顺序**：面板在还有任务在跑时每 3 秒重取分镜，而每次重取的签名 URL 都是**新签的**
（这是 §27 的设计，URL 必须新鲜），于是每个 `<img>` 的 `src` 都变、浏览器重新开始加载。
我却要求「连续两次读到全部加载完成」—— **只要轮询没停，这个条件永远不可能满足**。
当时我误判为「渲染竞态」并加重了等待，反而离真相更远。

正确的观测序列是**先等轮询停下，再读像素**：给工具栏加 `data-running`（`running === 0`
正是「不再重取」的精确信号，与 `useEffect` 里 `if (running === 0) return` 同源），
等 `running=0` 且 `with_image >= 镜头数`，再要求连续两次全部解码完成。

旁证：素材页加载的是**同一批文件**，5/5 全部成功 —— 说明服务端一直在正常供图，
所以「2/3 未加载」只可能是浏览器侧的观测窗口问题，不可能是产品缺陷。

教训：**检查失败时，先问「我这个指标测的是产品状态，还是测的我读取它的时机」**。
若一个检查在不同时机给出不同结论，它就是不可信的检查 —— 修检查，而不是反复重跑等它变绿。
顺带：失败信息要带上足以定位的读数（现在会打印 `running=` 与 `with_image=`），
否则「2/3」这种输出只能靠猜。

**⑩ 裸跑 `ruff format .` 会改到只读的 PRD（规格污染）**

收尾复核时发现 `docs/PRD.md` 在工作区里有 1 行改动 —— 在 §468 的 Python 代码块里多了一个
空行（`class StoryState` 之前）。提交历史是干净的，**改动只存在于工作区**，来源是早前为图
省事跑的一次 `ruff format .`（**全仓库**）：ruff 会把 Markdown 里的 Python 代码块一并格式化，
于是把一个只读规格文档改了。

已 `git checkout -- docs/PRD.md` 回退，并复核 PRD 在历史与工作区都无差异。

根因不是 ruff，而是**绕过了限定目录的规范入口**：`npm run lint` 明确只作用于
`backend/app backend/tests backend/migrations scripts`，`docs/` 根本不在其中。
手敲 `ruff format .` 把它扩到了全仓库。

教训：**门禁命令的作用域本身是设计的一部分。** 图快把作用域放大，就会改到不该改的文件 ——
而在「PRD 只读」这种规则下，代价是规格被悄悄污染，比测试失败难发现得多。
一律走 `npm run lint`，不要裸跑 `ruff`。

**⑪ 容器到 PyPI 的路由可能比宿主更差**

构建卡在 `pip install` 长时间无进展，而宿主 `curl https://pypi.org/simple/fastapi/`
是 200 / 0.38s —— 说明瓶颈在**容器内的路由/DNS**，不在宿主网络。

修法：把索引做成 build arg（`PIP_INDEX_URL`，默认仍是官方 PyPI，行为不变），需要时在
`.env` 里指向镜像源即可，不必改 Dockerfile。**不把某地的镜像源硬编码进仓库**，
只留出可配置的口子。
