/**
 * Client-side session storage.
 *
 * The access token lives in ``localStorage`` and is sent as
 * ``Authorization: Bearer <token>``.
 *
 * KNOWN LIMITATION (Phase 2): ``localStorage`` is readable by any script on the
 * origin, so an XSS bug would leak the token. httpOnly cookies are the correct
 * long-term answer and are tracked as a follow-up -- see docs/TDD.md §15.
 */

const TOKEN_KEY = "ai_studio.access_token";
const USER_KEY = "ai_studio.user";

export interface SessionUser {
  id: string;
  email: string;
  created_at: string;
}

export interface Session {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: SessionUser;
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function getToken(): string | null {
  if (!isBrowser()) return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredUser(): SessionUser | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as SessionUser) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(TOKEN_KEY, session.access_token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(session.user));
  } catch {
    /* storage disabled (private mode / quota) -- user simply stays logged out */
  }
}

export function saveUser(user: SessionUser): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* ignore */
  }
}

export function clearSession(): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

/** Broadcast so any mounted provider can drop its in-memory user. */
export const UNAUTHORIZED_EVENT = "ai-studio:unauthorized";

export function notifyUnauthorized(): void {
  if (!isBrowser()) return;
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}
