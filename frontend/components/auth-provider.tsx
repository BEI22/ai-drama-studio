"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api, ApiError } from "@/lib/api";
import {
  clearSession,
  getStoredUser,
  getToken,
  saveSession,
  saveUser,
  UNAUTHORIZED_EVENT,
  type SessionUser,
} from "@/lib/session";

interface AuthContextValue {
  user: SessionUser | null;
  /** ``true`` until the stored session has been validated against the API. */
  initializing: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [initializing, setInitializing] = useState(true);

  // Validate any stored token once on mount. A stale token is worse than none:
  // it makes every subsequent request fail with 401.
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      if (!getToken()) {
        if (!cancelled) setInitializing(false);
        return;
      }
      // Show the cached user immediately so the shell does not flash.
      setUser(getStoredUser());

      try {
        const fresh = await api.me();
        if (cancelled) return;
        setUser(fresh);
        saveUser(fresh);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.isUnauthorized) {
          clearSession();
          setUser(null);
        }
        // Network errors keep the cached user: the backend may just be down.
      } finally {
        if (!cancelled) setInitializing(false);
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  // The API client emits this when any request comes back 401.
  useEffect(() => {
    function onUnauthorized() {
      setUser(null);
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const session = await api.login(email, password);
    saveSession(session);
    setUser(session.user);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const session = await api.register(email, password);
    saveSession(session);
    setUser(session.user);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    router.push("/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, initializing, login, register, logout }),
    [user, initializing, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 <AuthProvider> 内部使用");
  }
  return context;
}
