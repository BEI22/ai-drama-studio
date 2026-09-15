"use client";

/**
 * Episode Agent UI (PRD sections 9, 10, 11, 19, 38) — the Phase 4 tab.
 *
 * Three artefacts, in the order the pipeline produces them:
 *
 *   分集列表 (episode_planner)  ->  剧本 (script_generator)  ->  分镜 (storyboard_generator)
 *                                                                        |
 *                                                            一致性检查 (consistency_checker)
 *
 * Two things shape this component:
 *
 * 1. **Generation is slow.** The real model needs ~6 s to plan episodes, ~25 s to
 *    write a script and ~60 s to produce a storyboard. Every generation button
 *    therefore shows elapsed seconds — without that, a 60 s wait is
 *    indistinguishable from a hung request, and users retry into duplicate work.
 *
 * 2. **Ids vs names.** A script dialogue carries a character *id*; a shot carries
 *    display *names*. Both are resolved through the Bible passed down from the
 *    parent page, so the UI never shows a raw uuid — and never invents a name.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState, ErrorState, FormError, LoadingState } from "@/components/states";
import { api, ApiError } from "@/lib/api";
import type {
  AnalysisStatus,
  Character,
  ConsistencyIssue,
  ConsistencyResponse,
  Episode,
  ScriptResponse,
  Shot,
  ShotUpdateInput,
  StoryLocation,
  StoryboardResponse,
} from "@/lib/api";
import {
  CAMERA_MOVEMENTS,
  CAMERA_MOVEMENT_LABELS,
  EPISODE_STATUS_LABELS,
  GENERATION_BADGE_CLASS,
  GENERATION_LABELS,
  ISSUE_LABELS,
  SEVERITY_BADGE_CLASS,
  SEVERITY_LABELS,
  SHOT_SIZES,
  SHOT_SIZE_LABELS,
  type CameraMovement,
  type GenerationStatus,
  type IssueSeverity,
  type ShotSize,
} from "@/types/api";

const BADGE = "badge ring-1";
const OPTIONS = [3, 6, 12];

/** Elapsed-seconds counter, so a slow generation never reads as a hang. */
function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) {
      setSeconds(0);
      return;
    }
    const started = Date.now();
    setSeconds(0);
    const timer = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return seconds;
}

function GenerationBadge({ status }: { status: GenerationStatus }) {
  return (
    <span className={`${BADGE} ${GENERATION_BADGE_CLASS[status]}`}>
      {GENERATION_LABELS[status]}
    </span>
  );
}

function asApiError(caught: unknown, fallback: string): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError(fallback, { code: "UNKNOWN", status: 0, requestId: null });
}

/** `mm:ss` for a duration in seconds. */
function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return mins > 0 ? `${mins}分${rest}秒` : `${rest}秒`;
}

// =========================================================================== #
// Main tab
// =========================================================================== #
export function EpisodesTab({
  projectId,
  analysisStatus,
  characters,
  locations,
  onEpisodesChanged,
}: {
  projectId: string;
  analysisStatus: AnalysisStatus;
  characters: Character[];
  locations: StoryLocation[];
  onEpisodesChanged?: () => void;
}) {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  /** False only until the first response lands. Later refetches must NOT blank
   *  the panel: swapping the grid for a skeleton unmounts the detail view and
   *  destroys its local state (a save confirmation, a half-typed edit). */
  const [hasLoaded, setHasLoaded] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [planMeta, setPlanMeta] = useState<Record<string, unknown> | null>(null);
  const [count, setCount] = useState(6);
  const elapsed = useElapsed(busy !== null);
  // Bumped on every write so the detail panel refetches. A plain `selectedId`
  // dependency would not re-run when the *same* episode is regenerated.
  const [revision, setRevision] = useState(0);

  const analyzed = analysisStatus === "SUCCEEDED";
  const analyzedRef = useRef(analyzed);
  analyzedRef.current = analyzed;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.listEpisodes(projectId);
      setEpisodes(page.items);
      setPlanMeta(page.plan_meta);
      setSelectedId((current) =>
        current && page.items.some((item) => item.id === current)
          ? current
          : (page.items[0]?.id ?? null),
      );
    } catch (caught) {
      setError(asApiError(caught, "加载剧集失败"));
    } finally {
      setLoading(false);
      setHasLoaded(true);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => episodes.find((item) => item.id === selectedId) ?? null,
    [episodes, selectedId],
  );

  /** Run a slow generation while keeping `busy` truthful. */
  const run = useCallback(
    async (label: string, action: () => Promise<unknown>) => {
      setBusy(label);
      setError(null);
      try {
        await action();
      } catch (caught) {
        setError(asApiError(caught, `${label}失败`));
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  async function handlePlan(replace: boolean) {
    await run(replace ? "重新规划分集" : "规划分集", async () => {
      await api.planEpisodes(projectId, { episodeCount: count, replace });
      await load();
      setRevision((n) => n + 1);
      onEpisodesChanged?.();
    });
  }

  async function handleClear() {
    await run("清空分集", async () => {
      await api.clearEpisodes(projectId);
      await load();
      onEpisodesChanged?.();
    });
  }

  async function handleGenerateScript(episodeId: string) {
    await run("生成剧本", async () => {
      await api.generateScript(episodeId);
      await load();
      setRevision((n) => n + 1);
    });
  }

  async function handleGenerateStoryboard(episodeId: string) {
    await run("生成分镜", async () => {
      await api.generateStoryboard(episodeId);
      await load();
      setRevision((n) => n + 1);
    });
  }

  if (!analyzed) {
    return (
      <EmptyState
        title="需要先完成故事解析"
        description="Episode Agent 要把故事拆成分集，并让人物 / 场景 id 绑定到真实数据。请先在「故事设定」里运行 Story Agent，解析出 Story Bible、人物与场景。"
      />
    );
  }

  return (
    <div className="space-y-4">
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}

      <div className="panel space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="label-caps">分集规划</h2>
            <p className="mt-1 text-xs text-slate-500">
              由 Episode Agent 依据 Story Bible 把整个故事拆成分集大纲。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="episode-count" className="text-xs text-slate-400">
              集数
            </label>
            <select
              id="episode-count"
              value={count}
              onChange={(event) => setCount(Number(event.target.value))}
              disabled={busy !== null}
              className="rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 text-xs text-slate-200
                focus:border-brand-500 focus:outline-none"
            >
              {OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value} 集
                </option>
              ))}
            </select>

            <button
              type="button"
              className="btn-primary"
              onClick={() => void handlePlan(episodes.length > 0)}
              disabled={busy !== null}
            >
              {busy === "规划分集" || busy === "重新规划分集"
                ? `${busy}中… ${elapsed}s`
                : episodes.length > 0
                  ? "重新规划"
                  : "规划分集"}
            </button>

            {episodes.length > 0 ? (
              <button
                type="button"
                className="btn-ghost"
                onClick={() => void handleClear()}
                disabled={busy !== null}
              >
                清空分集
              </button>
            ) : null}
          </div>
        </div>

        {episodes.length > 0 ? (
          <p className="text-[11px] text-slate-500">
            重新规划会删除现有剧本与分镜（PRD §38 的守卫要求显式覆盖，不会静默销毁产出）。
          </p>
        ) : null}

        {planMeta ? (
          <p className="font-mono text-[11px] text-slate-600">
            规划模型：{String(planMeta.model ?? "—")}
            {planMeta.mock ? " · 离线 mock" : ""}
            {loading ? " · 正在同步…" : ""}
          </p>
        ) : null}
      </div>

      {!hasLoaded ? (
        <LoadingState label="正在加载剧集…" />
      ) : episodes.length === 0 ? (
        <EmptyState
          title="还没有分集"
          description="选择集数后点击「规划分集」，Episode Agent 会输出分集大纲；随后可以逐集生成剧本与分镜。"
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
          <EpisodeListPanel
            projectId={projectId}
            episodes={episodes}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onCreated={() => {
              void load();
              onEpisodesChanged?.();
            }}
            onDeleted={() => {
              void load();
              onEpisodesChanged?.();
            }}
            busy={busy}
            elapsed={elapsed}
            run={run}
          />

          {selected ? (
            <EpisodeDetail
              // Keyed by id only. Bumping the key on every mutation remounted
              // the whole panel, which discarded local state -- so the "已保存"
              // confirmation was destroyed in the same tick it appeared (and any
              // half-typed edit went with it). `revision` is a prop instead.
              key={selected.id}
              episode={selected}
              characters={characters}
              locations={locations}
              busy={busy}
              elapsed={elapsed}
              revision={revision}
              onGenerateScript={() => void handleGenerateScript(selected.id)}
              onGenerateStoryboard={() => void handleGenerateStoryboard(selected.id)}
              onEpisodeListChanged={load}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}

// =========================================================================== #
// Episode list
// =========================================================================== #
function EpisodeListPanel({
  projectId,
  episodes,
  selectedId,
  onSelect,
  onCreated,
  onDeleted,
  busy,
  elapsed,
  run,
}: {
  projectId: string;
  episodes: Episode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreated: () => void;
  onDeleted: () => void;
  busy: string | null;
  elapsed: number;
  run: (label: string, action: () => Promise<unknown>) => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    await run("新增剧集", async () => {
      await api.createEpisode(projectId, { title: title.trim() });
      setTitle("");
      setAdding(false);
      onCreated();
    });
  }

  return (
    <aside className="space-y-3">
      <div className="panel p-2">
        <ol className="space-y-1">
          {episodes.map((episode) => {
            const active = episode.id === selectedId;
            return (
              <li key={episode.id}>
                <button
                  type="button"
                  onClick={() => onSelect(episode.id)}
                  aria-current={active ? "true" : undefined}
                  className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                    active ? "bg-brand-500/10 ring-1 ring-brand-500/30" : "hover:bg-ink-850"
                  }`}
                >
                  <span className="flex items-baseline gap-2">
                    <span
                      className={`font-mono text-[11px] ${
                        active ? "text-brand-400" : "text-slate-500"
                      }`}
                    >
                      EP{String(episode.episode_number).padStart(2, "0")}
                    </span>
                    <span
                      className={`min-w-0 flex-1 truncate text-sm ${
                        active ? "text-brand-400" : "text-slate-300"
                      }`}
                    >
                      {episode.title || "未命名"}
                    </span>
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-1">
                    <GenerationBadge status={episode.script_status} />
                    {episode.shot_count > 0 ? (
                      <span className={`${BADGE} border-ink-600 bg-ink-850 text-slate-400`}>
                        {episode.shot_count} 镜
                      </span>
                    ) : null}
                    {episode.duration > 0 ? (
                      <span className="font-mono text-[10px] text-slate-600">
                        {formatDuration(episode.duration)}
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>

      {adding ? (
        <form onSubmit={handleCreate} className="panel space-y-2 p-3">
          <label htmlFor="new-episode-title" className="block text-xs text-slate-300">
            剧集标题
          </label>
          <input
            id="new-episode-title"
            autoFocus
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 text-xs
              text-slate-200 focus:border-brand-500 focus:outline-none"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                setAdding(false);
                setTitle("");
              }}
            >
              取消
            </button>
            <button type="submit" className="btn-primary" disabled={!title.trim() || busy !== null}>
              {busy === "新增剧集" ? `新增中… ${elapsed}s` : "新增"}
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          className="btn-ghost w-full"
          onClick={() => setAdding(true)}
          disabled={busy !== null}
        >
          手动新增一集
        </button>
      )}

      {episodes.length > 0 ? (
        <button
          type="button"
          className="btn-ghost w-full"
          disabled={busy !== null}
          onClick={() =>
            void run("删除剧集", async () => {
              const last = episodes[episodes.length - 1];
              await api.deleteEpisode(last.id);
              onDeleted();
            })
          }
        >
          删除最后一集
        </button>
      ) : null}
    </aside>
  );
}

// =========================================================================== #
// Episode detail: script + storyboard + consistency
// =========================================================================== #
function EpisodeDetail({
  episode,
  characters,
  locations,
  busy,
  elapsed,
  revision,
  onGenerateScript,
  onGenerateStoryboard,
  onEpisodeListChanged,
}: {
  episode: Episode;
  characters: Character[];
  locations: StoryLocation[];
  busy: string | null;
  elapsed: number;
  /** Bumped by the parent after it triggers a generation, to force a refetch. */
  revision: number;
  onGenerateScript: () => void;
  onGenerateStoryboard: () => void;
  /** The episode list carries derived counts (shot_count), so it refetches too. */
  onEpisodeListChanged: () => void;
}) {
  const [script, setScript] = useState<ScriptResponse | null>(null);
  const [board, setBoard] = useState<StoryboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  /** Skeletons are for the first load only -- see the note in `EpisodesTab`. */
  const [hasLoaded, setHasLoaded] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [consistency, setConsistency] = useState<ConsistencyResponse | null>(null);
  const [panel, setPanel] = useState<"script" | "storyboard">("script");

  const characterNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const item of characters) map[item.id] = item.name;
    return map;
  }, [characters]);

  const locationNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const item of locations) map[item.id] = item.name;
    return map;
  }, [locations]);

  /**
   * scene_id -> display name, for the storyboard.
   *
   * A `Shot` row carries only a `scene_id` (a script label like "S3"), not a
   * location id -- so the scene's location has to be resolved through the
   * script. Without this the storyboard would have to show the raw uuid.
   */
  const sceneLocations = useMemo(() => {
    const map: Record<string, string> = {};
    for (const scene of script?.script?.scenes ?? []) {
      map[scene.scene_id] =
        locationNames[scene.location_id] ?? scene.location_id.slice(0, 8);
    }
    return map;
  }, [script, locationNames]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextScript, nextBoard] = await Promise.all([
        api.getScript(episode.id),
        api.getStoryboard(episode.id),
      ]);
      setScript(nextScript);
      setBoard(nextBoard);
    } catch (caught) {
      setError(asApiError(caught, "加载剧集内容失败"));
    } finally {
      setLoading(false);
      setHasLoaded(true);
    }
  }, [episode.id]);

  useEffect(() => {
    void load();
  }, [load, revision]);

  const generatingScript = busy === "生成剧本";
  const generatingBoard = busy === "生成分镜";

  useEffect(() => {
    // Follow the pipeline: once a script lands, the storyboard is the next step.
    if (board?.has_storyboard) setPanel("storyboard");
  }, [board?.has_storyboard]);

  if (!hasLoaded) return <LoadingState label="正在加载剧本与分镜…" />;

  return (
    <section className="min-w-0 space-y-4">
      <div className="panel space-y-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-medium text-white">
              EP{String(episode.episode_number).padStart(2, "0")}
              <span className="ml-2">{episode.title || "未命名"}</span>
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              {episode.summary || "暂无梗概"}
            </p>
            <p className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
              <span>{EPISODE_STATUS_LABELS[episode.status]}</span>
              <span>·</span>
              <span>目标 {formatDuration(episode.duration)}</span>
              <span>·</span>
              <span>{episode.shot_count} 个镜头</span>
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-ghost"
              onClick={onGenerateScript}
              disabled={busy !== null}
            >
              {generatingScript
                ? `生成剧本中… ${elapsed}s`
                : episode.has_script
                  ? "重新生成剧本"
                  : "生成剧本"}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={onGenerateStoryboard}
              disabled={busy !== null || !episode.has_script}
              title={episode.has_script ? undefined : "需要先生成剧本"}
            >
              {generatingBoard
                ? `生成分镜中… ${elapsed}s`
                : episode.has_storyboard
                  ? "重新生成分镜"
                  : "生成分镜"}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="text-slate-500">剧本</span>
            <GenerationBadge status={episode.script_status} />
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-slate-500">分镜</span>
            <GenerationBadge status={episode.storyboard_status} />
          </span>
        </div>

        {episode.generation_error ? (
          <p className="break-all rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 font-mono text-[11px] text-amber-200/90">
            {episode.generation_error}
          </p>
        ) : null}

        {busy ? (
          <p className="text-[11px] text-accent-400" role="status" aria-live="polite">
            {busy}进行中，已等待 {elapsed}s。真实模型逐句生成，剧本约 25s、分镜约 60s，请勿重复点击。
          </p>
        ) : loading ? (
          <p className="text-[11px] text-slate-500" role="status" aria-live="polite">
            正在同步…
          </p>
        ) : null}
      </div>

      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}

      <div className="flex gap-2">
        {(["script", "storyboard"] as const).map((key) => {
          const active = panel === key;
          const label = key === "script" ? "剧本" : "分镜";
          const count =
            key === "script"
              ? (script?.script?.scenes.length ?? 0)
              : (board?.shots.length ?? 0);
          return (
            <button
              key={key}
              type="button"
              onClick={() => setPanel(key)}
              aria-pressed={active}
              className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                active
                  ? "border-brand-500 bg-brand-500/10 text-brand-400"
                  : "border-ink-600 text-slate-400 hover:bg-ink-850"
              }`}
            >
              {label}
              {count > 0 ? (
                // aria-hidden: the count is decorative. Without this the button's
                // accessible name is "剧本8", which a screen reader announces
                // verbatim and which makes the tab impossible to target by name.
                <span aria-hidden="true" className="ml-1.5 font-mono text-[10px]">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {panel === "script" ? (
        <ScriptView
          response={script}
          characterNames={characterNames}
          locationNames={locationNames}
          onMutated={() => {
            void load();
            onEpisodeListChanged();
          }}
        />
      ) : (
        <StoryboardView
          response={board}
          sceneLocations={sceneLocations}
          consistency={consistency ?? board?.consistency ?? null}
          onRecheck={() =>
            void (async () => {
              try {
                setConsistency(await api.checkConsistency(episode.id));
              } catch (caught) {
                setError(asApiError(caught, "一致性检查失败"));
              }
            })()
          }
          onShotSaved={() => {
            void load();
            onEpisodeListChanged();
          }}
        />
      )}
    </section>
  );
}

// =========================================================================== #
// Script
// =========================================================================== #
function ScriptView({
  response,
  characterNames,
  locationNames,
  onMutated,
}: {
  response: ScriptResponse | null;
  characterNames: Record<string, string>;
  locationNames: Record<string, string>;
  onMutated: () => void;
}) {
  const serverSummary = response?.script?.summary ?? "";
  const [summary, setSummary] = useState(serverSummary);
  const adoptedRef = useRef(serverSummary);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    // Adopt a server-side change (a regenerated script). This panel no longer
    // remounts on mutation, so without this the textarea would keep showing the
    // previous episode's summary while the document underneath had changed.
    if (serverSummary !== adoptedRef.current) {
      adoptedRef.current = serverSummary;
      setSummary(serverSummary);
    }
  }, [serverSummary]);

  const script = response?.script ?? null;
  const dirty = script !== null && summary !== (script.summary ?? "");

  function name(characterId: string): string {
    // The response carries its own id -> name lookup; the Bible is the fallback
    // for a character that was removed after the script was written.
    return response?.characters?.[characterId] ?? characterNames[characterId] ?? characterId.slice(0, 8);
  }

  async function handleSave() {
    if (!response) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateScript(response.episode_id, { summary });
      onMutated();
    } catch (caught) {
      setError(asApiError(caught, "保存剧本失败"));
    } finally {
      setSaving(false);
    }
  }

  if (!script) {
    return (
      <EmptyState
        title="还没有剧本"
        description="点击「生成剧本」，Script Generator 会依据本集大纲、Story Bible 以及人物 / 场景名单写出剧本。每一句台词都会绑定到真实的人物 id。"
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="panel space-y-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="label-caps">本集梗概</h3>
          {error ? <span className="text-[11px] text-rose-300">{error.message}</span> : null}
        </div>
        <textarea
          rows={2}
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-xs
            leading-relaxed text-slate-200 focus:border-brand-500 focus:outline-none"
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-500">
            共 {script.scenes.length} 场戏 · {response?.meta?.model ?? "—"}
          </span>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void handleSave()}
            disabled={!dirty || saving}
          >
            {saving ? "保存中…" : "保存梗概"}
          </button>
        </div>
      </div>

      {script.scenes.map((scene) => (
        <article key={scene.scene_id} className="panel space-y-3 p-5">
          <header className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-brand-400">{scene.scene_id}</span>
            <span className="text-sm text-slate-200">
              {locationNames[scene.location_id] ?? scene.location_id.slice(0, 8)}
            </span>
            {scene.time ? (
              <span className="text-[11px] text-slate-500">· {scene.time}</span>
            ) : null}
          </header>

          {scene.characters.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {scene.characters.map((id) => (
                <span
                  key={id}
                  className={`${BADGE} border-ink-600 bg-ink-850 text-slate-300`}
                >
                  {name(id)}
                </span>
              ))}
            </div>
          ) : null}

          {scene.description ? (
            <p className="text-xs leading-relaxed text-slate-300">{scene.description}</p>
          ) : null}

          {scene.dialogues.length > 0 ? (
            <ul className="space-y-2 border-l-2 border-ink-700 pl-3">
              {scene.dialogues.map((line, index) => (
                <li key={`${line.character_id}-${index}`} className="text-xs">
                  <span className="text-brand-400">{name(line.character_id)}</span>
                  {line.emotion ? (
                    <span className="ml-1 font-mono text-[10px] text-slate-500">
                      （{line.emotion}）
                    </span>
                  ) : null}
                  <span className="ml-2 text-slate-200">{line.text}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-slate-600">本场无台词（纯动作场面）</p>
          )}
        </article>
      ))}
    </div>
  );
}

// =========================================================================== #
// Storyboard
// =========================================================================== #
function StoryboardView({
  response,
  sceneLocations,
  consistency,
  onRecheck,
  onShotSaved,
}: {
  response: StoryboardResponse | null;
  sceneLocations: Record<string, string>;
  consistency: { issues: ConsistencyIssue[]; checked_shots: number; checked_scenes: number } | null;
  onRecheck: () => void;
  onShotSaved: () => void;
}) {
  const shots = response?.shots ?? [];

  const groups = useMemo(() => {
    const byScene = new Map<string, Shot[]>();
    for (const shot of shots) {
      const list = byScene.get(shot.scene_id);
      if (list) list.push(shot);
      else byScene.set(shot.scene_id, [shot]);
    }
    return [...byScene.entries()];
  }, [shots]);

  const totalDuration = shots.reduce((sum, shot) => sum + shot.duration, 0);

  const issuesByPosition = useMemo(() => {
    const map = new Map<string, ConsistencyIssue[]>();
    for (const issue of consistency?.issues ?? []) {
      // A shot-less issue (scene level) is keyed on the scene alone.
      const key = `${issue.scene_id ?? ""}#${issue.shot_number ?? ""}`;
      const list = map.get(key);
      if (list) list.push(issue);
      else map.set(key, [issue]);
    }
    return map;
  }, [consistency]);

  if (shots.length === 0) {
    return (
      <EmptyState
        title="还没有分镜"
        description="点击「生成分镜」，Storyboard Generator 会把剧本拆成可直接用于绘图与图生视频的镜头，随后自动运行一致性检查。"
      />
    );
  }

  return (
    <div className="space-y-4">
      <ConsistencyPanel report={consistency} onRecheck={onRecheck} />

      <div className="panel flex flex-wrap items-center gap-x-6 gap-y-1 px-5 py-3 text-[11px] text-slate-400">
        <span>{groups.length} 个场景</span>
        <span>{shots.length} 个镜头</span>
        <span>总时长 {formatDuration(totalDuration)}</span>
        <span className="font-mono text-slate-600">{response?.meta?.model ?? "—"}</span>
      </div>

      {groups.map(([sceneId, sceneShots]) => {
        const sceneIssues = issuesByPosition.get(`${sceneId}#`) ?? [];
        return (
          <section key={sceneId} className="space-y-3">
            <h3 className="flex flex-wrap items-center gap-2 px-1">
              <span className="font-mono text-xs text-brand-400">{sceneId}</span>
              <span className="text-sm text-slate-300">{sceneLocations[sceneId] ?? "—"}</span>
              <span className="text-[11px] text-slate-600">{sceneShots.length} 镜</span>
            </h3>

            {sceneIssues.length > 0 ? (
              <ul className="space-y-1 px-1">
                {sceneIssues.map((issue, index) => (
                  <li key={`${issue.code}-${index}`} className="text-[11px] text-amber-300/90">
                    {ISSUE_LABELS[issue.code] ?? issue.code}：{issue.message}
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="space-y-3">
              {sceneShots.map((shot) => (
                <ShotCard
                  key={shot.id}
                  shot={shot}
                  issues={issuesByPosition.get(`${shot.scene_id}#${shot.shot_number}`) ?? []}
                  onSaved={onShotSaved}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/** One editable shot row (PRD section 11). */
function ShotCard({
  shot,
  issues,
  onSaved,
}: {
  shot: Shot;
  issues: ConsistencyIssue[];
  onSaved: () => void;
}) {
  const [duration, setDuration] = useState(shot.duration);
  const [shotSize, setShotSize] = useState<ShotSize>(shot.shot_size);
  const [movement, setMovement] = useState<CameraMovement>(shot.camera_movement);
  const [dialogue, setDialogue] = useState(shot.dialogue ?? "");
  const [imagePrompt, setImagePrompt] = useState(shot.image_prompt ?? "");
  const [videoPrompt, setVideoPrompt] = useState(shot.video_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  const dirty =
    duration !== shot.duration ||
    shotSize !== shot.shot_size ||
    movement !== shot.camera_movement ||
    dialogue !== (shot.dialogue ?? "") ||
    imagePrompt !== (shot.image_prompt ?? "") ||
    videoPrompt !== (shot.video_prompt ?? "");

  function reset() {
    setDuration(shot.duration);
    setShotSize(shot.shot_size);
    setMovement(shot.camera_movement);
    setDialogue(shot.dialogue ?? "");
    setImagePrompt(shot.image_prompt ?? "");
    setVideoPrompt(shot.video_prompt ?? "");
    setSaved(false);
    setError(null);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      // Only the changed fields are sent. This matters because the API uses
      // `exclude_unset` semantics: sending everything would rewrite fields the
      // user never touched (and could overwrite a concurrent edit).
      const patch: ShotUpdateInput = {};
      if (duration !== shot.duration) patch.duration = duration;
      if (shotSize !== shot.shot_size) patch.shot_size = shotSize;
      if (movement !== shot.camera_movement) patch.camera_movement = movement;
      if (dialogue !== (shot.dialogue ?? "")) patch.dialogue = dialogue;
      if (imagePrompt !== (shot.image_prompt ?? "")) patch.image_prompt = imagePrompt;
      if (videoPrompt !== (shot.video_prompt ?? "")) patch.video_prompt = videoPrompt;

      if (Object.keys(patch).length > 0) await api.updateShot(shot.id, patch);
      setSaved(true);
      onSaved();
    } catch (caught) {
      setError(asApiError(caught, "保存镜头失败"));
    } finally {
      setSaving(false);
    }
  }

  const errors = issues.filter((issue) => issue.severity === "ERROR");
  const others = issues.filter((issue) => issue.severity !== "ERROR");

  return (
    <article
      className={`panel space-y-3 p-4 ${
        errors.length > 0 ? "border-rose-500/40" : ""
      }`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-slate-500">
          #{shot.sequence} · {shot.scene_id}-{shot.shot_number}
        </span>
        <span className={`${BADGE} border-ink-600 bg-ink-850 text-slate-400`}>
          {SHOT_SIZE_LABELS[shot.shot_size]}
        </span>
        <span className={`${BADGE} border-ink-600 bg-ink-850 text-slate-400`}>
          {CAMERA_MOVEMENT_LABELS[shot.camera_movement]}
        </span>
        {shot.characters.map((name) => (
          <span key={name} className={`${BADGE} border-brand-500/30 bg-brand-500/10 text-brand-400`}>
            {name}
          </span>
        ))}
      </header>

      {shot.visual_description ? (
        <p className="text-xs leading-relaxed text-slate-300">{shot.visual_description}</p>
      ) : null}

      {(errors.length > 0 ? errors : others).length > 0 ? (
        <ul className="space-y-1">
          {(errors.length > 0 ? errors : others).map((issue, index) => (
            <li
              key={`${issue.code}-${index}`}
              className={`text-[11px] ${
                issue.severity === "ERROR"
                  ? "text-rose-300"
                  : issue.severity === "WARNING"
                    ? "text-amber-300/90"
                    : "text-slate-500"
              }`}
            >
              <span className={`${BADGE} ${SEVERITY_BADGE_CLASS[issue.severity as IssueSeverity]}`}>
                {SEVERITY_LABELS[issue.severity as IssueSeverity]}
              </span>{" "}
              {ISSUE_LABELS[issue.code] ?? issue.code}：{issue.message}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="space-y-1">
          <span className="block text-[11px] text-slate-500">时长（秒）</span>
          <input
            type="number"
            min={1}
            max={30}
            value={duration}
            onChange={(event) => setDuration(Number(event.target.value))}
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 text-xs
              text-slate-200 focus:border-brand-500 focus:outline-none"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-[11px] text-slate-500">景别</span>
          <select
            value={shotSize}
            onChange={(event) => setShotSize(event.target.value as ShotSize)}
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 text-xs
              text-slate-200 focus:border-brand-500 focus:outline-none"
          >
            {SHOT_SIZES.map((value) => (
              <option key={value} value={value}>
                {SHOT_SIZE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block text-[11px] text-slate-500">运镜</span>
          <select
            value={movement}
            onChange={(event) => setMovement(event.target.value as CameraMovement)}
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 text-xs
              text-slate-200 focus:border-brand-500 focus:outline-none"
          >
            {CAMERA_MOVEMENTS.map((value) => (
              <option key={value} value={value}>
                {CAMERA_MOVEMENT_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="block space-y-1">
        <span className="block text-[11px] text-slate-500">台词</span>
        <input
          value={dialogue}
          onChange={(event) => setDialogue(event.target.value)}
          className="w-full rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 text-xs
            text-slate-200 focus:border-brand-500 focus:outline-none"
        />
      </label>

      <label className="block space-y-1">
        <span className="block text-[11px] text-slate-500">文生图提示词</span>
        <textarea
          rows={3}
          value={imagePrompt}
          onChange={(event) => setImagePrompt(event.target.value)}
          className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 font-mono
            text-[11px] leading-relaxed text-slate-300 focus:border-brand-500 focus:outline-none"
        />
      </label>

      <label className="block space-y-1">
        <span className="block text-[11px] text-slate-500">图生视频提示词</span>
        <textarea
          rows={2}
          value={videoPrompt}
          onChange={(event) => setVideoPrompt(event.target.value)}
          className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-2 py-1.5 font-mono
            text-[11px] leading-relaxed text-slate-300 focus:border-brand-500 focus:outline-none"
        />
      </label>

      <FormError error={error} />

      <div className="flex flex-wrap items-center justify-end gap-2">
        <span className="mr-auto text-[11px] text-slate-600">
          出场角色由模型绑定到人物设定，不在此处编辑以免引入不存在的角色。
        </span>
        {saved && !dirty ? <span className="text-[11px] text-accent-400">已保存</span> : null}
        {dirty ? (
          <button type="button" className="btn-ghost" onClick={reset} disabled={saving}>
            撤销
          </button>
        ) : null}
        <button
          type="button"
          className="btn-primary"
          onClick={() => void handleSave()}
          disabled={!dirty || saving}
        >
          {saving ? "保存中…" : "保存镜头"}
        </button>
      </div>
    </article>
  );
}

// =========================================================================== #
// Consistency (PRD section 19)
// =========================================================================== #
function ConsistencyPanel({
  report,
  onRecheck,
}: {
  report: { issues: ConsistencyIssue[]; checked_shots: number; checked_scenes: number } | null;
  onRecheck: () => void;
}) {
  if (!report) return null;

  const errors = report.issues.filter((issue) => issue.severity === "ERROR");
  const warnings = report.issues.filter((issue) => issue.severity === "WARNING");

  return (
    <div className="panel space-y-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="label-caps">一致性检查</h3>
          <span
            className={`${BADGE} ring-1 ${
              errors.length > 0
                ? "bg-rose-500/15 text-rose-300 ring-rose-500/30"
                : "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
            }`}
          >
            {errors.length > 0 ? `发现 ${errors.length} 个错误` : "通过"}
          </span>
          {warnings.length > 0 ? (
            <span className={`${BADGE} bg-amber-500/15 text-amber-300 ring-amber-500/30`}>
              {warnings.length} 个警告
            </span>
          ) : null}
        </div>
        <button type="button" className="btn-ghost" onClick={onRecheck}>
          重新检查
        </button>
      </div>

      <p className="text-[11px] text-slate-500">
        已核对 {report.checked_scenes} 个场景 / {report.checked_shots} 个镜头，
        校验人物、场景、画风与时长是否与设定一致（不调用模型，可随时复检）。
      </p>

      {report.issues.length === 0 ? (
        <p className="text-xs text-emerald-300/90">
          全部镜头与 Story Bible / Character Bible / Scene Bible 一致。
        </p>
      ) : null}
    </div>
  );
}
