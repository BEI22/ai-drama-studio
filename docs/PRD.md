# AI Studio V1.0

## AI 漫剧 / 连续剧自动创作平台

### PRD + TDD + 开发执行规范

**文档版本：** V1.0\
**项目状态：** 准备实际开发\
**目标：** 使用 Codex 辅助完成可运行 MVP\
**产品形态：** Web SaaS\
**核心链路：** 故事 → 剧本 → 分镜 → 图片 → 视频 → 配音 → 字幕/BGM → 成片

------------------------------------------------------------------------

# 1. 项目总览

## 1.1 产品定义

AI Studio 是一个 AI 漫剧/连续剧自动创作平台。

用户输入小说、故事梗概或剧本后，系统自动完成：

1.  故事解析
2.  世界观整理
3.  人物提取
4.  场景提取
5.  剧集规划
6.  剧本生成
7.  分镜生成
8.  人物/场景/画风一致性控制
9.  图片生成
10. 图片转视频
11. AI 配音
12. 字幕生成
13. BGM/音效
14. FFmpeg 自动合成
15. 输出 MP4

核心原则：

> AI 自动生成 + 用户可以在关键节点查看、修改、重新生成。

第一版不追求完全无人值守，而追求完整、稳定、可演示的端到端 MVP。

------------------------------------------------------------------------

# 2. MVP 范围

## 2.1 P0 必须完成

-   用户注册/登录
-   项目创建
-   故事文本输入/上传
-   故事解析
-   Story Bible
-   Character Bible
-   Scene Bible
-   创建剧集
-   剧本生成
-   分镜生成
-   图片生成
-   图片转视频
-   TTS 配音
-   字幕生成
-   FFmpeg 合成
-   视频预览
-   生成任务状态
-   失败重试
-   项目/剧集/镜头数据持久化

## 2.2 P1

-   RAG 长期剧情记忆
-   人物参考图
-   场景参考图
-   画风参考
-   历史版本
-   单个镜头重新生成
-   Prompt 编辑
-   素材库
-   成本统计

## 2.3 P2

-   批量生成多集
-   多模型供应商选择
-   团队协作
-   会员/计费
-   API
-   自动发布到第三方平台
-   更复杂的视频编辑器

------------------------------------------------------------------------

# 3. 产品核心数据模型

产品对象层级：

``` text
User
 └── Project
      ├── Story Bible
      ├── Characters
      ├── Locations
      ├── Episodes
      │    ├── Script
      │    ├── Storyboard
      │    └── Shots
      │         ├── Image
      │         ├── Video
      │         └── Audio
      ├── Assets
      └── Generation Tasks
```

------------------------------------------------------------------------

# 4. 用户核心流程

``` text
创建项目
  ↓
输入故事
  ↓
AI 解析故事
  ↓
生成 Story Bible
  ↓
生成角色和场景
  ↓
用户确认/修改
  ↓
创建第 1 集
  ↓
AI 生成剧本
  ↓
AI 生成分镜
  ↓
用户确认
  ↓
生成分镜图片
  ↓
图片转视频
  ↓
生成角色配音
  ↓
生成字幕
  ↓
FFmpeg 合成
  ↓
预览成片
```

------------------------------------------------------------------------

# 5. 页面设计

## 5.1 首页

展示：

-   Logo / AI Studio
-   创建项目按钮
-   我的项目
-   项目封面
-   项目名称
-   已生成集数
-   最后更新时间

## 5.2 创建项目

字段：

-   项目名称
-   类型/题材
-   画风
-   故事来源
-   故事文本

故事来源：

-   故事梗概
-   小说文本
-   剧本

## 5.3 项目详情

建议左侧导航：

``` text
项目概览
故事设定
人物
场景
剧集
素材
生成任务
设置
```

## 5.4 剧集详情

``` text
第 1 集
├── 剧情
├── 剧本
├── 分镜
├── 素材
└── 成片
```

## 5.5 分镜页面

每个 Shot 卡片显示：

-   Shot ID
-   场景
-   人物
-   景别
-   动作
-   台词
-   Prompt
-   图片
-   视频
-   音频
-   生成状态
-   重新生成按钮

------------------------------------------------------------------------

# 6. Story Bible

Story Bible 是整个项目的长期世界观。

建议字段：

``` json
{
  "title": "",
  "genre": "",
  "logline": "",
  "background": "",
  "world_rules": [],
  "main_conflict": "",
  "timeline": [],
  "characters": [],
  "locations": [],
  "important_objects": [],
  "important_events": [],
  "style": ""
}
```

要求：

-   JSON 必须结构化
-   AI 输出不能直接作为数据库自由文本使用
-   后端必须进行 JSON Schema 校验
-   校验失败需要自动修复或重试

------------------------------------------------------------------------

# 7. Character Bible

每个角色：

``` json
{
  "id": "",
  "name": "",
  "role": "",
  "age": "",
  "gender": "",
  "personality": [],
  "appearance": "",
  "hair": "",
  "clothing": "",
  "voice_id": "",
  "reference_image_url": ""
}
```

角色一致性策略：

``` text
Shot
 +
Character Bible
 +
Character Reference Image
 +
Style Bible
 ↓
Image Prompt
```

------------------------------------------------------------------------

# 8. Scene Bible

``` json
{
  "id": "",
  "name": "",
  "description": "",
  "time": "",
  "lighting": "",
  "visual_style": "",
  "reference_image_url": ""
}
```

生成镜头时：

``` text
Shot
+
Scene Bible
+
Scene Reference
```

------------------------------------------------------------------------

# 9. 剧集设计

Episode：

``` json
{
  "id": "",
  "project_id": "",
  "episode_number": 1,
  "title": "",
  "summary": "",
  "duration": 180,
  "status": ""
}
```

剧集状态：

``` text
DRAFT
PLANNING
SCRIPTING
STORYBOARDING
GENERATING
COMPOSING
COMPLETED
FAILED
```

------------------------------------------------------------------------

# 10. 剧本 Schema

``` json
{
  "episode_id": "",
  "title": "",
  "summary": "",
  "scenes": [
    {
      "scene_id": "",
      "location_id": "",
      "time": "",
      "description": "",
      "characters": [],
      "dialogues": [
        {
          "character_id": "",
          "text": "",
          "emotion": ""
        }
      ]
    }
  ]
}
```

要求：

-   台词必须绑定 character_id
-   场景必须绑定 location_id
-   不允许 AI 随意创建数据库中不存在的人物 ID
-   新角色必须先进入 Character Bible

------------------------------------------------------------------------

# 11. 分镜 Schema

``` json
{
  "scene_id": "",
  "shots": [
    {
      "shot_id": "",
      "shot_number": 1,
      "duration": 5,
      "shot_size": "medium",
      "camera_movement": "slow_push",
      "characters": [],
      "action": "",
      "expression": "",
      "dialogue": "",
      "visual_description": "",
      "image_prompt": "",
      "video_prompt": ""
    }
  ]
}
```

------------------------------------------------------------------------

# 12. AI Workflow

核心 LangGraph：

``` text
START
 ↓
story_parser
 ↓
character_extractor
 ↓
location_extractor
 ↓
episode_planner
 ↓
script_generator
 ↓
storyboard_generator
 ↓
consistency_checker
 ↓
END
```

媒体生成单独执行：

``` text
Storyboard
 ↓
image_generation
 ↓
video_generation
 ↓
tts_generation
 ↓
subtitle_generation
 ↓
compose
```

原因：

剧本/分镜属于 LLM Workflow，而图片/视频/TTS
属于长耗时异步任务，不应该全部塞进一个同步 HTTP 请求。

------------------------------------------------------------------------

# 13. LangGraph State

Python：

``` python
from typing import TypedDict, List, Dict, Any

class StoryState(TypedDict, total=False):
    project_id: str
    episode_id: str

    story: Dict[str, Any]
    story_bible: Dict[str, Any]

    characters: List[Dict[str, Any]]
    locations: List[Dict[str, Any]]

    episode_plan: Dict[str, Any]
    script: Dict[str, Any]
    storyboard: Dict[str, Any]

    errors: List[Dict[str, Any]]
    current_step: str
```

注意：

-   State 只保存 Workflow 所需的数据
-   大型视频/图片不要直接塞进 State
-   文件只保存 URL/object storage key
-   大型文本可以保存数据库 ID，再按需读取

------------------------------------------------------------------------

# 14. 技术架构

推荐：

``` text
                Browser
                   |
                   v
              Next.js
                   |
                   v
              FastAPI
                   |
       +-----------+-----------+
       |           |           |
       v           v           v
 PostgreSQL      Redis       S3/OSS
       |           |
       |           v
       |        Celery
       |        Workers
       |           |
       |           v
       |      AI Providers
       |       /    |    \
       |     LLM  Image  Video
       |              \
       |               TTS
       |                |
       +------------ FFmpeg
```

------------------------------------------------------------------------

# 15. 技术栈

## Frontend

-   Next.js
-   TypeScript
-   React
-   Tailwind CSS

## Backend

-   Python
-   FastAPI
-   Pydantic
-   SQLAlchemy

## AI

-   LangGraph
-   LangChain
-   OpenAI-compatible LLM API
-   可插拔 Image Provider
-   可插拔 Video Provider
-   可插拔 TTS Provider

## Database

-   PostgreSQL
-   pgvector

## Queue

-   Redis
-   Celery

## Storage

-   S3-compatible Object Storage
-   国内部署可使用 OSS/COS

## Video

-   FFmpeg

## Deployment

V1：

``` text
Docker Compose
```

后续再考虑 Kubernetes。

------------------------------------------------------------------------

# 16. Provider 抽象层

禁止业务代码直接依赖具体模型供应商。

不要：

``` python
openai.xxx()
```

散落在业务代码里。

应该：

``` python
class LLMProvider:
    async def generate(self, request):
        raise NotImplementedError
```

图片：

``` python
class ImageProvider:
    async def generate(self, request):
        raise NotImplementedError
```

视频：

``` python
class VideoProvider:
    async def generate(self, request):
        raise NotImplementedError
```

TTS：

``` python
class TTSProvider:
    async def generate(self, request):
        raise NotImplementedError
```

然后：

``` text
providers/
├── llm/
├── image/
├── video/
└── tts/
```

以后可以增加不同厂商，而不修改业务层。

------------------------------------------------------------------------

# 17. 数据库设计

核心表：

``` text
users
projects
episodes
characters
locations
scripts
storyboards
shots
assets
generation_tasks
voices
story_memories
```

## users

``` text
id
email
password_hash
created_at
updated_at
```

## projects

``` text
id
user_id
name
genre
style
description
story_bible_json
status
created_at
updated_at
```

## episodes

``` text
id
project_id
episode_number
title
summary
duration
script_json
storyboard_json
status
created_at
updated_at
```

## characters

``` text
id
project_id
name
role
description
appearance
personality
clothing
voice_id
reference_image_url
created_at
updated_at
```

## locations

``` text
id
project_id
name
description
style
reference_image_url
created_at
updated_at
```

## shots

``` text
id
episode_id
scene_id
shot_number
duration
shot_size
camera_movement
characters_json
action
expression
dialogue
visual_description
image_prompt
video_prompt
image_asset_id
video_asset_id
audio_asset_id
status
created_at
updated_at
```

## assets

``` text
id
project_id
episode_id
shot_id
type
storage_key
url
metadata_json
created_at
```

type：

``` text
IMAGE
VIDEO
AUDIO
BGM
SFX
SUBTITLE
FINAL_VIDEO
```

## generation_tasks

``` text
id
project_id
episode_id
shot_id
task_type
provider
model
status
input_payload
output_payload
retry_count
error_message
started_at
completed_at
created_at
```

task_type：

``` text
STORY_ANALYSIS
SCRIPT
STORYBOARD
IMAGE
VIDEO
TTS
SUBTITLE
COMPOSE
```

------------------------------------------------------------------------

# 18. RAG / 长期记忆

V1 可以使用：

``` text
PostgreSQL + pgvector
```

不需要一开始使用 Milvus。

表：

``` text
story_memories

id
project_id
episode_id
memory_type
content
embedding
metadata_json
created_at
```

memory_type：

``` text
CHARACTER
EVENT
RELATIONSHIP
LOCATION
PLOT
WORLD_RULE
DIALOGUE
```

生成新剧集：

``` text
当前剧情
 ↓
Embedding
 ↓
pgvector similarity search
 ↓
Top K memories
 ↓
LLM
```

注意：

不要检索所有历史。

默认 Top K：

``` text
10~20
```

后续通过实际效果调整。

------------------------------------------------------------------------

# 19. 一致性机制

连续剧最重要的问题之一是视觉一致性。

V1 采用多层约束：

``` text
Story Bible
+
Character Bible
+
Scene Bible
+
Style Bible
+
Reference Image
+
Previous Shot Context
```

形成最终 Prompt。

示意：

``` text
System Style
+
Character Description
+
Location Description
+
Current Shot
+
Camera
+
Emotion
+
Reference Image
```

------------------------------------------------------------------------

# 20. Prompt 架构

Prompt 不允许散落在 Python 业务代码里。

目录：

``` text
prompts/
├── story/
├── script/
├── storyboard/
├── image/
├── video/
└── tts/
```

每个 Prompt 应版本化。

例如：

``` text
image_prompt_v1
image_prompt_v2
```

数据库记录：

``` text
prompt_version
```

方便后续 A/B 测试。

------------------------------------------------------------------------

# 21. 异步任务架构

所有耗时任务：

-   Image
-   Video
-   TTS
-   Compose

都必须异步。

流程：

``` text
POST /generate
 ↓
创建 generation_task
 ↓
Redis Queue
 ↓
Celery Worker
 ↓
Provider
 ↓
保存 Asset
 ↓
更新 Task
```

状态：

``` text
PENDING
 ↓
RUNNING
 ↓
SUCCESS
```

失败：

``` text
RUNNING
 ↓
FAILED
 ↓
RETRY
```

默认最大重试：

``` text
3
```

必须保证幂等。

------------------------------------------------------------------------

# 22. API 设计

## Project

``` http
POST /api/projects
GET /api/projects
GET /api/projects/{project_id}
PATCH /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

## Story

``` http
POST /api/projects/{project_id}/story
POST /api/projects/{project_id}/analyze
GET /api/projects/{project_id}/bible
```

## Characters

``` http
GET /api/projects/{project_id}/characters
POST /api/projects/{project_id}/characters
PATCH /api/characters/{character_id}
POST /api/characters/{character_id}/reference/generate
```

## Locations

``` http
GET /api/projects/{project_id}/locations
POST /api/projects/{project_id}/locations
PATCH /api/locations/{location_id}
POST /api/locations/{location_id}/reference/generate
```

## Episodes

``` http
POST /api/projects/{project_id}/episodes
GET /api/projects/{project_id}/episodes
GET /api/episodes/{episode_id}
PATCH /api/episodes/{episode_id}
```

## Script

``` http
POST /api/episodes/{episode_id}/script/generate
GET /api/episodes/{episode_id}/script
PATCH /api/episodes/{episode_id}/script
```

## Storyboard

``` http
POST /api/episodes/{episode_id}/storyboard/generate
GET /api/episodes/{episode_id}/storyboard
PATCH /api/episodes/{episode_id}/storyboard
```

## Shot

``` http
POST /api/shots/{shot_id}/image/generate
POST /api/shots/{shot_id}/video/generate
POST /api/shots/{shot_id}/audio/generate
POST /api/shots/{shot_id}/regenerate
```

## Compose

``` http
POST /api/episodes/{episode_id}/compose
GET /api/episodes/{episode_id}/video
```

## Tasks

``` http
GET /api/tasks/{task_id}
GET /api/projects/{project_id}/tasks
POST /api/tasks/{task_id}/retry
```

------------------------------------------------------------------------

# 23. API 返回规范

统一：

``` json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "xxx"
}
```

错误：

``` json
{
  "success": false,
  "data": null,
  "error": {
    "code": "GENERATION_FAILED",
    "message": "Video generation failed"
  },
  "request_id": "xxx"
}
```

------------------------------------------------------------------------

# 24. FFmpeg 合成

输入：

``` text
shot_001.mp4
shot_002.mp4
shot_003.mp4

voice_001.wav
voice_002.wav

bgm.mp3

subtitle.srt
```

输出：

``` text
episode_001.mp4
```

建议流程：

``` text
Video normalization
 ↓
Concatenate
 ↓
Voice mixing
 ↓
BGM mixing
 ↓
Subtitle
 ↓
Export
```

不要让用户上传任意 FFmpeg command。

后端自己生成安全的 FFmpeg 参数。

------------------------------------------------------------------------

# 25. 文件存储

数据库只保存：

``` text
storage_key
url
metadata
```

实际文件放：

``` text
/project/{project_id}/
    characters/
    locations/
    shots/
    videos/
    audio/
    subtitles/
    episodes/
```

禁止：

``` text
把大视频直接存 PostgreSQL
```

------------------------------------------------------------------------

# 26. 成本统计

每次 AI 调用记录：

``` text
provider
model
input_tokens
output_tokens
image_count
video_duration
estimated_cost
```

项目可以统计：

``` text
Project Cost
Episode Cost
Shot Cost
```

以后支持：

``` text
用户额度
积分
计费
```

------------------------------------------------------------------------

# 27. 安全

V1 至少做到：

-   JWT / Session 登录
-   用户只能访问自己的 project
-   所有 API 校验 user_id
-   文件 URL 使用签名 URL
-   API Key 存环境变量
-   不允许前端暴露 Provider Secret
-   Agent 不允许任意 shell
-   Agent 不允许任意文件系统访问
-   Agent 不允许未经授权的外部网络操作

------------------------------------------------------------------------

# 28. 日志

每个请求生成：

``` text
request_id
```

AI Task 生成：

``` text
task_id
```

日志至少包含：

``` text
request_id
task_id
project_id
episode_id
provider
model
status
latency
error
```

禁止在普通日志中输出：

-   API Key
-   密码
-   用户敏感数据

------------------------------------------------------------------------

# 29. 项目目录结构

推荐：

``` text
ai-studio/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── hooks/
│   ├── types/
│   └── public/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── providers/
│   │   ├── agents/
│   │   ├── tasks/
│   │   ├── workers/
│   │   └── utils/
│   │
│   ├── migrations/
│   ├── tests/
│   └── main.py
│
├── prompts/
│   ├── story/
│   ├── script/
│   ├── storyboard/
│   ├── image/
│   ├── video/
│   └── tts/
│
├── docker/
├── docker-compose.yml
├── .env.example
├── README.md
└── docs/
    ├── PRD.md
    └── TDD.md
```

------------------------------------------------------------------------

# 30. 开发原则

## 原则一：先跑通，再优化

第一阶段不要追求：

-   完美 UI
-   完美 Agent
-   完美一致性
-   极致性能

先完成：

``` text
Story
 ↓
Script
 ↓
Storyboard
 ↓
Image
 ↓
Video
 ↓
TTS
 ↓
FFmpeg
```

------------------------------------------------------------------------

## 原则二：所有 AI 输出结构化

LLM 尽量输出 JSON。

后端使用 Pydantic 校验。

例如：

``` python
class Dialogue(BaseModel):
    character_id: str
    text: str
    emotion: str
```

------------------------------------------------------------------------

## 原则三：Provider 解耦

业务代码不能绑定单一 AI 厂商。

------------------------------------------------------------------------

## 原则四：长任务异步化

视频生成绝对不能阻塞 HTTP 请求。

------------------------------------------------------------------------

## 原则五：每一步可恢复

例如：

``` text
第1集

剧本 ✓
分镜 ✓
图片 ✓
视频 8/12
```

服务重启后不能全部重新生成。

------------------------------------------------------------------------

# 31. 开发顺序

严格按照以下顺序开发。

## Phase 1：工程基础

1.  创建 Git Repository
2.  初始化 Next.js
3.  初始化 FastAPI
4.  Docker Compose
5.  PostgreSQL
6.  Redis
7.  环境变量
8.  数据库 Migration
9.  基础日志
10. Health Check

Health：

``` http
GET /health
```

返回：

``` json
{
  "status": "ok"
}
```

------------------------------------------------------------------------

## Phase 2：项目系统

实现：

-   登录
-   项目创建
-   项目列表
-   项目详情
-   Story 输入
-   Project CRUD

------------------------------------------------------------------------

## Phase 3：Story Agent

实现：

``` text
Story Parser
Character Extractor
Location Extractor
Story Bible
```

必须：

-   Pydantic Schema
-   JSON 校验
-   Retry
-   数据库持久化

------------------------------------------------------------------------

## Phase 4：Episode Agent

实现：

``` text
Episode Planner
Script Generator
Storyboard Generator
Consistency Checker
```

------------------------------------------------------------------------

## Phase 5：图片

实现：

``` text
ImageProvider
Character Reference
Location Reference
Prompt Builder
Image Task
```

------------------------------------------------------------------------

## Phase 6：视频

实现：

``` text
VideoProvider
Video Task
Retry
Polling
Asset Storage
```

------------------------------------------------------------------------

## Phase 7：TTS

实现：

``` text
Voice Provider
Character Voice
Dialogue Audio
```

------------------------------------------------------------------------

## Phase 8：Compose

实现：

``` text
Subtitle
BGM
FFmpeg
Final Video
```

------------------------------------------------------------------------

# 32. MVP 验收标准

输入一个简单故事，例如：

> 一个年轻人意外重生回大学时代，决定改变自己的人生。

系统至少应该能够：

1.  创建项目
2.  解析故事
3.  自动创建主要人物
4.  自动创建场景
5.  创建第1集
6.  生成第1集剧本
7.  生成至少 5 个 Shot
8.  每个 Shot 生成图片
9.  至少生成部分视频素材
10. 生成角色配音
11. 生成字幕
12. FFmpeg 合成 MP4
13. 页面可以播放 MP4
14. 单个失败 Shot 可以重新生成
15. 服务重启后已有成功任务不会丢失

------------------------------------------------------------------------

# 33. 第一版不要做的事情

为了防止项目失控，V1 明确禁止扩大范围：

-   不训练自己的 LLM
-   不训练自己的视频模型
-   不做移动 App
-   不做完整 Premiere/剪映级编辑器
-   不做复杂社交系统
-   不做推荐算法
-   不做自动发布矩阵
-   不做 Kubernetes
-   不做复杂微服务
-   不做几十种 AI Provider
-   不做无限集自动生成

------------------------------------------------------------------------

# 34. Codex 开发执行规则

Codex 不应该一次性生成整个项目。

必须按 Phase 开发。

每完成一个 Phase：

1.  运行测试
2.  修复错误
3.  更新 README
4.  更新数据库 Migration
5.  检查 API
6.  检查前端页面
7.  Git commit

推荐：

``` text
feat: initialize backend
feat: add project management
feat: add story analysis
feat: add character bible
feat: add episode generation
feat: add storyboard generation
feat: add image provider
feat: add video provider
feat: add tts
feat: add ffmpeg composer
```

------------------------------------------------------------------------

# 35. Codex 第一阶段任务

现在不要直接实现全部 AI 功能。

第一条开发任务：

``` text
建立 AI Studio V1.0 的基础工程。

要求：

1. 创建 frontend/ 和 backend/
2. frontend 使用 Next.js + TypeScript + Tailwind
3. backend 使用 Python + FastAPI
4. 使用 PostgreSQL
5. 使用 Redis
6. 使用 Docker Compose
7. 配置 .env.example
8. 配置数据库连接
9. 配置 SQLAlchemy
10. 配置 Alembic
11. 实现 /health
12. 创建基础 users/projects/episodes 表
13. 创建统一 API Response
14. 创建基础异常处理
15. 创建 request_id
16. 创建 README
17. 创建基础测试
18. 不要接入真实 AI Provider
19. 不要一次生成后续所有功能
20. 保证项目可以本地启动

完成后先运行测试并报告：
- 修改了哪些文件
- 如何启动
- 测试结果
- 当前已完成能力
- 下一步建议
```

------------------------------------------------------------------------

# 36. Codex 第二阶段任务

基础工程通过后：

``` text
实现 Project Management。

要求：

1. Project CRUD
2. 用户与 Project 的关联
3. Story 输入
4. Story 保存
5. Project 列表页面
6. Project 详情页面
7. 创建 Project 页面
8. API 完整实现
9. Pydantic Schema
10. Repository / Service 分层
11. API 权限校验
12. 单元测试
13. 前端基础错误处理
14. Loading 状态
15. Empty 状态

不要实现 AI Story Parser。
先把纯 CRUD 完成并测试。
```

------------------------------------------------------------------------

# 37. Codex 第三阶段任务

``` text
实现 Story Analysis Agent。

要求：

1. LangGraph
2. Story Parser Node
3. Character Extractor Node
4. Location Extractor Node
5. Story Bible
6. Pydantic JSON Schema
7. LLM Provider 抽象层
8. Mock LLM Provider
9. 真实 Provider 通过环境变量配置
10. AI 输出必须经过 Schema 校验
11. 失败自动 Retry
12. 保存分析结果
13. 提供 API
14. 前端展示 Story Bible
15. 前端展示 Characters
16. 前端展示 Locations
17. 用户可以修改人物和场景
18. 编写测试

不要实现图片、视频、TTS。
```

------------------------------------------------------------------------

# 38. Codex 后续任务

按顺序：

``` text
Episode Planner
 ↓
Script Generator
 ↓
Storyboard Generator
 ↓
Consistency Checker
 ↓
Image Provider
 ↓
Image Generation Task
 ↓
Video Provider
 ↓
Video Generation Task
 ↓
TTS Provider
 ↓
Subtitle
 ↓
FFmpeg Composer
 ↓
Final Video
```

每一步独立完成和测试。

------------------------------------------------------------------------

# 39. 关键技术决策总结

  问题            方案
  --------------- ----------------------
  前端            Next.js + TypeScript
  后端            FastAPI
  ORM             SQLAlchemy
  DB              PostgreSQL
  Vector          pgvector
  Cache           Redis
  Queue           Celery
  Agent           LangGraph
  LLM             Provider 抽象
  Image           Provider 抽象
  Video           Provider 抽象
  TTS             Provider 抽象
  Storage         S3/OSS
  Video Compose   FFmpeg
  Deployment      Docker Compose
  API             REST
  长任务          Celery
  状态            DB + Task
  一致性          Bible + Reference
  长期记忆        RAG + pgvector

------------------------------------------------------------------------

# 40. 最终产品目标

V1 最终不是一个"AI 聊天机器人"。

而是一个完整的：

> **AI 连续剧生产 Pipeline。**

最终：

``` text
用户
 ↓
故事
 ↓
AI Studio
 ↓
Story Bible
 ↓
Character Bible
 ↓
Episode
 ↓
Script
 ↓
Storyboard
 ↓
Image
 ↓
Video
 ↓
Voice
 ↓
Subtitle
 ↓
FFmpeg
 ↓
MP4
```

后续再在这个基础上扩展：

``` text
V2
 ↓
多集自动生成

V3
 ↓
批量生产

V4
 ↓
团队协作 + 商业化

V5
 ↓
AI 短剧生产平台
```

------------------------------------------------------------------------

# 41. 给 Codex 的最高优先级要求

**不要为了"看起来功能很多"而一次生成大量代码。**

必须遵循：

``` text
先架构
 ↓
再数据库
 ↓
再 API
 ↓
再前端
 ↓
再 Agent
 ↓
再 AI Provider
 ↓
再异步任务
 ↓
再媒体生成
```

每一步都必须：

``` text
实现
 ↓
运行
 ↓
测试
 ↓
修复
 ↓
提交
```

最终要求：

> **任何一个功能都必须能够独立运行和验证，不允许留下大量无法运行的伪代码。**

------------------------------------------------------------------------

# 42. 项目成功标准

项目第一阶段成功的定义不是：

> "写了很多代码。"

而是：

> **用户可以从一个故事开始，最终在浏览器里看到一集真正生成出来的 AI
> 漫剧/连续剧视频。**

这是整个 AI Studio V1.0 的最终验收目标。
