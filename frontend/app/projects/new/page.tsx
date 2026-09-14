"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { FormError, SignInRequired } from "@/components/states";
import { api, ApiError, type StorySource } from "@/lib/api";

const GENRES = ["都市", "玄幻", "科幻", "悬疑", "言情", "历史", "武侠", "奇幻"];
const STYLES = ["国漫", "日系", "美漫", "写实", "3D 渲染", "水彩"];

const STORY_SOURCES: { value: StorySource; label: string; hint: string }[] = [
  { value: "SYNOPSIS", label: "故事梗概", hint: "一段话讲清核心设定与冲突" },
  { value: "NOVEL", label: "小说文本", hint: "直接粘贴章节原文" },
  { value: "SCRIPT", label: "剧本", hint: "已有的场次 / 台词格式" },
];

export default function NewProjectPage() {
  const router = useRouter();
  const { user, initializing } = useAuth();

  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [style, setStyle] = useState("");
  const [description, setDescription] = useState("");
  const [storySource, setStorySource] = useState<StorySource | "">("");
  const [storyText, setStoryText] = useState("");

  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (initializing || !user) {
    return <SignInRequired what="创建项目" />;
  }

  const storyMissingSource = storyText.trim().length > 0 && !storySource;
  const canSubmit = name.trim().length > 0 && !storyMissingSource && !submitting;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const project = await api.createProject({
        name: name.trim(),
        genre: genre || null,
        style: style || null,
        description: description.trim() || null,
        story_source: storySource || null,
        story_text: storyText.trim() || null,
      });
      router.push(`/projects/${project.id}`);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("创建失败，请重试", { code: "UNKNOWN", status: 0, requestId: null }),
      );
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <div>
        <Link href="/" className="text-xs text-slate-500 hover:text-slate-300">
          ← 返回项目列表
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-white">创建项目</h1>
        <p className="mt-1 text-sm text-slate-400">
          先填基础信息与故事文本；后续的解析、剧本与分镜都会基于它生成。
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <section className="panel space-y-4 p-5">
          <h2 className="label-caps">基础信息</h2>

          <div className="space-y-1.5">
            <label htmlFor="name" className="block text-sm text-slate-300">
              项目名称 <span className="text-rose-400">*</span>
            </label>
            <input
              id="name"
              required
              maxLength={200}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：重生大学时代"
              className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
                text-slate-200 placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="genre" className="block text-sm text-slate-300">
                题材
              </label>
              <input
                id="genre"
                list="genre-options"
                value={genre}
                onChange={(event) => setGenre(event.target.value)}
                placeholder="都市"
                className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
                  text-slate-200 placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
              />
              <datalist id="genre-options">
                {GENRES.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="style" className="block text-sm text-slate-300">
                画风
              </label>
              <input
                id="style"
                list="style-options"
                value={style}
                onChange={(event) => setStyle(event.target.value)}
                placeholder="国漫"
                className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
                  text-slate-200 placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
              />
              <datalist id="style-options">
                {STYLES.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="description" className="block text-sm text-slate-300">
              项目简介
            </label>
            <textarea
              id="description"
              rows={2}
              maxLength={2000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="一句话说明这个项目（可留空）"
              className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm
                text-slate-200 placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
            />
          </div>
        </section>

        <section className="panel space-y-4 p-5">
          <div className="flex items-center justify-between">
            <h2 className="label-caps">故事文本</h2>
            <span className="text-[11px] text-slate-500">可先留空，稍后在项目详情里补充</span>
          </div>

          <fieldset className="space-y-2">
            <legend className="mb-1 block text-sm text-slate-300">故事来源</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {STORY_SOURCES.map((source) => {
                const active = storySource === source.value;
                return (
                  <button
                    key={source.value}
                    type="button"
                    onClick={() => setStorySource(active ? "" : source.value)}
                    aria-pressed={active}
                    className={`rounded-lg border p-3 text-left transition-colors ${
                      active
                        ? "border-brand-500 bg-brand-500/10"
                        : "border-ink-600 hover:border-ink-600/80 hover:bg-ink-850"
                    }`}
                  >
                    <span
                      className={`block text-sm ${active ? "text-brand-400" : "text-slate-300"}`}
                    >
                      {source.label}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-500">
                      {source.hint}
                    </span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <div className="space-y-1.5">
            <label htmlFor="story" className="block text-sm text-slate-300">
              故事内容
            </label>
            <textarea
              id="story"
              rows={8}
              maxLength={200000}
              value={storyText}
              onChange={(event) => setStoryText(event.target.value)}
              placeholder="一个年轻人意外重生回大学时代，决定改变自己的人生……"
              className="w-full resize-y rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 font-mono
                text-xs leading-relaxed text-slate-200 placeholder:text-slate-600
                focus:border-brand-500 focus:outline-none"
            />
            <div className="flex items-center justify-between text-[11px]">
              <span className={storyMissingSource ? "text-rose-400" : "text-slate-500"}>
                {storyMissingSource ? "填写了故事内容，请先选择故事来源" : "支持最多 20 万字符"}
              </span>
              <span className="font-mono text-slate-600">{storyText.length} 字符</span>
            </div>
          </div>

          <p className="rounded-lg border border-ink-700 bg-ink-850/60 p-3 text-[11px] leading-relaxed text-slate-500">
            Phase 2 只做保存，不会调用 AI 解析。故事解析（Story Bible / 人物 / 场景）属于 Phase 3。
          </p>
        </section>

        <FormError error={error} />

        <div className="flex items-center justify-end gap-3">
          <Link href="/" className="btn-ghost">
            取消
          </Link>
          <button type="submit" className="btn-primary" disabled={!canSubmit}>
            {submitting ? "创建中…" : "创建项目"}
          </button>
        </div>
      </form>
    </div>
  );
}
