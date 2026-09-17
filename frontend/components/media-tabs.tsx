"use client";

/**
 * Project-level media pages: 素材 (assets) and 生成任务 (generation tasks).
 *
 * PRD section 5.3 puts both in the project navigation; the app already carried them
 * as Phase 5 placeholders. Section 2.1 makes 生成任务状态 + 失败重试 an MVP
 * requirement, so the tasks page is not optional. Section 22 routes the task
 * endpoints but nothing for assets -- the 素材 grid reads the additive
 * ``GET /projects/{id}/assets`` (recorded as beyond section 22 in docs/TDD.md 19.7).
 *
 * Both pages are deliberately read-mostly: the tasks page can retry a failure, and
 * nothing here deletes. Generated media is the user's work product, so there is no
 * destructive control one mis-click away.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, FormError, LoadingState } from "@/components/states";
import { api, ApiError, type AssetListItem, type AssetType, type GenerationTask } from "@/lib/api";
import {
  ASSET_TYPE_LABELS,
  ASSET_TYPE_ORDER,
  isTaskLive,
  TASK_STATUS_BADGE_CLASS,
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
} from "@/types/api";

const BADGE = "rounded-full px-2 py-0.5 text-[10px] ring-1 ring-inset";

function asApiError(caught: unknown, fallback: string): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError(fallback, { code: "UNKNOWN", status: 0, requestId: null });
}

function formatTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", { hour12: false });
}

/** Seconds -> "12s" / "1m 20s"; task durations are the interesting number here. */
function formatElapsed(from: string | null, to: string | null): string {
  if (!from) return "—";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

// ------------------------------------------------------------------ 素材
export function AssetsTab({ projectId }: { projectId: string }) {
  const [assets, setAssets] = useState<AssetListItem[] | null>(null);
  const [totals, setTotals] = useState<{ assets: number; by_type: Record<string, number> } | null>(
    null,
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<AssetType | "ALL">("ALL");
  const [hasLoaded, setHasLoaded] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.listAssets(projectId, {
        assetType: filter === "ALL" ? undefined : filter,
      });
      setAssets(page.items);
      setTotals(page.totals);
      setHasLoaded(true);
    } catch (caught) {
      setError(asApiError(caught, "加载素材失败"));
    } finally {
      setLoading(false);
    }
  }, [projectId, filter]);

  useEffect(() => {
    void load();
  }, [load]);

  // Only offer filters for types that actually exist, plus whatever is selected --
  // an empty "视频 0" button is noise when Phase 5 cannot produce video at all.
  const availableTypes = useMemo(() => {
    const counts = totals?.by_type ?? {};
    return ASSET_TYPE_ORDER.filter((type) => (counts[type] ?? 0) > 0);
  }, [totals]);

  // Skeleton only on the first load: a filter change must not blow away the grid
  // (same rule as the storyboard panel -- a refetch is not a fresh page).
  if (loading && !hasLoaded) return <LoadingState label="正在加载素材…" />;
  if (error && !hasLoaded) return <ErrorState error={error} onRetry={load} />;
  if (!assets) return null;

  return (
    <div data-testid="assets-tab" className="space-y-4">
      <div className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3">
        <span className="text-[11px] text-slate-400">
          共 <span className="text-slate-200">{totals?.assets ?? assets.length}</span> 个素材
        </span>
        {availableTypes.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              aria-pressed={filter === "ALL"}
              className={`${BADGE} ${
                filter === "ALL"
                  ? "bg-brand-500/15 text-brand-400 ring-brand-500/30"
                  : "bg-ink-850 text-slate-400 ring-ink-600 hover:text-slate-200"
              }`}
              onClick={() => setFilter("ALL")}
            >
              全部
            </button>
            {availableTypes.map((type) => (
              <button
                key={type}
                type="button"
                aria-pressed={filter === type}
                className={`${BADGE} ${
                  filter === type
                    ? "bg-brand-500/15 text-brand-400 ring-brand-500/30"
                    : "bg-ink-850 text-slate-400 ring-ink-600 hover:text-slate-200"
                }`}
                onClick={() => setFilter(type)}
              >
                {ASSET_TYPE_LABELS[type]} {totals?.by_type[type] ?? 0}
              </button>
            ))}
          </div>
        ) : null}
        {loading ? <span className="text-[11px] text-slate-500">正在同步…</span> : null}
      </div>

      <FormError error={error} />

      {assets.length === 0 ? (
        <EmptyState
          title="还没有素材"
          description="到「剧集」里生成分镜图片，或在「人物 / 场景」里生成参考图，产出会汇总到这里。"
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {assets.map((asset) => (
            <figure
              key={asset.id}
              data-testid="asset-tile"
              className="panel overflow-hidden p-0"
            >
              {asset.url ? (
                <a href={asset.url} target="_blank" rel="noreferrer" className="block">
                  {/* Signed, expiring URL: plain <img>, never next/image, whose
                      optimizer would try to cache a link that expires (PRD §27). */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={asset.url}
                    alt={
                      asset.shot_number
                        ? `${asset.scene_id}-${asset.shot_number} 的分镜图`
                        : `${ASSET_TYPE_LABELS[asset.type]}素材`
                    }
                    className="h-40 w-full bg-ink-950 object-cover"
                    loading="lazy"
                  />
                </a>
              ) : (
                <div className="h-40 w-full bg-ink-950" />
              )}
              <figcaption className="space-y-1 p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`${BADGE} bg-ink-850 text-slate-400 ring-ink-600`}>
                    {ASSET_TYPE_LABELS[asset.type]}
                  </span>
                  {asset.shot_number ? (
                    <span className="font-mono text-[10px] text-slate-500">
                      {asset.scene_id}-{asset.shot_number}
                    </span>
                  ) : null}
                </div>
                <p className="truncate font-mono text-[10px] text-slate-600" title={asset.storage_key}>
                  {asset.storage_key}
                </p>
                <p className="text-[10px] text-slate-600">{formatTime(asset.created_at)}</p>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- 生成任务
export function TasksTab({ projectId }: { projectId: string }) {
  const [tasks, setTasks] = useState<GenerationTask[] | null>(null);
  const [totals, setTotals] = useState<{ by_status: Record<string, number> } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.listTasks(projectId);
      setTasks(page.items);
      setTotals(page.totals);
      setHasLoaded(true);
    } catch (caught) {
      setError(asApiError(caught, "加载生成任务失败"));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something can still change, and stop as soon as nothing can.
  // Without the terminal check this page would poll a finished project forever.
  const liveCount = (tasks ?? []).filter((task) => isTaskLive(task.status)).length;
  useEffect(() => {
    if (liveCount === 0) return;
    const timer = window.setTimeout(() => void load(), 3000);
    return () => window.clearTimeout(timer);
  }, [liveCount, load, tasks]);

  async function handleRetry(taskId: string) {
    setBusy(taskId);
    setError(null);
    setNotice(null);
    try {
      await api.retryTask(taskId);
      setNotice("已重新排队");
      await load();
    } catch (caught) {
      setError(asApiError(caught, "重试失败"));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !hasLoaded) return <LoadingState label="正在加载生成任务…" />;
  if (error && !hasLoaded) return <ErrorState error={error} onRetry={load} />;
  if (!tasks) return null;

  const failedCount = totals?.by_status?.FAILED ?? 0;

  return (
    <div data-testid="tasks-tab" className="space-y-4">
      <div className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 text-[11px]">
        <span className="text-slate-400">
          共 <span className="text-slate-200">{tasks.length}</span> 个任务
        </span>
        {(["PENDING", "RUNNING", "RETRY", "SUCCESS", "FAILED"] as const).map((state) => {
          const count = totals?.by_status?.[state] ?? 0;
          if (count === 0) return null;
          return (
            <span key={state} className={`${BADGE} ${TASK_STATUS_BADGE_CLASS[state]}`}>
              {TASK_STATUS_LABELS[state]} {count}
            </span>
          );
        })}
        {liveCount > 0 ? <span className="text-sky-300">生成中…</span> : null}
        {notice ? <span className="text-accent-400">{notice}</span> : null}
        {loading && hasLoaded ? <span className="text-slate-500">正在同步…</span> : null}
      </div>

      <FormError error={error} />

      {tasks.length === 0 ? (
        <EmptyState
          title="还没有生成任务"
          description="生成分镜图片、参考图或剧本时会创建任务，状态与重试都在这里。"
        />
      ) : (
        <div className="panel divide-y divide-ink-700 overflow-hidden p-0">
          {tasks.map((task) => (
            <div
              key={task.id}
              data-testid="task-row"
              data-task-status={task.status}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[11px]"
            >
              <span className={`${BADGE} ${TASK_STATUS_BADGE_CLASS[task.status]}`}>
                {TASK_STATUS_LABELS[task.status]}
              </span>
              <span className="text-slate-300">{TASK_TYPE_LABELS[task.task_type]}</span>
              <span className="font-mono text-[10px] text-slate-500">
                {task.provider ?? "—"}
                {task.model ? ` / ${task.model}` : ""}
              </span>

              {task.retry_count > 0 ? (
                <span className="text-amber-300/90">
                  已重试 {task.retry_count}/{task.max_retries}
                </span>
              ) : null}
              <span className="text-slate-600">耗时 {formatElapsed(task.started_at, task.completed_at)}</span>
              <span className="text-slate-600">{formatTime(task.created_at)}</span>

              {/* A failed task is the only one worth acting on here; retrying a
                  SUCCESS is refused by the API (use regenerate for a new take). */}
              {task.status === "FAILED" ? (
                <button
                  type="button"
                  className="btn-ghost ml-auto px-2 py-0.5 text-[11px] text-amber-300"
                  disabled={busy !== null}
                  onClick={() => void handleRetry(task.id)}
                >
                  {busy === task.id ? "重试中…" : "重试"}
                </button>
              ) : null}

              {task.error_message ? (
                <p className="w-full break-all rounded border border-rose-500/40 bg-rose-500/5 p-2 font-mono text-[10px] text-rose-200/80">
                  {task.error_message}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {failedCount > 0 ? (
        <p className="text-[11px] text-amber-300/90">
          有 {failedCount} 个任务失败 —— 点击对应行的「重试」重新排队。
        </p>
      ) : null}
    </div>
  );
}
