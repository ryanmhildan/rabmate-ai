// Thin client for the FastAPI backend, reached through the same-origin /api rewrite.

export const API_BASE = "/api/v1";
export const CSRF_COOKIE = "rabmate_csrf";
export const UNAUTHENTICATED_EVENT = "rabmate:unauthenticated";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type ErrorBody = {
  code: string;
  message: string;
  details: unknown;
  request_id: string | null;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.requestId = body.request_id;
  }

  /** Field-level messages from a 422 response, keyed by body field name. */
  fieldErrors(): Record<string, string> {
    if (!Array.isArray(this.details)) return {};
    const result: Record<string, string> = {};
    for (const item of this.details) {
      if (typeof item !== "object" || item === null) continue;
      const { loc, msg } = item as { loc?: unknown; msg?: unknown };
      if (Array.isArray(loc) && loc[0] === "body" && typeof loc[1] === "string") {
        result[loc[1]] = typeof msg === "string" ? cleanPydanticMessage(msg) : this.message;
      }
    }
    return result;
  }
}

/** Pydantic prefixes custom messages with "Value error, ". */
function cleanPydanticMessage(message: string): string {
  return message.replace(/^Value error, /, "");
}

const NETWORK_ERROR: ErrorBody = {
  code: "network_error",
  message: "Tidak dapat terhubung ke server. Periksa apakah API berjalan.",
  details: null,
  request_id: null,
};

function isErrorEnvelope(value: unknown): value is { error: ErrorBody } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as ErrorBody).code === "string" &&
    typeof (error as ErrorBody).message === "string"
  );
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return null;
}

export type ApiInit = Omit<RequestInit, "body"> & {
  /** Serialised as JSON with the matching Content-Type. */
  json?: unknown;
  body?: BodyInit | null;
  /** Non-2xx statuses whose body should be returned as data (e.g. health 503). */
  acceptStatuses?: number[];
};

/** Fetches `${API_BASE}${path}`. Mutations automatically carry the CSRF header. */
export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { acceptStatuses = [], headers, json, body, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const finalHeaders = new Headers(headers);
  finalHeaders.set("Accept", "application/json");

  let payload = body;
  if (json !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    payload = JSON.stringify(json);
  }
  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) finalHeaders.set("X-CSRF-Token", csrf);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: "same-origin",
      ...rest,
      method,
      headers: finalHeaders,
      body: payload,
    });
  } catch {
    throw new ApiError(0, NETWORK_ERROR);
  }

  if (response.status === 204) return undefined as T;
  const data = await readJson(response);
  if (response.ok || acceptStatuses.includes(response.status)) {
    return data as T;
  }
  if (isErrorEnvelope(data)) {
    if (data.error.code === "unauthenticated" && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT));
    }
    throw new ApiError(response.status, data.error);
  }
  throw new ApiError(response.status, {
    code: "http_error",
    message: `Server mengembalikan status ${response.status}.`,
    details: null,
    request_id: response.headers.get("X-Request-ID"),
  });
}

export const api = {
  get: <T>(path: string, init?: ApiInit) => apiFetch<T>(path, init),
  post: <T>(path: string, json?: unknown) => apiFetch<T>(path, { method: "POST", json }),
  put: <T>(path: string, json?: unknown) => apiFetch<T>(path, { method: "PUT", json }),
  patch: <T>(path: string, json?: unknown) => apiFetch<T>(path, { method: "PATCH", json }),
  delete: <T = void>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};

/** Builds `?a=1&b=2`, skipping empty values. */
export function queryString(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Terjadi kesalahan tak terduga.";
}

export type ComponentStatus = "ok" | "error" | "disabled";

export type HealthResponse = {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  time: string;
  database: ComponentStatus;
  ai: ComponentStatus;
};

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health", { signal, acceptStatuses: [503] });
}
