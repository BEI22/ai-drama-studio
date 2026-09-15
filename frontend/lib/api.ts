/**
 * Typed API client.
 *
 * Every backend response uses the unified envelope (PRD section 23)::
 *
 *   { success, data, error: { code, message, details? }, request_id, meta? }
 *
 * The client unwraps ``data`` on success and throws an {@link ApiError} carrying
 * the backend error code plus the request id. A 401 additionally clears the
 * stored session and emits ``UNAUTHORIZED_EVENT`` so the UI can react.
 */

import { clearSession, getToken, notifyUnauthorized } from "@/lib/session";
import type {
  AnalysisStatus,
  AnalyzeStatus,
  Character,
  CharacterWriteInput,
  DeletedResult,
  LocationWriteInput,
  StoryBibleResponse,
  StoryLocation,
} from "@/types/api";

// Re-exported so components have a single import site for domain types.
export type {
  AnalysisStatus,
  AnalyzeStatus,
  BibleMeta,
  Character,
  CharacterRole,
  CharacterWriteInput,
  DeletedResult,
  LocationWriteInput,
  StoryBibleContent,
  StoryBibleResponse,
  StoryLocation,
  UsageRecord,
} from "@/types/api";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const REQUEST_ID_HEADER =
  process.env.NEXT_PUBLIC_REQUEST_ID_HEADER ?? "X-Request-ID";

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: ApiErrorBody | null;
  request_id: string | null;
  meta?: Record<string, unknown> | null;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(
    message: string,
    options: { code: string; status: number; requestId: string | null; details?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId;
    this.details = options.details;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** Field-level messages from a 422 VALIDATION_ERROR, if any. */
  get fieldErrors(): { field: string; message: string }[] {
    if (!Array.isArray(this.details)) return [];
    return this.details
      .map((detail: unknown) => {
        const entry = detail as { loc?: unknown[]; msg?: string };
        const loc = Array.isArray(entry?.loc) ? entry.loc : [];
        // FastAPI prefixes the location with "body" / "query" etc.
        const field = loc.filter((part) => part !== "body").join(".");
        return { field, message: entry?.msg ?? "" };
      })
      .filter((item) => item.field || item.message);
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip envelope unwrapping and return the raw parsed JSON. */
  raw?: boolean;
  /** Do not attach the stored bearer token. */
  anonymous?: boolean;
}

/** Perform a request and return the full envelope (needed for ``meta``). */
async function requestEnvelope<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiEnvelope<T>> {
  const { body, anonymous, headers, ...rest } = options;

  const token = anonymous ? null : getToken();

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(headers ?? {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? `无法连接后端：${error.message}` : "无法连接后端",
      { code: "NETWORK_ERROR", status: 0, requestId: null },
    );
  }

  const headerRequestId = response.headers.get(REQUEST_ID_HEADER);

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const envelope = payload as ApiEnvelope<T> | null;

  if (!response.ok || !envelope || envelope.success !== true) {
    // An expired/revoked token must not leave the UI half-logged-in.
    if (response.status === 401 && !anonymous && token) {
      clearSession();
      notifyUnauthorized();
    }

    throw new ApiError(envelope?.error?.message ?? `请求失败（HTTP ${response.status}）`, {
      code: envelope?.error?.code ?? "HTTP_ERROR",
      status: response.status,
      requestId: envelope?.request_id ?? headerRequestId,
      details: envelope?.error?.details,
    });
  }

  return envelope;
}

/** Perform a request and return only ``data``. */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (options.raw) {
    const envelope = await requestEnvelope<T>(path, options);
    return envelope as unknown as T;
  }
  const envelope = await requestEnvelope<T>(path, options);
  return envelope.data as T;
}

// --------------------------------------------------------------------------- types
export interface HealthComponent {
  name: string;
  status: "up" | "down" | "unknown";
  detail?: string | null;
  latency_ms?: number | null;
}

export interface HealthDetail {
  status: string;
  version: string;
  environment: string;
  components: HealthComponent[];
}

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface SessionToken {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export type ProjectStatus = "DRAFT" | "ACTIVE" | "ARCHIVED" | "FAILED";
export type StorySource = "SYNOPSIS" | "NOVEL" | "SCRIPT";

export interface Project {
  id: string;
  name: string;
  genre: string | null;
  style: string | null;
  description: string | null;
  status: ProjectStatus;
  story_source: StorySource | null;
  has_story: boolean;
  episode_count: number;
  // Phase 3: surfaced on the list cards so the dashboard shows Bible progress.
  analysis_status: AnalysisStatus;
  character_count: number;
  location_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectListItem extends Project {}

export interface EpisodeSummary {
  id: string;
  episode_number: number;
  title: string | null;
  summary: string | null;
  duration: number;
  status: string;
}

export interface ProjectDetail extends Project {
  story_text: string | null;
  story_bible_json: Record<string, unknown> | null;
  analysis_error: string | null;
  analyzed_at: string | null;
  episodes: EpisodeSummary[];
}

export interface ProjectListPage {
  items: ProjectListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ProjectCreateInput {
  name: string;
  genre?: string | null;
  style?: string | null;
  description?: string | null;
  story_source?: StorySource | null;
  story_text?: string | null;
}

export interface ProjectUpdateInput {
  name?: string;
  genre?: string | null;
  style?: string | null;
  description?: string | null;
  status?: ProjectStatus;
}

export interface StoryInput {
  story_source: StorySource;
  story_text: string;
}

export interface StoryPayload {
  story_source: StorySource | null;
  story_text: string | null;
  has_story: boolean;
}

export interface ProjectListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  status?: ProjectStatus;
}

// ------------------------------------------------------------------------- client
export const api = {
  // ---------------------------------------------------------------- meta/health
  liveness: () => request<{ status: string }>("/health", { raw: true, anonymous: true }),

  healthDetail: () => request<HealthDetail>("/health/detail", { anonymous: true }),

  // ---------------------------------------------------------------------- auth
  register: (email: string, password: string) =>
    request<SessionToken>("/auth/register", {
      method: "POST",
      body: { email, password },
      anonymous: true,
    }),

  login: (email: string, password: string) =>
    request<SessionToken>("/auth/login", {
      method: "POST",
      body: { email, password },
      anonymous: true,
    }),

  me: () => request<User>("/auth/me"),

  // ------------------------------------------------------------------ projects
  listProjects: async (params: ProjectListParams = {}): Promise<ProjectListPage> => {
    const query = new URLSearchParams();
    if (params.page) query.set("page", String(params.page));
    if (params.pageSize) query.set("page_size", String(params.pageSize));
    if (params.search) query.set("search", params.search);
    if (params.status) query.set("status", params.status);

    const suffix = query.toString() ? `?${query.toString()}` : "";
    const envelope = await requestEnvelope<{ items: ProjectListItem[] }>(`/projects${suffix}`);
    const meta = (envelope.meta ?? {}) as Record<string, number>;

    return {
      items: envelope.data?.items ?? [],
      total: meta.total ?? 0,
      page: meta.page ?? 1,
      page_size: meta.page_size ?? 20,
      pages: meta.pages ?? 0,
    };
  },

  createProject: (input: ProjectCreateInput) =>
    request<ProjectDetail>("/projects", { method: "POST", body: input }),

  getProject: (id: string) => request<ProjectDetail>(`/projects/${id}`),

  updateProject: (id: string, input: ProjectUpdateInput) =>
    request<ProjectDetail>(`/projects/${id}`, { method: "PATCH", body: input }),

  deleteProject: (id: string) =>
    request<{ id: string; deleted: boolean }>(`/projects/${id}`, { method: "DELETE" }),

  getStory: (id: string) => request<StoryPayload>(`/projects/${id}/story`),

  saveStory: (id: string, input: StoryInput) =>
    request<ProjectDetail>(`/projects/${id}/story`, { method: "POST", body: input }),

  clearStory: (id: string) =>
    request<{ id: string; has_story: boolean }>(`/projects/${id}/story`, { method: "DELETE" }),

  // --------------------------------------------------------------- phase 3
  // Story Agent + Story Bible (PRD sections 6-9, 22).

  /** Run the Story Agent. Slow (real LLM calls), so callers should show progress. */
  analyzeProject: (
    id: string,
    input: { story_text?: string; replace?: boolean } = {},
  ) => {
    const query = input.replace ? "?replace=true" : "";
    return request<StoryBibleResponse>(`/projects/${id}/analyze${query}`, {
      method: "POST",
      body: input.story_text ? { story_text: input.story_text } : undefined,
    });
  },

  analyzeStatus: (id: string) => request<AnalyzeStatus>(`/projects/${id}/analyze/status`),

  getBible: (id: string) => request<StoryBibleResponse>(`/projects/${id}/bible`),

  listCharacters: (id: string) =>
    request<Character[]>(`/projects/${id}/characters`),

  createCharacter: (id: string, input: CharacterWriteInput) =>
    request<Character>(`/projects/${id}/characters`, { method: "POST", body: input }),

  updateCharacter: (characterId: string, input: CharacterWriteInput) =>
    request<Character>(`/characters/${characterId}`, { method: "PATCH", body: input }),

  deleteCharacter: (characterId: string) =>
    request<DeletedResult>(`/characters/${characterId}`, { method: "DELETE" }),

  listLocations: (id: string) => request<StoryLocation[]>(`/projects/${id}/locations`),

  createLocation: (id: string, input: LocationWriteInput) =>
    request<StoryLocation>(`/projects/${id}/locations`, { method: "POST", body: input }),

  updateLocation: (locationId: string, input: LocationWriteInput) =>
    request<StoryLocation>(`/locations/${locationId}`, { method: "PATCH", body: input }),

  deleteLocation: (locationId: string) =>
    request<DeletedResult>(`/locations/${locationId}`, { method: "DELETE" }),
};

export type { RequestOptions };
