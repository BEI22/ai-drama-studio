"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { FormError } from "@/components/states";
import { ApiError } from "@/lib/api";

type Mode = "login" | "register";

const COPY: Record<Mode, { title: string; subtitle: string; submit: string; switchText: string }> = {
  login: {
    title: "登录",
    subtitle: "继续你的 AI 漫剧生产流水线。",
    submit: "登录",
    switchText: "还没有账号？去注册",
  },
  register: {
    title: "注册",
    subtitle: "创建账号，开始把故事变成成片。",
    submit: "注册并进入",
    switchText: "已有账号？去登录",
  },
};

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, register, user, initializing } = useAuth();

  const [mode, setMode] = useState<Mode>(
    searchParams.get("mode") === "register" ? "register" : "login",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const next = searchParams.get("next") || "/";

  // Already signed in: don't make the user stare at a login form.
  useEffect(() => {
    if (!initializing && user) router.replace(next);
  }, [initializing, user, router, next]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
      router.replace(next);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("登录失败，请重试", {
              code: "UNKNOWN",
              status: 0,
              requestId: null,
            }),
      );
    } finally {
      setSubmitting(false);
    }
  }

  const copy = COPY[mode];

  return (
    <div className="mx-auto w-full max-w-md">
      <div className="mb-6 space-y-1">
        <span className="badge border-ink-600 bg-ink-850 text-slate-400">Phase 2 · 账号</span>
        <h1 className="pt-2 text-2xl font-semibold text-white">{copy.title}</h1>
        <p className="text-sm text-slate-400">{copy.subtitle}</p>
      </div>

      <form onSubmit={handleSubmit} className="panel space-y-4 p-6" noValidate>
        <div className="space-y-1.5">
          <label htmlFor="email" className="label-caps block">
            邮箱
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-slate-200
              placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="password" className="label-caps block">
            密码
          </label>
          <input
            id="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="至少 8 位，含字母和数字"
            className="w-full rounded-lg border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-slate-200
              placeholder:text-slate-600 focus:border-brand-500 focus:outline-none"
          />
          {mode === "register" ? (
            <p className="text-[11px] text-slate-500">至少 8 位，且需同时包含字母和数字。</p>
          ) : null}
        </div>

        <FormError error={error} />

        <button type="submit" className="btn-primary w-full" disabled={submitting}>
          {submitting ? "处理中…" : copy.submit}
        </button>

        <button
          type="button"
          className="w-full text-center text-xs text-brand-400 hover:text-brand-500"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {copy.switchText}
        </button>
      </form>

      <p className="mt-4 text-center text-xs text-slate-500">
        <Link href="/" className="hover:text-slate-300">
          返回首页
        </Link>
      </p>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <Suspense fallback={<div className="mx-auto w-full max-w-md"><div className="skeleton h-64" /></div>}>
      <LoginForm />
    </Suspense>
  );
}
