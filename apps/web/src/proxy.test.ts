import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { proxy } from "./proxy";

function request(path: string, cookie?: string) {
  return new NextRequest(new URL(path, "http://localhost:3000"), {
    headers: cookie ? { cookie } : {},
  });
}

describe("proxy", () => {
  it("sends visitors without a session cookie to /login with the target", () => {
    const response = proxy(request("/proyek/abc?tab=x"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login?next=%2Fproyek%2Fabc%3Ftab%3Dx",
    );
  });

  it("does not add a next parameter for the home page", () => {
    expect(proxy(request("/")).headers.get("location")).toBe("http://localhost:3000/login");
  });

  it("lets requests with a session cookie through (validity is checked by the API)", () => {
    const response = proxy(request("/proyek", "rabmate_session=abc"));
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
