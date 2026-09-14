"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type HealthState =
  | { kind: "loading" }
  | { kind: "up"; version: string; latencyMs: number }
  | { kind: "degraded"; version: string; detail: string }
  | { kind: "down"; detail: string };

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

/**
 * Phase 1 acceptance surface: proves the browser can reach the FastAPI backend
 * through the unified response envelope, and surfaces failures honestly instead
 * of silently rendering an empty page.
 */
export default function HomePage() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function probe() {
      const started = performance.now();
      try {
        const response = await fetch(`${API_BASE_URL}/health/detail`, {
          signal: controller.signal,
          cache: "no-store",
        });
        const latencyMs = Math.round(performance.now() - started);
        const body = await response.json();

        if (!response.ok || body?.success !== true) {
          setHealth({
            kind: "down",
            detail: body?.error?.message ?? `HTTP ${response.status}`,
          });
          return;
        }

        const status: string = body.data?.status ?? "unknown";
        if (status === "ok") {
          setHealth({ kind: "up", version: body.data.version, latencyMs });
        } else {
          const unhealthy = (body.data.components ?? [])
            .filter((component: { status: string }) => component.status !== "up")
            .map((component: { name: string; status: string }) => `${component.name}=${component.status}`)
            .join(", ");
          setHealth({
            kind: "degraded",
            version: body.data.version,
            detail: unhealthy || "unknown",
          });
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setHealth({
          kind: "down",
          detail: error instanceof Error ? error.message : "network error",
        });
      }
    }

    void probe();
    return () => controller.abort();
  }, []);

  return (
    <div className="space-y-10">
      <section className="space-y-5">
        <span className="badge border-ink-600 bg-ink-850 text-slate-400">
          Phase 1 · 工程基础
        </span>
        <h1 className="text-4xl font-semibold leading-tight text-white sm:text-5xl">
          从一段故事，
          <br className="hidden sm:block" />
          到一集成片。
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-slate-400">
          AI Studio 是一条 <span className="text-slate-200">AI 漫剧生产流水线</span>：
          故事 → 剧本 → 分镜 → 图片 → 视频 → 配音 → 字幕 → FFmpeg 合成 MP4。
          第一版目标是端到端跑通并可演示，而不是功能堆砌。
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" disabled title="Phase 2 实现">
            创建项目
            <span className="text-xs opacity-70">(Phase 2)</span>
          </button>
          <a className="btn-ghost" href={`${API_BASE_URL}/../docs`} target="_blank" rel="noreferrer">
            API 文档
          </a>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <BackendStatusCard health={health} />
        <PipelineCard />
      </section>

      <section className="space-y-3">
        <div className="flex items-end justify-between">
          <h2 className="text-lg font-medium text-white">我的项目</h2>
          <span className="label-caps">{"项目列表 · Phase 2"}</span>
        </div>
        <div className="panel flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
          <p className="text-sm text-slate-400">还没有项目</p>
          <p className="max-w-md text-xs leading-relaxed text-slate-500">
            项目 CRUD、故事输入与 Story Bible 展示将在 Phase 2 / Phase 3 接入。
            Phase 1 只交付可运行的工程底座：数据库、迁移、统一响应、request_id、健康检查。
          </p>
          <Link className="mt-2 text-xs text-brand-400 hover:text-brand-500" href="#pipeline">
            查看流水线进度 ↓
          </Link>
        </div>
      </section>
    </div>
  );
}

function BackendStatusCard({ health }: { health: HealthState }) {
  const tone =
    health.kind === "up"
      ? "border-accent-500/40 bg-accent-500/10 text-accent-400"
      : health.kind === "degraded"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
        : health.kind === "down"
          ? "border-rose-500/40 bg-rose-500/10 text-rose-400"
          : "border-ink-600 bg-ink-850 text-slate-400";

  const text =
    health.kind === "loading"
      ? "检查中…"
      : health.kind === "up"
        ? "后端正常"
        : health.kind === "degraded"
          ? "部分依赖不可用"
          : "后端不可达";

  return (
    <div className="panel p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-slate-200">后端连通性</h3>
        <span className={`badge ${tone}`}>
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          {text}
        </span>
      </div>

      <dl className="mt-4 space-y-2 font-mono text-xs text-slate-400">
        <div className="flex justify-between gap-4">
          <dt className="text-slate-500">endpoint</dt>
          <dd className="truncate">{API_BASE_URL}/health/detail</dd>
        </div>
        {health.kind === "up" || health.kind === "degraded" ? (
          <>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">version</dt>
              <dd>{health.version}</dd>
            </div>
            {health.kind === "up" ? (
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">latency</dt>
                <dd>{health.latencyMs} ms</dd>
              </div>
            ) : (
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">unhealthy</dt>
                <dd className="text-amber-400">{health.detail}</dd>
              </div>
            )}
          </>
        ) : null}
        {health.kind === "down" ? (
          <div className="flex flex-col gap-1">
            <dt className="text-slate-500">error</dt>
            <dd className="whitespace-pre-wrap break-words text-rose-400">{health.detail}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

const PIPELINE = [
  { label: "Story → Script", done: false },
  { label: "Storyboard", done: false },
  { label: "Image", done: false },
  { label: "Video", done: false },
  { label: "TTS", done: false },
  { label: "Compose (FFmpeg)", done: false },
];

function PipelineCard() {
  return (
    <div id="pipeline" className="panel p-5">
      <h3 className="text-sm font-medium text-slate-200">生产流水线</h3>
      <ul className="mt-4 space-y-2 text-xs">
        {PIPELINE.map((step) => (
          <li key={step.label} className="flex items-center justify-between gap-4">
            <span className="text-slate-400">{step.label}</span>
            <span className="badge border-ink-600 bg-ink-850 text-slate-500">
              {step.done ? "完成" : "待开发"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
