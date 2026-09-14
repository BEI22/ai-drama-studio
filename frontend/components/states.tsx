"use client";

import Link from "next/link";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

/** Shared error mapping so every form explains failures the same way. */
export function FormError({ error }: { error: ApiError | null }) {
  if (!error) return null;

  const fieldErrors = error.fieldErrors;

  return (
    <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-3" role="alert">
      <p className="text-xs leading-relaxed text-rose-200">{error.message}</p>
      {fieldErrors.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {fieldErrors.map((item) => (
            <li key={`${item.field}-${item.message}`} className="text-[11px] text-rose-300/80">
              {item.field ? <span className="font-mono">{item.field}</span> : null} {item.message}
            </li>
          ))}
        </ul>
      ) : null}
      {error.requestId ? (
        <p className="mt-2 font-mono text-[10px] text-slate-500">request_id={error.requestId}</p>
      ) : null}
    </div>
  );
}

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
    <div className="panel flex flex-col items-center gap-3 px-6 py-14 text-center">
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
  title = "请求失败",
}: {
  error: ApiError;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <div className="panel border-rose-500/40 bg-rose-500/5 p-5" role="alert">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-sm font-medium text-rose-300">{title}</p>
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

/** Rendered while auth state is being restored, or when the user is not signed in. */
export function SignInRequired({ what = "该页面" }: { what?: string }) {
  const { initializing, user } = useAuth();

  if (initializing) return <LoadingState label="正在恢复登录状态…" />;
  if (user) return null;

  return (
    <EmptyState
      title={`请先登录后查看${what}`}
      description="AI Studio 的项目数据与账号绑定，登录后才能创建和管理项目。"
      action={
        <Link href="/login" className="btn-primary mt-1">
          去登录 / 注册
        </Link>
      }
    />
  );
}
