/**
 * Domain types for the Story Agent (Phase 3) and the Episode Agent (Phase 4)
 * — PRD sections 6-11, 17, 19, 26.
 *
 * Deliberately self-contained -- it does not import from ``lib/api`` so the two
 * modules can't form an import cycle. Project/user/session types live in
 * ``lib/api`` and are re-exported from there.
 */

export type AnalysisStatus = "NOT_ANALYZED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export type CharacterRole =
  | "PROTAGONIST"
  | "ANTAGONIST"
  | "SUPPORTING"
  | "MENTOR"
  | "LOVE_INTEREST"
  | "OTHER";

export interface Character {
  id: string;
  project_id: string;
  name: string;
  role: CharacterRole;
  age: string | null;
  gender: string | null;
  description: string | null;
  appearance: string | null;
  hair: string | null;
  clothing: string | null;
  personality: string[];
  voice_id: string | null;
  reference_image_url: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface StoryLocation {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  time: string | null;
  lighting: string | null;
  visual_style: string | null;
  reference_image_url: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/**
 * PRD section 6: the structured Story Bible.
 *
 * ``extensions`` holds fields a capable model volunteers beyond the PRD list
 * (主题、人物弧光、视觉风格…). The backend preserves them rather than discarding
 * them, so the UI surfaces them as "AI 补充设定".
 */
export interface StoryBibleContent {
  title: string;
  genre: string | null;
  logline: string | null;
  background: string | null;
  main_conflict: string | null;
  style: string | null;
  world_rules: string[];
  timeline: string[];
  important_objects: string[];
  important_events: string[];
  extensions: Record<string, unknown>;
}

/** PRD section 26 groundwork: what a run cost and which prompt versions it used. */
export interface UsageRecord {
  node: string;
  provider: string;
  model: string;
  prompt_version: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
}

export interface BibleMeta {
  provider: string;
  model: string;
  /** True when the deterministic offline provider produced this, not a real model. */
  mock: boolean;
  prompt_versions: Record<string, string>;
  usage: UsageRecord[];
  max_retries: number;
  /**
   * Fields the user typed in themselves and which were therefore forced onto the
   * model's output (genre/style). Everything else in the Bible is the model's.
   * Optional: Bibles analysed before this was recorded won't have it.
   */
  pinned_from_user?: Record<string, string>;
}

export interface StoryBibleResponse {
  project_id: string;
  analysis_status: AnalysisStatus;
  analysis_error: string | null;
  analyzed_at: string | null;
  story_bible: StoryBibleContent | null;
  characters: Character[];
  locations: StoryLocation[];
  meta: BibleMeta | null;
}

export interface AnalyzeStatus {
  analysis_status: AnalysisStatus;
  analysis_error: string | null;
  analyzed_at: string | null;
  characters: number;
  locations: number;
  provider: string;
  model: string;
  mock: boolean;
}

export interface CharacterWriteInput {
  name?: string;
  role?: CharacterRole;
  age?: string | null;
  gender?: string | null;
  description?: string | null;
  appearance?: string | null;
  hair?: string | null;
  clothing?: string | null;
  personality?: string[];
  voice_id?: string | null;
}

export interface LocationWriteInput {
  name?: string;
  description?: string | null;
  time?: string | null;
  lighting?: string | null;
  visual_style?: string | null;
}

export interface DeletedResult {
  id: string;
  deleted: boolean;
}

// ----------------------------------------------------------------- label maps
export const ROLE_LABELS: Record<CharacterRole, string> = {
  PROTAGONIST: "主角",
  ANTAGONIST: "反派",
  SUPPORTING: "配角",
  MENTOR: "导师",
  LOVE_INTEREST: "恋人",
  OTHER: "其他",
};

/** Protagonist first, matching how a writer reads a cast list. */
export const ROLE_ORDER: CharacterRole[] = [
  "PROTAGONIST",
  "ANTAGONIST",
  "LOVE_INTEREST",
  "MENTOR",
  "SUPPORTING",
  "OTHER",
];

export const ANALYSIS_LABELS: Record<AnalysisStatus, string> = {
  NOT_ANALYZED: "未解析",
  RUNNING: "解析中",
  SUCCEEDED: "已解析",
  FAILED: "解析失败",
};

/** Stable badge colours, keyed by role then by analysis status. */
export const ROLE_BADGE_CLASS: Record<CharacterRole, string> = {
  PROTAGONIST: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  ANTAGONIST: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  LOVE_INTEREST: "bg-pink-500/15 text-pink-300 ring-pink-500/30",
  MENTOR: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  SUPPORTING: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  OTHER: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
};

export const ANALYSIS_BADGE_CLASS: Record<AnalysisStatus, string> = {
  NOT_ANALYZED: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
  RUNNING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  SUCCEEDED: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  FAILED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

/** Node id -> Chinese label, for the usage/cost table. */
export const NODE_LABELS: Record<string, string> = {
  // Phase 3 -- Story Agent (PRD section 12)
  story_parser: "故事解析",
  character_extractor: "人物提取",
  location_extractor: "场景提取",
  // Phase 4 -- Episode Agent (PRD section 12)
  episode_planner: "分集规划",
  script_generator: "剧本生成",
  storyboard_generator: "分镜生成",
  consistency_checker: "一致性检查",
};

/** Human labels for the model-invented extension keys we see in practice. */
export const EXTENSION_LABELS: Record<string, string> = {
  theme: "主题",
  tone: "基调",
  subgenre: "细分题材",
  visual_style: "视觉风格",
  art_style: "美术风格",
  target_audience: "目标受众",
  protagonist: "主角",
  protagonist_profile: "主角设定",
  protagonist_goal: "主角目标",
  protagonist_flaw: "主角缺陷",
  protagonist_arc: "人物弧光",
  antagonist: "反派",
  antagonist_profile: "反派设定",
  supporting_characters: "配角",
  relationships: "人物关系",
  setting: "背景设定",
  time_period: "时代",
  narrative_style: "叙事风格",
  core_conflict: "核心冲突",
  story_engine: "故事引擎",
  episode_potential: "分集潜力",
  visual_motifs: "视觉母题",
  music_tone: "音乐基调",
  alternative_titles: "备选标题",
  synopsis: "故事梗概",
  notes: "补充说明",
};

// =========================================================================== #
// Phase 4 -- Episode Agent: episodes, script, storyboard, shots
// (PRD sections 9, 10, 11, 19, 38)
// =========================================================================== #

/**
 * Per-step run state for a generated artefact.
 *
 * ``FAILED`` is not the same as "never generated": the previous successful
 * artefact is kept, so a failed regeneration can be retried without losing work.
 */
export type GenerationStatus = "NOT_GENERATED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export type EpisodeStatus =
  | "DRAFT"
  | "PLANNING"
  | "SCRIPTING"
  | "STORYBOARDING"
  | "GENERATING"
  | "COMPOSING"
  | "COMPLETED"
  | "FAILED";

/** PRD section 11 shot-size vocabulary. Closed set -- the backend rejects others. */
export type ShotSize =
  | "extreme_wide"
  | "wide"
  | "medium"
  | "medium_close_up"
  | "close_up"
  | "extreme_close_up";

/** PRD section 11 camera-movement vocabulary. Closed set. */
export type CameraMovement =
  | "static"
  | "slow_push"
  | "push_in"
  | "pull_out"
  | "pan_left"
  | "pan_right"
  | "tilt_up"
  | "tilt_down"
  | "tracking"
  | "crane"
  | "handheld";

export type ShotStatus = "DRAFT" | "READY" | "GENERATING" | "COMPLETED" | "FAILED";

/** Episode as returned by the API (``EpisodeOut``). */
export interface Episode {
  id: string;
  project_id: string;
  episode_number: number;
  title: string | null;
  summary: string | null;
  duration: number;
  status: EpisodeStatus;

  script_status: GenerationStatus;
  storyboard_status: GenerationStatus;
  generation_error: string | null;
  script_generated_at: string | null;
  storyboard_generated_at: string | null;

  /** Derived flags so the list renders without fetching every script. */
  has_script: boolean;
  has_storyboard: boolean;
  shot_count: number;

  created_at: string;
  updated_at: string;
}

/** Provenance of the plan, stored alongside the episodes (PRD section 26). */
export interface EpisodePlanMeta {
  provider?: string;
  model?: string;
  mock?: boolean;
  prompt_versions?: Record<string, string>;
  usage?: UsageRecord[];
  [key: string]: unknown;
}

export interface EpisodeListResponse {
  items: Episode[];
  totals: { episodes: number; characters: number; locations: number };
  plan_meta: EpisodePlanMeta | null;
  analysis_status: AnalysisStatus;
}

// -------------------------------------------------------------------- script
export interface Dialogue {
  /** A real Character Bible uuid -- never a name (PRD section 10). */
  character_id: string;
  text: string;
  emotion: string | null;
}

export interface ScriptScene {
  /** ``S1``, ``S2`` … normalised by the backend to be unique and ordered. */
  scene_id: string;
  /** A real Scene Bible uuid. */
  location_id: string;
  time: string | null;
  description: string | null;
  /** Character ids present in this scene. */
  characters: string[];
  dialogues: Dialogue[];
}

export interface ScriptContent {
  title: string | null;
  summary: string | null;
  scenes: ScriptScene[];
}

export interface ScriptResponse {
  episode_id: string;
  script_status: GenerationStatus;
  has_script: boolean;
  script: ScriptContent | null;
  meta: BibleMeta | null;
  /** id -> name, so the UI can render speakers without a second request. */
  characters: Record<string, string>;
}

// ---------------------------------------------------------------- storyboard
/**
 * A shot as persisted (``ShotOut``).
 *
 * Note on the two ``characters`` fields that exist in this domain: a **shot**
 * carries display **names** (that is what the model writes and what the
 * consistency checker verifies against the Bible), while a **script dialogue**
 * carries a character **id**. Resolve names through the project's character list.
 */
export interface Shot {
  id: string;
  episode_id: string;
  scene_id: string;
  /** Restarts at 1 inside every scene (PRD section 11). */
  shot_number: number;
  /** Absolute order across the whole episode -- stable for rendering and Phase 5. */
  sequence: number;
  duration: number;
  shot_size: ShotSize;
  camera_movement: CameraMovement;
  characters: string[];
  action: string | null;
  expression: string | null;
  dialogue: string | null;
  visual_description: string | null;
  image_prompt: string | null;
  video_prompt: string | null;
  status: ShotStatus;
  created_at: string;
  updated_at: string;
}

/** PRD section 11's per-scene object, as returned in the storyboard document. */
export interface SceneStoryboard {
  scene_id: string;
  shots: ShotDraft[];
}

/** A shot inside the storyboard document (pre-persistence shape). */
export interface ShotDraft {
  shot_number: number;
  duration: number;
  shot_size: ShotSize;
  camera_movement: CameraMovement;
  characters: string[];
  action: string | null;
  expression: string | null;
  dialogue: string | null;
  visual_description: string | null;
  image_prompt: string | null;
  video_prompt: string | null;
}

export interface StoryboardContent {
  scenes: SceneStoryboard[];
}

// -------------------------------------------------------------- consistency
export type IssueSeverity = "ERROR" | "WARNING" | "INFO";

/** PRD section 19: one way the generated content disagrees with the Bibles. */
export interface ConsistencyIssue {
  code: string;
  severity: IssueSeverity;
  message: string;
  scene_id: string | null;
  shot_number: number | null;
  field: string | null;
}

export interface ConsistencyReport {
  issues: ConsistencyIssue[];
  checked_shots: number;
  checked_scenes: number;
}

/** The ``GET /consistency`` shape adds derived counts and a verdict. */
export interface ConsistencyResponse extends ConsistencyReport {
  episode_id: string;
  errors: number;
  warnings: number;
  ok: boolean;
}

export interface StoryboardResponse {
  episode_id: string;
  storyboard_status: GenerationStatus;
  has_storyboard: boolean;
  storyboard: StoryboardContent | null;
  shots: Shot[];
  consistency: ConsistencyReport | null;
  meta: BibleMeta | null;
  characters: Record<string, string>;
  /** Phase 5: per-shot media state, keyed by shot id. */
  media: Record<string, ShotImageState>;
}

// ----------------------------------------------------------------- media (Phase 5)
export type AssetType = "IMAGE" | "VIDEO" | "AUDIO" | "BGM" | "SFX" | "SUBTITLE" | "FINAL_VIDEO";

export type TaskType =
  | "STORY_ANALYSIS"
  | "SCRIPT"
  | "STORYBOARD"
  | "IMAGE"
  | "VIDEO"
  | "TTS"
  | "SUBTITLE"
  | "COMPOSE";

/** PRD §21: PENDING -> RUNNING -> SUCCESS, or RUNNING -> RETRY -> ... -> FAILED. */
export type TaskStatus = "PENDING" | "RUNNING" | "SUCCESS" | "FAILED" | "RETRY";

export interface Asset {
  id: string;
  project_id: string;
  episode_id: string | null;
  shot_id: string | null;
  type: AssetType;
  /** Signed and expiring (PRD §27); re-fetched on each storyboard read. */
  url: string | null;
  storage_key: string;
  duration: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface GenerationTask {
  id: string;
  project_id: string;
  episode_id: string | null;
  shot_id: string | null;
  task_type: TaskType;
  status: TaskStatus;
  provider: string | null;
  model: string | null;
  retry_count: number;
  max_retries: number;
  error_message: string | null;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown>;
  estimated_cost: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  /** Present on GET /tasks/{id} once the task succeeded. */
  asset?: Asset | null;
}

/** One shot's picture state, as returned inside a storyboard response. */
export interface ShotImageState {
  shot_id: string;
  shot_number: number;
  scene_id: string;
  status: ShotStatus;
  image_asset_id: string | null;
  asset: Asset | null;
  image_count: number;
  latest_task: GenerationTask | null;
}

export interface TaskAccepted {
  task: GenerationTask;
  /** True when an identical task was already in flight (PRD §21 idempotency). */
  reused: boolean;
}

export interface TaskListResponse {
  items: GenerationTask[];
  totals: { tasks: number; by_status: Record<TaskStatus, number> };
}

/** An asset plus the shot labels the 素材 grid needs to caption its tiles. */
export interface AssetListItem extends Asset {
  shot_number: number | null;
  scene_id: string | null;
}

export interface AssetListResponse {
  items: AssetListItem[];
  totals: { assets: number; by_type: Record<AssetType, number> };
}

export interface BatchImageResponse {
  episode_id: string;
  queued: number;
  skipped_existing: number;
  shots_total: number;
  tasks: GenerationTask[];
  provider: string;
  model: string;
}

// ------------------------------------------------------------------- inputs
export interface EpisodeCreateInput {
  title: string;
  episode_number?: number;
  summary?: string | null;
  duration?: number;
}

export interface EpisodeUpdateInput {
  episode_number?: number;
  title?: string;
  summary?: string | null;
  duration?: number;
  status?: EpisodeStatus;
}

export interface ScriptUpdateInput {
  title?: string | null;
  summary?: string | null;
  scenes?: ScriptScene[];
}

/** Only supplied fields change. Enums are validated strictly, unlike model output. */
export interface ShotUpdateInput {
  duration?: number;
  shot_size?: ShotSize;
  camera_movement?: CameraMovement;
  characters?: string[];
  action?: string | null;
  expression?: string | null;
  dialogue?: string | null;
  visual_description?: string | null;
  image_prompt?: string | null;
  video_prompt?: string | null;
  status?: ShotStatus;
}

// ----------------------------------------------------------------- label maps
export const GENERATION_LABELS: Record<GenerationStatus, string> = {
  NOT_GENERATED: "未生成",
  RUNNING: "生成中",
  SUCCEEDED: "已生成",
  FAILED: "生成失败",
};

export const GENERATION_BADGE_CLASS: Record<GenerationStatus, string> = {
  NOT_GENERATED: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
  RUNNING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  SUCCEEDED: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  FAILED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

/** PRD §21's task states. RETRY is shown as in-flight: the task is still alive. */
export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  PENDING: "排队中",
  RUNNING: "生成中",
  SUCCESS: "已完成",
  FAILED: "失败",
  RETRY: "重试中",
};

export const TASK_STATUS_BADGE_CLASS: Record<TaskStatus, string> = {
  PENDING: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
  RUNNING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  SUCCESS: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  FAILED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  RETRY: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
};

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  IMAGE: "图片",
  VIDEO: "视频",
  AUDIO: "配音",
  BGM: "背景音乐",
  SFX: "音效",
  SUBTITLE: "字幕",
  FINAL_VIDEO: "成片",
};

export const ASSET_TYPE_ORDER: AssetType[] = [
  "IMAGE",
  "VIDEO",
  "AUDIO",
  "BGM",
  "SFX",
  "SUBTITLE",
  "FINAL_VIDEO",
];

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  STORY_ANALYSIS: "故事解析",
  SCRIPT: "剧本生成",
  STORYBOARD: "分镜生成",
  IMAGE: "图片生成",
  VIDEO: "视频生成",
  TTS: "配音生成",
  SUBTITLE: "字幕生成",
  COMPOSE: "合成",
};

/** True while a task can still change state -- the UI polls only these. */
export function isTaskLive(status: TaskStatus): boolean {
  return status === "PENDING" || status === "RUNNING" || status === "RETRY";
}

export const EPISODE_STATUS_LABELS: Record<EpisodeStatus, string> = {
  DRAFT: "草稿",
  PLANNING: "规划中",
  SCRIPTING: "写剧本",
  STORYBOARDING: "画分镜",
  GENERATING: "生成中",
  COMPOSING: "合成中",
  COMPLETED: "已完成",
  FAILED: "失败",
};

export const SHOT_SIZE_LABELS: Record<ShotSize, string> = {
  extreme_wide: "大远景",
  wide: "远景",
  medium: "中景",
  medium_close_up: "中近景",
  close_up: "特写",
  extreme_close_up: "大特写",
};

export const CAMERA_MOVEMENT_LABELS: Record<CameraMovement, string> = {
  static: "固定",
  slow_push: "缓推",
  push_in: "推镜",
  pull_out: "拉镜",
  pan_left: "左摇",
  pan_right: "右摇",
  tilt_up: "上摇",
  tilt_down: "下摇",
  tracking: "跟拍",
  crane: "升降",
  handheld: "手持",
};

export const SEVERITY_LABELS: Record<IssueSeverity, string> = {
  ERROR: "错误",
  WARNING: "警告",
  INFO: "提示",
};

export const SEVERITY_BADGE_CLASS: Record<IssueSeverity, string> = {
  ERROR: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  WARNING: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  INFO: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
};

/** Consistency issue code -> Chinese explanation. */
export const ISSUE_LABELS: Record<string, string> = {
  UNKNOWN_CHARACTER: "镜头里出现了人物设定中不存在的角色",
  SCENE_NOT_IN_SCRIPT: "该镜头所属场景不在剧本中",
  SCENE_WITHOUT_SHOTS: "该场景没有任何镜头",
  SCENE_WITHOUT_DIALOGUE: "该场景有角色出场但没有台词",
  SPEAKER_NOT_IN_SCENE: "有台词的角色未列入本场出场角色",
  IMAGE_PROMPT_MISSING: "缺少文生图提示词",
  VIDEO_PROMPT_MISSING: "缺少图生视频提示词",
  VISUAL_DESCRIPTION_MISSING: "缺少画面描述",
  APPEARANCE_NOT_IN_PROMPT: "提示词里没有体现出人物的外貌设定",
  SCENE_CONTEXT_MISSING: "提示词没有描述任何环境或光线（会画出没有背景的画面）",
  STYLE_NOT_IN_PROMPT: "提示词里没有带上项目画风",
  SHOT_TOO_LONG: "单个镜头过长",
  SHOT_DURATION_INVALID: "镜头时长非法",
  EPISODE_DURATION_MISMATCH: "分镜总时长与本集目标时长偏差过大",
  DIALOGUE_NOT_IN_SCRIPT: "镜头台词与剧本不一致",
};

export const SHOT_SIZES: ShotSize[] = [
  "extreme_wide",
  "wide",
  "medium",
  "medium_close_up",
  "close_up",
  "extreme_close_up",
];

export const CAMERA_MOVEMENTS: CameraMovement[] = [
  "static",
  "slow_push",
  "push_in",
  "pull_out",
  "pan_left",
  "pan_right",
  "tilt_up",
  "tilt_down",
  "tracking",
  "crane",
  "handheld",
];
