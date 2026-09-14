"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { EmptyState, ErrorState, LoadingState, SignInRequired } from "@/components/states";
import { api, ApiError, type ProjectListItem, type ProjectStatus } from "@/lib/api";

const STATUS_STYLES: Record<ProjectStatus, string> = {
  DRAFT: "border-ink-600 bg-ink-850 text-slate-400",
  ACTIVE: "border-accent-500/40 bg-accent-500/10 text-accent-400",
  ARCHIVED: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  FAILED: "border-rose-500/40 bg-rose-500/10 text-rose-400",
};

const STATUS_LABELS: Record<ProjectStatus, string> = {
  DRAFT: "草稿",
  ACTIVE: "进行中",
  ARCHIVED: "已归档",
  FAILED: "失败",
};

const PAGE_SIZE = 12;

export default function DashboardPage() {
  const { user, initializing } = useAuth();

  const [items, setItems] = useState<ProjectListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<ProjectStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.listProjects({
        page,
        pageSize: PAGE_SIZE,
        search: query || undefined,
        status: status || undefined,
      });
      setItems(result.items);
      setTotal(result.total);
      setPages(result.pages);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("加载项目列表失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    } finally {
      setLoading(false);
    }
  }, [page, query, status]);

  useEffect(() => {
    if (initializing || !user) return;
    void load();
  }, [initializing, user, load]);

  // Debounce the search box so we don't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const heading = useMemo(
    () => (
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">我的项目</h1>
          <p className="mt-1 text-sm text-slate-400">
            {total > 0 ? `共 ${total} 个项目` : "从一段故事开始，产出一集成片。"}
          </p>
        </div>
        <Link href="/projects/new" className="btn-primary">
          + 创建项目
        </Link>
      </div>
    ),
    [total],
  );

  if (initializing || !user) {
    return (
      <div className="space-y-6">
        {heading}
        <SignInRequired what="我的项目" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {heading}

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="按项目名称搜索…"
          aria-label="搜索项目"
          className="min-w-[16rem] flex-1 rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm
            text-slate-200 placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
        />
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as ProjectStatus | "");
            setPage(1);
          }}
          aria-label="按状态筛选"
          className="rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slate-200
            focus:border-brand-500 focus:outline-none"
        >
          <option value="">全部状态</option>
          {(Object.keys(STATUS_LABELS) as ProjectStatus[]).map((key) => (
            <option key={key} value={key}>
              {STATUS_LABELS[key]}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <LoadingState />
          <LoadingState />
          <LoadingState />
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={load} />
      ) : items.length === 0 ? (
        query || status ? (
          <EmptyState
            title="没有匹配的项目"
            description="换个关键词或清除筛选条件再试。"
            action={
              <button
                type="button"
                className="btn-ghost mt-1"
                onClick={() => {
                  setSearch("");
                  setQuery("");
                  setStatus("");
                  setPage(1);
                }}
              >
                清除筛选
              </button>
            }
          />
        ) : (
          <EmptyState
            title="还没有项目"
            description="创建一个项目并粘贴你的故事梗概，AI 会自动解析世界观、人物与场景，进而生成剧本与分镜。"
            action={
              <Link href="/projects/new" className="btn-primary mt-1">
                创建第一个项目
              </Link>
            }
          />
        )
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>

          {pages > 1 ? (
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>
                第 {page} / {pages} 页
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  上一页
                </button>
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  disabled={page >= pages}
                  onClick={() => setPage((value) => Math.min(pages, value + 1))}
                >
                  下一页
                </button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: ProjectListItem }) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="panel group flex flex-col gap-4 p-5 transition-colors hover:border-brand-500/50"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="line-clamp-1 text-base font-medium text-white group-hover:text-brand-400">
          {project.name}
        </h2>
        <span className={`badge shrink-0 ${STATUS_STYLES[project.status]}`}>
          {STATUS_LABELS[project.status]}
        </span>
      </div>

      <p className="line-clamp-2 min-h-[2.5rem] text-xs leading-relaxed text-slate-500">
        {project.description || project.genre || "暂无简介"}
      </p>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-slate-500">
        <span>已生成 {project.episode_count} 集</span>
        <span>{project.has_story ? "已录入故事" : "缺故事"}</span>
      </div>

      <div className="mt-auto flex items-center justify-between border-t border-ink-800 pt-3 text-[11px] text-slate-600">
        <span>更新于 {formatDateTime(project.updated_at)}</span>
        {project.genre ? <span className="text-slate-500">{project.genre}</span> : null}
      </div>
    </Link>
  );
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
