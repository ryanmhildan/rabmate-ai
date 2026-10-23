import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/test/render";
import { LoginForm } from "./LoginForm";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), next: null as string | null }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => new URLSearchParams(navigation.next ? { next: navigation.next } : {}),
}));

const me = {
  user: { id: "u1", email: "budi@contoh.co.id", full_name: "Budi" },
  organization: { id: "o1", name: "PT Uji" },
  role: "owner",
  role_label: "Owner/Admin",
  permissions: [],
  organizations: [],
};

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function fillAndSubmit(email: string, password: string) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText(/email/i), email);
  if (password) await user.type(screen.getByLabelText(/kata sandi/i), password);
  await user.click(screen.getByRole("button", { name: "Masuk" }));
}

describe("LoginForm", () => {
  it("validates before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithQuery(<LoginForm />);

    await fillAndSubmit("", "");

    expect(await screen.findByText("Email wajib diisi.")).toBeInTheDocument();
    expect(screen.getByText("Kata sandi wajib diisi.")).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the server's generic message on wrong credentials", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(401, {
          error: {
            code: "invalid_credentials",
            message: "Email atau kata sandi salah.",
            details: null,
            request_id: null,
          },
        }),
      ),
    );
    renderWithQuery(<LoginForm />);

    await fillAndSubmit("budi@contoh.co.id", "salah-sandi");

    expect(await screen.findByRole("alert")).toHaveTextContent("Email atau kata sandi salah.");
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("redirects to a safe `next` path after login", async () => {
    navigation.next = "/proyek/abc";
    const fetchMock = vi.fn().mockResolvedValue(respond(200, me));
    vi.stubGlobal("fetch", fetchMock);
    renderWithQuery(<LoginForm />);

    await fillAndSubmit("budi@contoh.co.id", "sandi-yang-benar");

    await vi.waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/proyek/abc"));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      email: "budi@contoh.co.id",
      password: "sandi-yang-benar",
    });
  });

  it("ignores an external `next` target", async () => {
    navigation.next = "https://evil.example/phish";
    navigation.replace.mockClear();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(200, me)));
    renderWithQuery(<LoginForm />);

    await fillAndSubmit("budi@contoh.co.id", "sandi-yang-benar");

    await vi.waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
  });
});
