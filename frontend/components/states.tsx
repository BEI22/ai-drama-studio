"use client";

import { ApiError } from "@/lib/api";

export function LoadingState({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="panel space-y-3 p-5" role="status" aria-live="polite">
      <div className="skeleton h-4 w-1/3" />
      <div className="skeleton h-3 w-2/3" />
      <div className="skeleton h-3 w-1/2" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="panel flex flex-col items-center gap-3 px-6 py-12 text-center">
      <p className="text-sm text-slate-300">{title}</p>
      {description ? (
        <p className="max-w-md text-xs leading-relaxed text-slate-500">{description}</p>
      ) : null}
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: ApiError;
  onRetry?: () => void;
}) {
  return (
    <div className="panel border-rose-500/40 bg-rose-500/5 p-5" role="alert">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-sm font-medium text-rose-300">请求失败</p>
          <p className="text-xs text-rose-200/80">{error.message}</p>
          <p className="font-mono text-[11px] text-slate-500">
            code={error.code}
            {error.requestId ? ` · request_id=${error.requestId}` : ""}
            {error.isNetworkError ? " · 后端不可达" : ""}
          </p>
        </div>
        {onRetry ? (
          <button type="button" className="btn-ghost shrink-0" onClick={onRetry}>
            重试
          </button>
        ) : null}
      </div>
    </div>
  );
}
