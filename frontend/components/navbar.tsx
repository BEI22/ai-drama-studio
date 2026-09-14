"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

const NAV_ITEMS = [
  { href: "/", label: "项目" },
  { href: "/#", label: "素材", disabled: true },
  { href: "/#", label: "任务", disabled: true },
];

export function Navbar() {
  const { user, initializing, logout } = useAuth();
  const pathname = usePathname();

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
          <span className="block text-sm font-semibold tracking-wide text-white">AI STUDIO</span>
          <span className="block text-[11px] text-slate-500">AI 漫剧自动创作平台</span>
        </span>
      </Link>

      <nav className="flex items-center gap-1 text-sm">
        {NAV_ITEMS.map((item) => {
          const active = item.href === pathname;
          if (item.disabled) {
            return (
              <span
                key={item.label}
                className="cursor-not-allowed rounded-lg px-3 py-1.5 text-slate-600"
                title="后续阶段实现"
              >
                {item.label}
              </span>
            );
          }
          return (
            <Link
              key={item.label}
              href={item.href}
              className={`rounded-lg px-3 py-1.5 transition-colors ${
                active ? "bg-ink-800 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {item.label}
            </Link>
          );
        })}

        {initializing ? (
          <span className="skeleton ml-2 h-7 w-20" />
        ) : user ? (
          <div className="ml-2 flex items-center gap-2">
            <span
              className="badge max-w-[14rem] truncate border-ink-600 bg-ink-850 text-slate-300"
              title={user.email}
            >
              {user.email}
            </span>
            <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={logout}>
              退出
            </button>
          </div>
        ) : (
          <Link href="/login" className="btn-primary ml-2 px-3 py-1.5 text-xs">
            登录 / 注册
          </Link>
        )}
      </nav>
    </header>
  );
}
