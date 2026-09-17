"use client";

/**
 * Phase 3 UI: Story Agent, Story Bible, character and scene bibles
 * (PRD sections 5.3, 6, 7, 8, 9).
 *
 * Three exports:
 *   - {@link AnalyzePanel}   run the agent, show progress/errors, re-analyze
 *   - {@link StoryBibleView} render the structured Bible
 *   - {@link CharactersTab} / {@link LocationsTab}  review and edit the cast
 */

import { useCallback, useEffect, useState } from "react";

import { LoadingState, FormError, EmptyState } from "@/components/states";
import { ReferenceImageButton } from "@/components/media-panel";
import { api, ApiError, type Character, type StoryBibleResponse, type StoryLocation } from "@/lib/api";
import {
  ANALYSIS_BADGE_CLASS,
  ANALYSIS_LABELS,
  EXTENSION_LABELS,
  NODE_LABELS,
  ROLE_BADGE_CLASS,
  ROLE_LABELS,
  ROLE_ORDER,
  type AnalysisStatus,
  type CharacterRole,
} from "@/types/api";

// --------------------------------------------------------------------------- util
function badgeUpdating(value: string | null | undefined): string {
  return value && value.trim() ? value : "—";
}

/** Prefer a human label for a model-invented key, else prettify the raw key. */
function extensionLabel(key: string): string {
  return EXTENSION_LABELS[key] ?? key.replace(/_/g, " ");
}

function renderExtensionValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join("；");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function AnalysisBadge({ status }: { status: AnalysisStatus }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset ${
        ANALYSIS_BADGE_CLASS[status] ?? ANALYSIS_BADGE_CLASS.NOT_ANALYZED
      }`}
    >
      {ANALYSIS_LABELS[status] ?? status}
    </span>
  );
}

// ------------------------------------------------------------------- analyze
export function AnalyzePanel({
  projectId,
  projectName: _projectName,
  analysisStatus,
  analysisError,
  hasStory,
  characterCount,
  locationCount,
  onDone,
  onOpenTab,
}: {
  projectId: string;
  projectName: string;
  analysisStatus: AnalysisStatus;
  analysisError: string | null;
  hasStory: boolean;
  characterCount: number;
  locationCount: number;
  onDone: (result: StoryBibleResponse) => void;
  onOpenTab?: (tab: "characters" | "locations") => void;
}) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const alreadyAnalyzed = analysisStatus === "SUCCEEDED";

  const run = useCallback(
    async (replace: boolean) => {
      setRunning(true);
      setError(null);
      try {
        const result = await api.analyzeProject(projectId, { replace });
        onDone(result);
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError("解析失败", { code: "UNKNOWN", status: 0, requestId: null }),
        );
      } finally {
        setRunning(false);
      }
    },
    [projectId, onDone],
  );

  return (
    <div className="panel space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">Story Agent 解析</h2>
            <AnalysisBadge status={analysisStatus} />
          </div>
          <p className="max-w-xl text-xs leading-relaxed text-slate-400">
            运行 LangGraph 工作流：故事解析 → 人物提取 → 场景提取。输出经过 JSON Schema
            校验，校验失败会自动修复重试。
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          {alreadyAnalyzed ? (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => run(true)}
              disabled={running}
            >
              {running ? "重新解析中…" : "重新解析"}
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={() => run(false)}
              disabled={running || !hasStory}
              title={hasStory ? undefined : "请先在「故事设定」里填写故事文本"}
            >
              {running ? "解析中…" : "开始解析"}
            </button>
          )}
          {alreadyAnalyzed ? (
            <p className="text-[10px] text-slate-500">
              重新解析会按名字合并，不会重复创建人物
            </p>
          ) : null}
        </div>
      </div>

      {!hasStory && !alreadyAnalyzed ? (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
          还没有故事文本。请先切换到「故事设定」保存故事内容，再回来解析。
        </p>
      ) : null}

      {running ? (
        <div className="space-y-2 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3">
          <p className="text-xs text-sky-200">
            正在调用模型，真实 LLM 通常需要 20–90 秒，请勿关闭页面…
          </p>
          <div className="skeleton h-1.5 w-full" />
        </div>
      ) : null}

      <FormError error={error} />

      {analysisError && !error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-3" role="alert">
          <p className="text-[11px] text-rose-300">上次解析失败</p>
          <p className="mt-1 break-all font-mono text-[11px] text-rose-200/80">
            {analysisError}
          </p>
        </div>
      ) : null}

      {alreadyAnalyzed ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-ink-700 pt-3 text-xs text-slate-400">
          <span>
            已提取 <span className="text-slate-200">{characterCount}</span> 个人物、
            <span className="text-slate-200"> {locationCount}</span> 个场景
          </span>
          {onOpenTab ? (
            <>
              <button
                type="button"
                className="text-brand-400 hover:text-brand-300"
                onClick={() => onOpenTab("characters")}
              >
                查看人物 →
              </button>
              <button
                type="button"
                className="text-brand-400 hover:text-brand-300"
                onClick={() => onOpenTab("locations")}
              >
                查看场景 →
              </button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- story bible
export function StoryBibleView({ bible }: { bible: StoryBibleResponse }) {
  const content = bible.story_bible;
  if (!content) return null;

  const meta = bible.meta;
  const extensions = Object.entries(content.extensions ?? {});

  return (
    <div className="space-y-4">
      {meta?.mock ? (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
          本次结果由 <span className="font-mono">mock</span> 离线启发式生成，不是真实大模型输出。
          设置 <span className="font-mono">LLM_PROVIDER=openai</span> 可接入真实模型。
        </p>
      ) : null}

      <div className="panel space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-white">Story Bible</h2>
          {meta ? (
            <span className="font-mono text-[10px] text-slate-500">
              {meta.provider} · {meta.model}
            </span>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <BibleField label="标题" value={content.title} />
          <BibleField label="题材" value={content.genre} />
          <BibleField label="画风 / 基调" value={content.style} />
          <BibleField label="一句话故事线" value={content.logline} wide />
          <BibleField label="背景设定" value={content.background} wide />
          <BibleField label="核心冲突" value={content.main_conflict} wide />
        </div>

        <BibleList label="世界观规则" items={content.world_rules} />
        <BibleList label="时间线" items={content.timeline} />
        <BibleList label="重要道具" items={content.important_objects} />
        <BibleList label="重要事件" items={content.important_events} />

        {extensions.length > 0 ? (
          <details className="rounded-lg border border-ink-700 bg-ink-900/40 p-3">
            <summary className="cursor-pointer text-xs font-medium text-slate-300">
              AI 补充设定（{extensions.length} 项）
            </summary>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {extensions.map(([key, value]) => (
                <div key={key} className="rounded border border-ink-800 bg-ink-950/40 p-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-500">
                    {extensionLabel(key)}
                  </p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-slate-300">
                    {renderExtensionValue(value)}
                  </p>
                </div>
              ))}
            </div>
          </details>
        ) : null}

        {meta && meta.usage.length > 0 ? (
          <details className="rounded-lg border border-ink-700 bg-ink-900/40 p-3">
            <summary className="cursor-pointer text-xs font-medium text-slate-300">
              运行详情（模型调用与 token）
            </summary>
            <table className="mt-3 w-full text-[11px]">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="pb-1 font-normal">节点</th>
                  <th className="pb-1 font-normal">Prompt 版本</th>
                  <th className="pb-1 text-right font-normal">输入</th>
                  <th className="pb-1 text-right font-normal">输出</th>
                </tr>
              </thead>
              <tbody className="font-mono text-slate-300">
                {meta.usage.map((record) => (
                  <tr key={record.node} className="border-t border-ink-800">
                    <td className="py-1">{NODE_LABELS[record.node] ?? record.node}</td>
                    <td className="py-1 text-slate-400">{record.prompt_version}</td>
                    <td className="py-1 text-right">{record.input_tokens}</td>
                    <td className="py-1 text-right">{record.output_tokens}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[10px] text-slate-500">
              失败自动重试上限 {meta.max_retries} 次 · 校验不通过的输出不会入库
            </p>
            {Object.keys(meta.pinned_from_user ?? {}).length > 0 ? (
              <p className="mt-1 text-[10px] text-slate-500">
                题材 / 画风 按你在项目里填写的值固定，未被模型改写：
                {Object.entries(meta.pinned_from_user ?? {})
                  .map(([field, value]) => `${EXTENSION_LABELS[field] ?? field}=${value}`)
                  .join(" · ")}
              </p>
            ) : null}
          </details>
        ) : null}
      </div>
    </div>
  );
}

function BibleField({
  label,
  value,
  wide,
}: {
  label: string;
  value: string | null;
  wide?: boolean;
}) {
  return (
    <div className={`rounded-lg border border-ink-800 bg-ink-950/40 p-3 ${wide ? "sm:col-span-2" : ""}`}>
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-xs leading-relaxed text-slate-200">{badgeUpdating(value)}</p>
    </div>
  );
}

function BibleList({ label, items }: { label: string; items: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-950/40 p-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <ul className="mt-1.5 space-y-1">
        {items.map((item, index) => (
          <li key={`${label}-${index}`} className="flex gap-2 text-xs leading-relaxed text-slate-200">
            <span className="mt-[3px] h-1 w-1 shrink-0 rounded-full bg-brand-500/60" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ characters
export function CharactersTab({
  projectId,
  analysisStatus,
  characters,
  onCharactersChanged,
  onReferenceChanged,
}: {
  projectId: string;
  analysisStatus: AnalysisStatus;
  characters: Character[];
  onCharactersChanged: (next: Character[]) => void;
  /** Re-reads the Bible: a fresh reference URL is minted per read (PRD §27). */
  onReferenceChanged?: () => void;
}) {
  const [error, setError] = useState<ApiError | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ appearance: string; role: CharacterRole }>({
    appearance: "",
    role: "SUPPORTING",
  });
  const [saving, setSaving] = useState(false);

  const sorted = [...characters].sort(
    (a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || a.sort_order - b.sort_order,
  );

  function startEdit(character: Character) {
    setEditingId(character.id);
    setDraft({ appearance: character.appearance ?? "", role: character.role });
    setError(null);
  }

  async function save(id: string) {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateCharacter(id, {
        appearance: draft.appearance,
        role: draft.role,
      });
      onCharactersChanged(characters.map((item) => (item.id === id ? updated : item)));
      setEditingId(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("保存失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.deleteCharacter(id);
      onCharactersChanged(characters.filter((item) => item.id !== id));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("删除失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    }
  }

  if (characters.length === 0) {
    return (
      <EmptyState
        title={analysisStatus === "SUCCEEDED" ? "没有提取到人物" : "还没有人物设定"}
        description={
          analysisStatus === "SUCCEEDED"
            ? "这次解析没有识别出角色。可以在「故事设定」里补充更完整的故事文本后重新解析。"
            : "先在「故事设定」保存故事文本并运行 Story Agent 解析，人物会自动出现在这里。"
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <FormError error={error} />
      <p className="text-xs text-slate-500">
        共 {characters.length} 个人物。外貌描述会直接用于后续的文生图（Phase 5），可以手动调整。
      </p>

      <div className="grid gap-3 md:grid-cols-2">
        {sorted.map((character) => {
          const editing = editingId === character.id;
          return (
            <div key={character.id} className="panel space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">{character.name}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] ring-1 ring-inset ${
                        ROLE_BADGE_CLASS[character.role] ?? ROLE_BADGE_CLASS.OTHER
                      }`}
                    >
                      {ROLE_LABELS[character.role] ?? character.role}
                    </span>
                    {character.gender ? (
                      <span className="text-[10px] text-slate-500">{character.gender}</span>
                    ) : null}
                    {character.age ? (
                      <span className="text-[10px] text-slate-500">{character.age}</span>
                    ) : null}
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  {editing ? (
                    <>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px]"
                        onClick={() => save(character.id)}
                        disabled={saving}
                      >
                        {saving ? "保存中" : "保存"}
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px]"
                        onClick={() => setEditingId(null)}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px]"
                        onClick={() => startEdit(character)}
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px] text-rose-300"
                        onClick={() => remove(character.id)}
                      >
                        删除
                      </button>
                    </>
                  )}
                </div>
              </div>

              {character.description ? (
                <p className="text-[11px] leading-relaxed text-slate-400">
                  {character.description}
                </p>
              ) : null}

              <Field label="外貌" value={character.appearance} />
              <Field label="发型" value={character.hair} />
              <Field label="服装" value={character.clothing} />

              {character.personality.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {character.personality.map((trait) => (
                    <span
                      key={trait}
                      className="rounded bg-ink-850 px-1.5 py-0.5 text-[10px] text-slate-400"
                    >
                      {trait}
                    </span>
                  ))}
                </div>
              ) : null}

              {/* Phase 5: a reusable visual anchor for this character, feeding
                  PRD §19's Reference Image layer. Hidden while editing so the
                  edit controls stay the focus. */}
              {editing ? null : (
                <ReferenceImageButton
                  kind="character"
                  id={character.id}
                  currentUrl={character.reference_image_url ?? null}
                  onChanged={() => onReferenceChanged?.()}
                />
              )}

              {editing ? (
                <div className="space-y-2 border-t border-ink-700 pt-3">
                  <label className="block text-[10px] uppercase tracking-wide text-slate-500">
                    角色定位
                    <select
                      className="input mt-1"
                      value={draft.role}
                      onChange={(event) =>
                        setDraft({ ...draft, role: event.target.value as CharacterRole })
                      }
                    >
                      {ROLE_ORDER.map((role) => (
                        <option key={role} value={role}>
                          {ROLE_LABELS[role]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-[10px] uppercase tracking-wide text-slate-500">
                    外貌描述
                    <textarea
                      className="input mt-1 min-h-20"
                      value={draft.appearance}
                      onChange={(event) => setDraft({ ...draft, appearance: event.target.value })}
                    />
                  </label>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-slate-300">{value}</p>
    </div>
  );
}

// ------------------------------------------------------------------- locations
export function LocationsTab({
  analysisStatus,
  locations,
  onLocationsChanged,
  onReferenceChanged,
}: {
  analysisStatus: AnalysisStatus;
  locations: StoryLocation[];
  onLocationsChanged: (next: StoryLocation[]) => void;
  /** Re-reads the Bible: a fresh reference URL is minted per read (PRD §27). */
  onReferenceChanged?: () => void;
}) {
  const [error, setError] = useState<ApiError | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ description: "", time: "", lighting: "" });
  const [saving, setSaving] = useState(false);

  function startEdit(location: StoryLocation) {
    setEditingId(location.id);
    setDraft({
      description: location.description ?? "",
      time: location.time ?? "",
      lighting: location.lighting ?? "",
    });
    setError(null);
  }

  async function save(id: string) {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateLocation(id, {
        description: draft.description,
        time: draft.time,
        lighting: draft.lighting,
      });
      onLocationsChanged(locations.map((item) => (item.id === id ? updated : item)));
      setEditingId(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("保存失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.deleteLocation(id);
      onLocationsChanged(locations.filter((item) => item.id !== id));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("删除失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    }
  }

  if (locations.length === 0) {
    return (
      <EmptyState
        title={analysisStatus === "SUCCEEDED" ? "没有提取到场景" : "还没有场景设定"}
        description={
          analysisStatus === "SUCCEEDED"
            ? "这次解析没有识别出可复用的场景。补充故事里的环境描写后重新解析即可。"
            : "先在「故事设定」保存故事文本并运行 Story Agent 解析，场景会自动出现在这里。"
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <FormError error={error} />
      <p className="text-xs text-slate-500">
        共 {locations.length} 个场景。时间与光线会进入后续的绘图提示词，可以手动调整。
      </p>

      <div className="grid gap-3 md:grid-cols-2">
        {locations.map((location) => {
          const editing = editingId === location.id;
          return (
            <div key={location.id} className="panel space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <p className="truncate text-sm font-medium text-white">{location.name}</p>
                <div className="flex shrink-0 gap-1">
                  {editing ? (
                    <>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px]"
                        onClick={() => save(location.id)}
                        disabled={saving}
                      >
                        {saving ? "保存中" : "保存"}
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px]"
                        onClick={() => setEditingId(null)}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px]"
                        onClick={() => startEdit(location)}
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-[11px] text-rose-300"
                        onClick={() => remove(location.id)}
                      >
                        删除
                      </button>
                    </>
                  )}
                </div>
              </div>

              {editing ? (
                <div className="space-y-2">
                  <label className="block text-[10px] uppercase tracking-wide text-slate-500">
                    场景描述
                    <textarea
                      className="input mt-1 min-h-20"
                      value={draft.description}
                      onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block text-[10px] uppercase tracking-wide text-slate-500">
                      时间
                      <input
                        className="input mt-1"
                        value={draft.time}
                        onChange={(event) => setDraft({ ...draft, time: event.target.value })}
                      />
                    </label>
                    <label className="block text-[10px] uppercase tracking-wide text-slate-500">
                      光线
                      <input
                        className="input mt-1"
                        value={draft.lighting}
                        onChange={(event) => setDraft({ ...draft, lighting: event.target.value })}
                      />
                    </label>
                  </div>
                </div>
              ) : (
                <>
                  <p className="text-[11px] leading-relaxed text-slate-400">
                    {badgeUpdating(location.description)}
                  </p>
                  <div className="flex flex-wrap gap-3 text-[10px] text-slate-500">
                    {location.time ? <span>时间：{location.time}</span> : null}
                    {location.lighting ? <span>光线：{location.lighting}</span> : null}
                  </div>
                  {/* Phase 5 location reference sheet. */}
                  <ReferenceImageButton
                    kind="location"
                    id={location.id}
                    currentUrl={location.reference_image_url ?? null}
                    onChanged={() => onReferenceChanged?.()}
                  />
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Loads the Bible for a project; used by the overview tab. */
export function useBible(projectId: string, enabled: boolean) {
  const [bible, setBible] = useState<StoryBibleResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const reload = useCallback(async () => {
    if (!projectId || !enabled) return;
    setLoading(true);
    setError(null);
    try {
      setBible(await api.getBible(projectId));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("加载 Story Bible 失败", {
              code: "UNKNOWN",
              status: 0,
              requestId: null,
            }),
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { bible, loading, error, reload, setBible };
}
