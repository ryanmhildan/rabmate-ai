import { describe, expect, it, vi } from "vitest";
import { ApiError, UNAUTHENTICATED_EVENT, api, apiFetch, getHealth, queryString } from "./api";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function sentHeaders(fetchMock: ReturnType<typeof vi.fn>): Headers {
  return fetchMock.mock.calls[0][1].headers as Headers;
}

describe("apiFetch", () => {
  it("calls the versioned same-origin API and returns JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/health/live")).resolves.toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/health/live",
      expect.objectContaining({ credentials: "same-origin", method: "GET" }),
    );
  });

  it("echoes the CSRF cookie on mutations only", async () => {
    document.cookie = "rabmate_csrf=token-123; path=/";
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(200, {})));
    vi.stubGlobal("fetch", fetchMock);

    await api.post("/clients", { name: "A" });
    await api.get("/clients");

    const post = fetchMock.mock.calls[0][1];
    expect((post.headers as Headers).get("X-CSRF-Token")).toBe("token-123");
    expect((post.headers as Headers).get("Content-Type")).toBe("application/json");
    expect(post.body).toBe(JSON.stringify({ name: "A" }));
    expect((fetchMock.mock.calls[1][1].headers as Headers).has("X-CSRF-Token")).toBe(false);
  });

  it("returns undefined for 204 responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.delete("/clients/1")).resolves.toBeUndefined();
    expect(sentHeaders(fetchMock).get("Accept")).toBe("application/json");
  });

  it("raises ApiError with the backend error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(404, {
          error: { code: "not_found", message: "Data tidak ditemukan.", details: null, request_id: "r1" },
        }),
      ),
    );

    const error = await apiFetch("/projects/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      message: "Data tidak ditemukan.",
      requestId: "r1",
    });
  });

  it("maps 422 details to field errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          error: {
            code: "validation_error",
            message: "Data yang dikirim tidak valid.",
            details: [
              { loc: ["body", "tax_id"], msg: "Value error, NPWP harus terdiri dari 15 atau 16 digit." },
              { loc: ["query", "page"], msg: "x" },
            ],
            request_id: null,
          },
        }),
      ),
    );

    const error = (await api.post("/clients", {}).catch((e: unknown) => e)) as ApiError;
    expect(error.fieldErrors()).toEqual({ tax_id: "NPWP harus terdiri dari 15 atau 16 digit." });
  });

  it("announces lost sessions so the app can redirect to login", async () => {
    const listener = vi.fn();
    window.addEventListener(UNAUTHENTICATED_EVENT, listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(401, {
          error: { code: "unauthenticated", message: "Sesi berakhir", details: null, request_id: null },
        }),
      ),
    );

    await expect(api.get("/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHENTICATED_EVENT, listener);
  });

  it("does not treat wrong credentials as a lost session", async () => {
    const listener = vi.fn();
    window.addEventListener(UNAUTHENTICATED_EVENT, listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(401, {
          error: { code: "invalid_credentials", message: "Salah", details: null, request_id: null },
        }),
      ),
    );

    await expect(api.post("/auth/login", {})).rejects.toMatchObject({ code: "invalid_credentials" });
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(UNAUTHENTICATED_EVENT, listener);
  });

  it("handles non-JSON error bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>Bad gateway</html>", { status: 502, headers: { "X-Request-ID": "r2" } }),
      ),
    );

    await expect(apiFetch("/x")).rejects.toMatchObject({
      status: 502,
      code: "http_error",
      requestId: "r2",
    });
  });

  it("maps network failures to a readable error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});

describe("queryString", () => {
  it("skips empty values and encodes the rest", () => {
    expect(queryString({ q: "pt & co", page: 2, status: "", x: null, y: undefined })).toBe(
      "?q=pt+%26+co&page=2",
    );
    expect(queryString({})).toBe("");
  });
});

describe("getHealth", () => {
  it("treats a 503 degraded body as data, not an exception", async () => {
    const degraded = {
      status: "degraded",
      version: "0.1.0",
      environment: "development",
      time: "2026-10-18T20:00:00+07:00",
      database: "error",
      ai: "disabled",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, degraded)));

    await expect(getHealth()).resolves.toEqual(degraded);
  });
});
