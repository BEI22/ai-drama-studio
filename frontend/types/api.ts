/**
 * Phase 3 domain types: Story Agent, Story Bible, characters and locations
 * (PRD sections 6, 7, 8, 9, 17, 26).
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
  story_parser: "故事解析",
  character_extractor: "人物提取",
  location_extractor: "场景提取",
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
