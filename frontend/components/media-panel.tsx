"use client";

/**
 * Media UI for Phase 5 (PRD sections 21, 22): shot images, reference images and
 * generation-task state.
 *
 * Two behaviours here are deliberate and easy to get wrong:
 *
 * 1. **Polling stops.** PRD §21's task row is polled only while it can still
 *    change (PENDING/RUNNING/RETRY). A SUCCESS/FAILED task is terminal, so the
 *    interval is cleared -- otherwise every rendered shot keeps a timer alive
 *    forever, and a 50-shot episode opens 50 of them.
 *
 * 2. **The image is not "the shot's picture" until the response says so.** The
 *    generate endpoint returns a *task*, not an image; the picture appears when
 *    the parent re-reads the storyboard after the task settles. So the panel
 *    reports completion upward instead of guessing that the click produced a file.
 */

import { useEffect, useRef, useState } from "react";

import { api, ApiError, type Asset, type ShotImageState, type TaskStatus } from "@/lib/api";
import { FormError } from "@/components/states";
import { isTaskLive, TASK_STATUS_BADGE_CLASS, TASK_STATUS_LABELS } from "@/types/api";

function asApiError(caught: unknown, fallback: string): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError(fallback, { code: "UNKNOWN", status: 0, requestId: null });
}

export function TaskBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`badge ring-1 ${TASK_STATUS_BADGE_CLASS[status]}`}>
      {TASK_STATUS_LABELS[status]}
    </span>
  );
}

/**
 * Poll a task until it settles, then tell the parent to refresh.
 *
 * The callback lives in a ref on purpose. Parents here pass inline arrow
 * functions ("refresh the storyboard"), so the callback's identity changes on
 * every parent render -- and a timer set up inside an effect that depends on it
 * would be torn down and restarted on every render, turning a 2.5s poll into a
 * tight request loop. Only the task id may restart the watch.
 */
function useTaskWatch(taskId: string | null, onSettled: () => void) {
  const settledRef = useRef<string | null>(null);
  const callbackRef = useRef(onSettled);
  callbackRef.current = onSettled;

  useEffect(() => {
    if (!taskId || settledRef.current === taskId) return;

    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const task = await api.getTask(taskId);
        if (cancelled) return;
        if (isTaskLive(task.status)) {
          timer = window.setTimeout(poll, 2500);
        } else {
          settledRef.current = taskId;
          callbackRef.current();
        }
      } catch {
        // A transient read failure must not kill the watch: the picture may
        // still be generating, and the next tick can recover.
        if (!cancelled) timer = window.setTimeout(poll, 4000);
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [taskId]);
}

/**
 * One shot's image: the picture, its state, and the actions that change it.
 *
 * `generate` is refused by the API with 409 once a picture exists (PRD §38's
 * overwrite guard), so the button switches to "重新生成" rather than surfacing a
 * conflict the user cannot act on.
 */
export function ShotImagePanel({
  state,
  onChanged,
  compact = false,
}: {
  state: ShotImageState | undefined;
  onChanged: () => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const task = state?.latest_task ?? null;
  const asset: Asset | null = state?.asset ?? null;
  const live = task ? isTaskLive(task.status) : false;
  const failed = task?.status === "FAILED";

  useTaskWatch(live && task ? task.id : null, onChanged);

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (caught) {
      setError(asApiError(caught, `${label}失败`));
    } finally {
      setBusy(null);
    }
  }

  async function handleRetry() {
    if (!task) return;
    await run("重试", () => api.retryTask(task.id));
  }

  return (
    <div
      data-testid="shot-image-panel"
      data-shot-id={state?.shot_id ?? ""}
      className={compact ? "space-y-2" : "space-y-2 rounded-lg border border-ink-700 p-3"}
    >
      <div className="flex items-center gap-2 text-[11px]">
        <span className="text-slate-500">图片</span>
        {task ? <TaskBadge status={task.status} /> : <span className="text-slate-600">未生成</span>}
        {state && state.image_count > 1 ? (
          <span className="font-mono text-[10px] text-slate-600">{state.image_count} 次尝试</span>
        ) : null}
      </div>

      {asset?.url ? (
        <a href={asset.url} target="_blank" rel="noreferrer" className="block">
          {/* Signed, expiring URL from the API -- plain <img>, not next/image:
              the optimizer would try to cache a link that expires. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={asset.url}
            alt={`镜头 ${state?.shot_number ?? ""} 的分镜图`}
            className="w-full rounded-lg border border-ink-700 bg-ink-950 object-cover"
            loading="lazy"
          />
        </a>
      ) : live ? (
        <div className="skeleton h-24 w-full rounded-lg" aria-live="polite" />
      ) : null}

      {task?.error_message ? (
        <p className="break-all rounded border border-rose-500/40 bg-rose-500/5 p-2 font-mono text-[10px] text-rose-200/80">
          {task.error_message}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-ghost px-2 py-0.5 text-[11px]"
          disabled={busy !== null || live}
          onClick={() =>
            void run(asset ? "重新生成" : "生成图片", () =>
              asset
                ? api.regenerateShotImage(state!.shot_id)
                : api.generateShotImage(state!.shot_id),
            )
          }
        >
          {busy === "生成图片" || busy === "重新生成"
            ? `${busy}中…`
            : live
              ? "生成中…"
              : asset
                ? "重新生成"
                : "生成图片"}
        </button>

        {failed ? (
          <button
            type="button"
            className="btn-ghost px-2 py-0.5 text-[11px] text-amber-300"
            disabled={busy !== null}
            onClick={() => void handleRetry()}
          >
            {busy === "重试" ? "重试中…" : "重试"}
          </button>
        ) : null}
      </div>

      <FormError error={error} />
    </div>
  );
}

/**
 * Episode-level image toolbar: batch generation plus the rollup.
 *
 * The batch action skips shots that already have a picture (the API reports how
 * many it skipped), so it is safe to press twice and the button can say so.
 */
export function EpisodeImageToolbar({
  episodeId,
  media,
  shotCount,
  onChanged,
}: {
  episodeId: string;
  media: Record<string, ShotImageState>;
  shotCount: number;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const entries = Object.values(media);
  const withImage = entries.filter((entry) => entry.asset).length;
  const running = entries.filter(
    (entry) => entry.latest_task && isTaskLive(entry.latest_task.status),
  ).length;
  const failed = entries.filter((entry) => entry.latest_task?.status === "FAILED").length;

  const provider = entries[0]?.latest_task?.provider ?? null;
  const missing = shotCount - withImage;

  // Keep the rollup moving while any shot is still generating. Depends on
  // `running` (a number) rather than the media object, whose identity changes on
  // every fetch and would restart this timer endlessly.
  const refreshRef = useRef(onChanged);
  refreshRef.current = onChanged;
  useEffect(() => {
    if (running === 0) return;
    const timer = window.setTimeout(() => refreshRef.current(), 3000);
    return () => window.clearTimeout(timer);
  }, [running]);

  async function handleBatch() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.generateEpisodeImages(episodeId);
      setNotice(
        result.queued === 0
          ? `所有 ${result.shots_total} 个镜头都已有图片`
          : `已排队 ${result.queued} 个镜头（跳过 ${result.skipped_existing} 个已有图片的）`,
      );
      onChanged();
    } catch (caught) {
      setError(asApiError(caught, "批量生成失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="episode-image-toolbar"
      data-with-image={withImage}
      data-shot-count={shotCount}
      data-running={running}
      className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3"
    >
      <span className="text-[11px] text-slate-400">
        图片 <span className="text-slate-200">{withImage}</span> / {shotCount}
      </span>
      {running > 0 ? <span className="text-[11px] text-sky-300">{running} 个生成中</span> : null}
      {failed > 0 ? <span className="text-[11px] text-rose-300">{failed} 个失败</span> : null}
      {provider ? (
        <span className="font-mono text-[10px] text-slate-600">provider: {provider}</span>
      ) : null}

      <div className="ml-auto flex items-center gap-2">
        {notice ? <span className="text-[11px] text-accent-400">{notice}</span> : null}
        <button
          type="button"
          className="btn-ghost"
          disabled={busy || missing === 0}
          onClick={() => void handleBatch()}
        >
          {busy ? "排队中…" : missing > 0 ? `生成整集图片（${missing}）` : "整集已生成"}
        </button>
      </div>

      {error ? (
        <div className="w-full">
          <FormError error={error} />
        </div>
      ) : null}
    </div>
  );
}

/** Reference-sheet control used on the 人物 / 场景 tabs (PRD §31 Phase 5). */
export function ReferenceImageButton({
  kind,
  id,
  currentUrl,
  onChanged,
}: {
  kind: "character" | "location";
  id: string;
  currentUrl: string | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleClick() {
    setBusy(true);
    setError(null);
    try {
      // force=true: the button only appears as "重新生成" once a reference exists,
      // and the API refuses to overwrite without it (PRD §38).
      const result =
        kind === "character"
          ? await api.generateCharacterReference(id, Boolean(currentUrl))
          : await api.generateLocationReference(id, Boolean(currentUrl));
      const taskId = result.task.id;

      // Poll until settled, then let the caller re-read the Bible.
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const task = await api.getTask(taskId);
        if (!isTaskLive(task.status)) {
          if (task.status === "FAILED") {
            setError(
              new ApiError(task.error_message ?? "参考图生成失败", {
                code: "GENERATION_FAILED",
                status: 0,
                requestId: null,
              }),
            );
          }
          break;
        }
      }
      onChanged();
    } catch (caught) {
      setError(asApiError(caught, "参考图生成失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="reference-image" className="space-y-2">
      {currentUrl ? (
        <a href={currentUrl} target="_blank" rel="noreferrer" className="block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={currentUrl}
            alt={`${kind === "character" ? "人物" : "场景"}参考图`}
            className="h-32 w-full rounded-lg border border-ink-700 bg-ink-950 object-contain"
            loading="lazy"
          />
        </a>
      ) : null}
      <button
        type="button"
        className="btn-ghost w-full text-[11px]"
        disabled={busy}
        onClick={() => void handleClick()}
      >
        {busy ? "生成中…" : currentUrl ? "重新生成参考图" : "生成参考图"}
      </button>
      <FormError error={error} />
    </div>
  );
}
