import { describe, expect, it } from "vitest";
import { loginUrl, safeNextPath } from "./auth";

describe("safeNextPath", () => {
  it.each([
    ["/proyek", "/proyek"],
    ["/proyek/123?tab=a", "/proyek/123?tab=a"],
    [null, "/"],
    ["", "/"],
  ])("keeps same-site path %p", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "proyek"])(
    "rejects open redirect target %p",
    (input) => {
      expect(safeNextPath(input)).toBe("/");
    },
  );
});

describe("loginUrl", () => {
  it("remembers where the user was going", () => {
    expect(loginUrl("/proyek/abc")).toBe("/login?next=%2Fproyek%2Fabc");
    expect(loginUrl("/")).toBe("/login");
  });
});
