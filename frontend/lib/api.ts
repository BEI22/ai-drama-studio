/**
 * Typed API client.
 *
 * Every backend response uses the unified envelope (PRD section 23)::
 *
 *   { success, data, error: { code, message, details? }, request_id }
 *
 * The client unwraps ``data`` on success and throws an {@link ApiError} that
 * carries the backend error code plus the request id for support/debugging.
 */

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

  /** True when the backend was never reached (network/CORS/timeout). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip envelope unwrapping and return the raw parsed JSON. */
  raw?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, raw, headers, ...rest } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
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

  const requestId = response.headers.get(REQUEST_ID_HEADER);

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (raw) {
    return payload as T;
  }

  const envelope = payload as ApiEnvelope<T> | null;

  if (!response.ok || !envelope || envelope.success !== true) {
    const errorBody = envelope?.error ?? null;
    throw new ApiError(
      errorBody?.message ?? `请求失败（HTTP ${response.status}）`,
      {
        code: errorBody?.code ?? "HTTP_ERROR",
        status: response.status,
        requestId: envelope?.request_id ?? requestId,
        details: errorBody?.details,
      },
    );
  }

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

export const api = {
  /** Bare liveness probe — not enveloped (PRD section 31). */
  liveness: () => request<{ status: string }>("/health", { raw: true }),

  /** Readiness probe with dependency status, enveloped. */
  healthDetail: () => request<HealthDetail>("/health/detail"),
};

export type { RequestOptions };
