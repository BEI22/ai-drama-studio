"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { EpisodesTab } from "@/components/episode-agent";
import { ErrorState, LoadingState, SignInRequired } from "@/components/states";
import { AssetsTab, TasksTab } from "@/components/media-tabs";
import {
  AnalysisBadge,
  AnalyzePanel,
  CharactersTab,
  LocationsTab,
  StoryBibleView,
  useBible,
} from "@/components/story-agent";
import { api, ApiError, type ProjectDetail, type StorySource } from "@/lib/api";
import type { StoryBibleResponse } from "@/types/api";

/** PRD section 5.3 left navigation. Tabs above the current phase are marked. */
const TABS = [
  { key: "overview", label: "项目概览", phase: 2 },
  { key: "story", label: "故事设定", phase: 2 },
  { key: "characters", label: "人物", phase: 3 },
  { key: "locations", label: "场景", phase: 3 },
  { key: "episodes", label: "剧集", phase: 4 },
  { key: "assets", label: "素材", phase: 5 },
  { key: "tasks", label: "生成任务", phase: 5 },
  { key: "settings", label: "设置", phase: 2 },
] as const;

/** Highest phase delivered so far -- drives the "not implemented" placeholders. */
const DELIVERED_PHASE = 5;

type TabKey = (typeof TABS)[number]["key"];

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "草稿",
  ACTIVE: "进行中",
  ARCHIVED: "已归档",
  FAILED: "失败",
};

const SOURCE_LABELS: Record<StorySource, string> = {
  SYNOPSIS: "故事梗概",
  NOVEL: "小说文本",
  SCRIPT: "剧本",
};

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = params?.id ?? "";

  const { user, initializing } = useAuth();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      setProject(await api.getProject(projectId));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("加载项目失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (initializing || !user) return;
    void load();
  }, [initializing, user, load]);

  // The Bible feeds the overview banner, the characters tab and the locations
  // tab, so it is loaded once here. This hook MUST stay above the early returns
  // below -- calling it after a conditional return would change the hook order
  // between renders and crash React. It is gated on `project` so no request is
  // made before the project itself has loaded.
  const { bible, loading: bibleLoading, error: bibleError, reload: reloadBible, setBible } =
    useBible(projectId, Boolean(project));

  if (initializing || !user) return <SignInRequired what="项目详情" />;

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-8 w-1/3" />
        <LoadingState />
      </div>
    );
  }

  if (error) {
    const missing = error.isNotFound;
    return (
      <div className="space-y-4">
        <Link href="/" className="text-xs text-slate-500 hover:text-slate-300">
          ← 返回项目列表
        </Link>
        <ErrorState
          error={error}
          onRetry={missing ? undefined : load}
          title={missing ? "项目不存在" : "请求失败"}
        />
        {missing ? (
          <p className="text-xs text-slate-500">
            项目可能已被删除，或它属于其他账号。
          </p>
        ) : null}
      </div>
    );
  }

  if (!project) return null;

  const activeTab = TABS.find((item) => item.key === tab) ?? TABS[0];
  const notYet = activeTab.phase > DELIVERED_PHASE;

  function handleAnalyzed(result: StoryBibleResponse) {
    setBible(result);
    void load();
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="text-xs text-slate-500 hover:text-slate-300">
          ← 返回项目列表
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold text-white">{project.name}</h1>
          <span className="badge border-ink-600 bg-ink-850 text-slate-400">
            {STATUS_LABELS[project.status] ?? project.status}
          </span>
        </div>
        <p className="mt-1 text-sm text-slate-400">{project.description || "暂无简介"}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[13rem_1fr]">
        <aside>
          <nav className="panel flex flex-col gap-0.5 p-2" aria-label="项目导航">
            {TABS.map((item) => {
              const active = item.key === tab;
              const pending = item.phase > DELIVERED_PHASE;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setTab(item.key)}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                    active
                      ? "bg-brand-500/10 text-brand-400"
                      : "text-slate-400 hover:bg-ink-850 hover:text-slate-200"
                  }`}
                >
                  <span>{item.label}</span>
                  {pending ? (
                    <span className="font-mono text-[10px] text-slate-600">P{item.phase}</span>
                  ) : null}
                </button>
              );
            })}
          </nav>
        </aside>

        <section className="min-w-0">
          {notYet ? (
            <div className="panel flex flex-col items-center gap-2 px-6 py-14 text-center">
              <p className="text-sm text-slate-300">{activeTab.label} 尚未实现</p>
              <p className="max-w-md text-xs leading-relaxed text-slate-500">
                该模块计划在 Phase {activeTab.phase} 交付。目前已完成到 Phase {DELIVERED_PHASE}
                ：项目 CRUD、故事文本、Story Agent 解析出的 Story Bible / 人物 / 场景，
                以及 Episode Agent 的分集、剧本与分镜。
              </p>
            </div>
          ) : tab === "overview" ? (
            <OverviewTab
              project={project}
              bible={bible}
              bibleLoading={bibleLoading}
              bibleError={bibleError}
              onRetryBible={reloadBible}
              onOpenTab={setTab}
            />
          ) : tab === "story" ? (
            <div className="space-y-4">
              <StoryTab project={project} onSaved={setProject} />
              <AnalyzePanel
                projectId={project.id}
                projectName={project.name}
                analysisStatus={project.analysis_status}
                analysisError={project.analysis_error}
                hasStory={project.has_story}
                characterCount={project.character_count}
                locationCount={project.location_count}
                onDone={handleAnalyzed}
                onOpenTab={setTab}
              />
              {bibleLoading ? <LoadingState label="正在加载 Story Bible…" /> : null}
              {bibleError ? (
                <ErrorState error={bibleError} onRetry={reloadBible} title="加载 Story Bible 失败" />
              ) : null}
              {bible ? <StoryBibleView bible={bible} /> : null}
            </div>
          ) : tab === "characters" ? (
            <CharactersTab
              projectId={project.id}
              analysisStatus={project.analysis_status}
              characters={bible?.characters ?? []}
              onCharactersChanged={(next) => {
                if (bible) setBible({ ...bible, characters: next });
              }}
              onReferenceChanged={reloadBible}
            />
          ) : tab === "locations" ? (
            <LocationsTab
              analysisStatus={project.analysis_status}
              locations={bible?.locations ?? []}
              onLocationsChanged={(next) => {
                if (bible) setBible({ ...bible, locations: next });
              }}
              onReferenceChanged={reloadBible}
            />
          ) : tab === "episodes" ? (
            <EpisodesTab
              projectId={project.id}
              analysisStatus={project.analysis_status}
              characters={bible?.characters ?? []}
              locations={bible?.locations ?? []}
              onEpisodesChanged={load}
            />
          ) : tab === "assets" ? (
            <AssetsTab projectId={project.id} />
          ) : tab === "tasks" ? (
            <TasksTab projectId={project.id} />
          ) : (
            <SettingsTab project={project} onChanged={load} />
          )}
        </section>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- overview
function OverviewTab({
  project,
  bible,
  bibleLoading,
  bibleError,
  onRetryBible,
  onOpenTab,
}: {
  project: ProjectDetail;
  bible: StoryBibleResponse | null;
  bibleLoading: boolean;
  bibleError: ApiError | null;
  onRetryBible: () => void;
  onOpenTab: (tab: "characters" | "locations" | "episodes") => void;
}) {
  const steps: { label: string; done: boolean | null; phase: number }[] = [
    { label: "项目创建", done: true, phase: 2 },
    { label: "故事文本录入", done: project.has_story, phase: 2 },
    { label: "故事解析（Story Bible）", done: project.analysis_status === "SUCCEEDED", phase: 3 },
    { label: "分集规划", done: project.episode_count > 0, phase: 4 },
    // `null` means "this panel cannot know". The project detail payload carries
    // only an episode *count*, so whether those episodes actually have scripts
    // and storyboards is reported by the 剧集 tab -- guessing here would show a
    // confident "待开发" for work that is already done.
    { label: "剧本生成", done: null, phase: 4 },
    { label: "分镜生成", done: null, phase: 4 },
    { label: "图片生成", done: null, phase: 5 },
    { label: "视频生成", done: null, phase: 6 },
    { label: "配音 / 字幕 / 合成", done: null, phase: 7 },
  ];

  return (
    <div className="space-y-4">
      <div className="panel p-5">
        <h2 className="label-caps">项目信息</h2>
        <dl className="mt-4 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <Field label="题材" value={project.genre || "—"} />
          <Field label="画风" value={project.style || "—"} />
          <Field label="状态" value={STATUS_LABELS[project.status] ?? project.status} />
          <Field
            label="故事来源"
            value={project.story_source ? SOURCE_LABELS[project.story_source] : "—"}
          />
          <Field label="已生成集数" value={String(project.episode_count)} />
          <Field label="故事文本" value={project.has_story ? "已保存" : "未填写"} />
          <Field label="人物数" value={String(project.character_count)} />
          <Field label="场景数" value={String(project.location_count)} />
          <Field label="创建时间" value={formatDateTime(project.created_at)} />
          <Field label="更新时间" value={formatDateTime(project.updated_at)} />
        </dl>
      </div>

      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="label-caps">故事解析状态</h2>
          <AnalysisBadge status={project.analysis_status} />
        </div>

        {project.analysis_error ? (
          <p className="mt-3 break-all rounded-lg border border-rose-500/40 bg-rose-500/5 p-3 font-mono text-[11px] text-rose-200/80">
            {project.analysis_error}
          </p>
        ) : null}

        {project.analysis_status === "SUCCEEDED" ? (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-slate-400">
              解析完成于 {formatDateTime(project.analyzed_at ?? "")}，共提取
              <span className="text-slate-200"> {project.character_count} </span>个人物、
              <span className="text-slate-200"> {project.location_count} </span>个场景。
            </p>
            {bible?.story_bible?.logline ? (
              <p className="rounded-lg border border-ink-800 bg-ink-950/40 p-3 text-xs leading-relaxed text-slate-300">
                {bible.story_bible.logline}
              </p>
            ) : null}
            {bibleLoading ? <LoadingState label="正在加载 Story Bible…" /> : null}
            {bibleError ? (
              <ErrorState error={bibleError} onRetry={onRetryBible} title="加载 Story Bible 失败" />
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-ghost"
                onClick={() => onOpenTab("characters")}
              >
                查看人物（{project.character_count}）
              </button>
              <button type="button" className="btn-ghost" onClick={() => onOpenTab("locations")}>
                查看场景（{project.location_count}）
              </button>
              <button type="button" className="btn-ghost" onClick={() => onOpenTab("episodes")}>
                查看剧集（{project.episode_count}）
              </button>
            </div>
          </div>
        ) : (
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            {project.has_story
              ? "故事文本已就绪。切换到「故事设定」运行 Story Agent，即可生成 Story Bible、人物与场景设定。"
              : "还没有故事文本。先在「故事设定」里录入内容。"}
          </p>
        )}
      </div>

      <div className="panel p-5">
        <div className="flex items-center justify-between">
          <h2 className="label-caps">流水线进度</h2>
          <span className="text-[11px] text-slate-500">Phase {DELIVERED_PHASE} / 8</span>
        </div>
        <ol className="mt-4 space-y-2 text-xs">
          {steps.map((step) => {
            // `done === null` means this panel cannot know the state; point the
            // user at the tab that owns the data instead of showing a verdict.
            const viewable = step.done === null && step.phase <= DELIVERED_PHASE;
            return (
              <li key={step.label} className="flex items-center justify-between gap-4">
                <span className={step.done === true ? "text-slate-300" : "text-slate-500"}>
                  {step.label}
                </span>
                {viewable ? (
                  <button
                    type="button"
                    className="text-[11px] text-brand-400 transition-colors hover:text-brand-300"
                    onClick={() => onOpenTab("episodes")}
                  >
                    在剧集查看 →
                  </button>
                ) : (
                  <span
                    className={`badge ${
                      step.done === true
                        ? "border-accent-500/40 bg-accent-500/10 text-accent-400"
                        : "border-ink-600 bg-ink-850 text-slate-600"
                    }`}
                  >
                    {step.done === true ? "完成" : step.done === false ? "待办" : "待开发"}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-ink-800/60 pb-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right text-slate-300">{value}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------- story
function StoryTab({
  project,
  onSaved,
}: {
  project: ProjectDetail;
  onSaved: (project: ProjectDetail) => void;
}) {
  const [source, setSource] = useState<StorySource | "">(project.story_source ?? "");
  const [text, setText] = useState(project.story_text ?? "");
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const dirty = source !== (project.story_source ?? "") || text !== (project.story_text ?? "");
  const missingSource = text.trim().length > 0 && !source;
  const canSave = text.trim().length > 0 && !missingSource && !saving && dirty;

  async function handleSave() {
    if (!source) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.saveStory(project.id, {
        story_source: source,
        story_text: text,
      });
      onSaved(updated);
      setSavedAt(new Date().toLocaleTimeString("zh-CN"));
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

  async function handleClear() {
    setClearing(true);
    setError(null);
    try {
      await api.clearStory(project.id);
      const updated = await api.getProject(project.id);
      onSaved(updated);
      setSource("");
      setText("");
      setSavedAt(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("清空失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="panel space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="label-caps">故事设定</h2>
          {savedAt ? (
            <span className="text-[11px] text-accent-400">已保存 · {savedAt}</span>
          ) : dirty ? (
            <span className="text-[11px] text-amber-400">有未保存的修改</span>
          ) : null}
        </div>

        <fieldset className="space-y-2">
          <legend className="mb-1 block text-sm text-slate-300">故事来源</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {(["SYNOPSIS", "NOVEL", "SCRIPT"] as StorySource[]).map((value) => {
              const active = source === value;
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSource(active ? "" : value)}
                  className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
                    active
                      ? "border-brand-500 bg-brand-500/10 text-brand-400"
                      : "border-ink-600 text-slate-300 hover:bg-ink-850"
                  }`}
                >
                  {SOURCE_LABELS[value]}
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="space-y-1.5">
          <label htmlFor="story-text" className="block text-sm text-slate-300">
            故事内容
          </label>
          <textarea
            id="story-text"
            rows={14}
            maxLength={200000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="粘贴你的故事梗概 / 小说文本 / 剧本……"
            className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 font-mono
              text-xs leading-relaxed text-slate-200 placeholder:text-slate-600
              focus:border-brand-500 focus:outline-none"
          />
          <div className="flex items-center justify-between text-[11px]">
            <span className={missingSource ? "text-rose-400" : "text-slate-500"}>
              {missingSource ? "填写了内容，请先选择故事来源" : "Phase 2 仅保存，不做 AI 解析"}
            </span>
            <span className="font-mono text-slate-600">{text.length} 字符</span>
          </div>
        </div>

        {error ? (
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-3 text-xs text-rose-200">
            {error.message}
            {error.requestId ? (
              <span className="ml-2 font-mono text-[10px] text-slate-500">
                request_id={error.requestId}
              </span>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-end gap-3">
          {project.has_story ? (
            <button
              type="button"
              className="btn-ghost"
              onClick={handleClear}
              disabled={clearing}
            >
              {clearing ? "清空中…" : "清空故事"}
            </button>
          ) : null}
          <button type="button" className="btn-primary" onClick={handleSave} disabled={!canSave}>
            {saving ? "保存中…" : "保存故事"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- settings
function SettingsTab({
  project,
  onChanged,
}: {
  project: ProjectDetail;
  onChanged: () => Promise<void> | void;
}) {
  const router = useRouter();
  const [name, setName] = useState(project.name);
  const [genre, setGenre] = useState(project.genre ?? "");
  const [style, setStyle] = useState(project.style ?? "");
  const [description, setDescription] = useState(project.description ?? "");
  const [status, setStatus] = useState(project.status);

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateProject(project.id, {
        name: name.trim(),
        genre: genre || null,
        style: style || null,
        description: description.trim() || null,
        status,
      });
      await onChanged();
      setNotice("已保存");
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

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProject(project.id);
      router.push("/");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("删除失败", { code: "UNKNOWN", status: 0, requestId: null }),
      );
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSave} className="panel space-y-4 p-5" noValidate>
        <h2 className="label-caps">项目设置</h2>

        <div className="space-y-1.5">
          <label htmlFor="s-name" className="block text-sm text-slate-300">
            项目名称
          </label>
          <input
            id="s-name"
            required
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
              text-slate-200 focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="s-genre" className="block text-sm text-slate-300">
              题材
            </label>
            <input
              id="s-genre"
              value={genre}
              onChange={(event) => setGenre(event.target.value)}
              className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
                text-slate-200 focus:border-brand-500 focus:outline-none"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="s-style" className="block text-sm text-slate-300">
              画风
            </label>
            <input
              id="s-style"
              value={style}
              onChange={(event) => setStyle(event.target.value)}
              className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
                text-slate-200 focus:border-brand-500 focus:outline-none"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="s-desc" className="block text-sm text-slate-300">
            简介
          </label>
          <textarea
            id="s-desc"
            rows={2}
            maxLength={2000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
              text-slate-200 focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="s-status" className="block text-sm text-slate-300">
            状态
          </label>
          <select
            id="s-status"
            value={status}
            onChange={(event) => setStatus(event.target.value as ProjectDetail["status"])}
            className="rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-slate-200
              focus:border-brand-500 focus:outline-none"
          >
            <option value="DRAFT">草稿</option>
            <option value="ACTIVE">进行中</option>
            <option value="ARCHIVED">已归档</option>
          </select>
        </div>

        {error ? (
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-3 text-xs text-rose-200">
            {error.message}
          </div>
        ) : null}
        {notice ? <p className="text-xs text-accent-400">{notice}</p> : null}

        <div className="flex justify-end">
          <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>
            {saving ? "保存中…" : "保存修改"}
          </button>
        </div>
      </form>

      <div className="panel border-rose-500/30 p-5">
        <h2 className="label-caps text-rose-400">危险操作</h2>
        <p className="mt-3 text-xs leading-relaxed text-slate-500">
          删除项目会同时移除它的剧集、剧本与分镜数据，且无法恢复。
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {confirmDelete ? (
            <>
              <button
                type="button"
                className="btn rounded-lg bg-rose-600 px-4 py-2 text-sm text-white hover:bg-rose-500"
                onClick={handleDelete}
                disabled={deleting}
              >
                {deleting ? "删除中…" : "确认删除"}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
              >
                取消
              </button>
            </>
          ) : (
            <button type="button" className="btn-ghost" onClick={() => setConfirmDelete(true)}>
              删除项目
            </button>
          )}
        </div>
      </div>
    </div>
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
