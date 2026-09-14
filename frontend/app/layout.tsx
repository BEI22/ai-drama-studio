import type { Metadata } from "next";

import { Navbar } from "@/components/navbar";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Studio — AI 漫剧自动创作平台",
  description:
    "输入故事，自动生成剧本、分镜、图片、视频、配音与字幕，最终合成一集 AI 漫剧。",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-full font-sans">
        <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-5 sm:px-8">
          <Navbar />
          <main className="flex-1 pb-20 pt-8">{children}</main>
          <footer className="border-t border-ink-800 py-6 text-xs text-slate-500">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>AI Studio V1.0 · Phase 1 工程基础</span>
              <span className="font-mono">
                API{" "}
                <a
                  className="text-slate-400 underline decoration-dotted hover:text-slate-200"
                  href={`${apiBaseUrl()}/../docs`}
                  target="_blank"
                  rel="noreferrer"
                >
                  /docs
                </a>
              </span>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}

function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}
