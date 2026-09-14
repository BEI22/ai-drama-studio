import Link from "next/link";

export function Navbar() {
  return (
    <header className="flex items-center justify-between border-b border-ink-800 py-5">
      <Link href="/" className="flex items-center gap-3">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-500/15 text-brand-400 ring-1 ring-brand-500/30">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
            <path
              d="M4 5.5h11.5a2.5 2.5 0 0 1 2.5 2.5v0M4 9.5h16M4 13.5h10M4 17.5h7"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
            <circle cx="18.5" cy="16.5" r="2.5" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </span>
        <span className="leading-tight">
          <span className="block text-sm font-semibold tracking-wide text-white">
            AI STUDIO
          </span>
          <span className="block text-[11px] text-slate-500">AI 漫剧自动创作平台</span>
        </span>
      </Link>

      <nav className="flex items-center gap-1 text-sm">
        <span className="rounded-lg px-3 py-1.5 text-slate-400">项目</span>
        <span className="rounded-lg px-3 py-1.5 text-slate-400">素材</span>
        <span className="rounded-lg px-3 py-1.5 text-slate-400">任务</span>
        <span
          className="badge ml-2 border-ink-600 bg-ink-850 text-slate-500"
          title="Phase 2 实现"
        >
          未登录
        </span>
      </nav>
    </header>
  );
}
