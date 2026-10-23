import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/test/render";
import type { Client } from "@/lib/types";
import { ClientFormDialog } from "./ClientFormDialog";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const existing: Client = {
  id: "c1",
  code: "CL-1",
  name: "PT Lama",
  client_type: "company",
  tax_id: null,
  email: null,
  phone: null,
  address: null,
  city: "Bogor",
  contact_person: null,
  notes: null,
  is_active: true,
  version: 3,
  created_at: "2026-10-18T00:00:00Z",
  updated_at: "2026-10-18T00:00:00Z",
};

describe("ClientFormDialog", () => {
  it("creates a client, sending blanks as null and no is_active", async () => {
    const onClose = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue(respond(201, { ...existing, name: "PT Baru" }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithQuery(<ClientFormDialog client={null} open onClose={onClose} />);

    await userEvent.type(screen.getByLabelText(/nama klien/i), "PT Baru");
    await userEvent.click(screen.getByRole("button", { name: "Tambah klien" }));

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/clients");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({ name: "PT Baru", client_type: "company", code: null, email: null });
    expect(body).not.toHaveProperty("is_active");
  });

  it("blocks invalid NPWP on the client side", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithQuery(<ClientFormDialog client={null} open onClose={vi.fn()} />);

    await userEvent.type(screen.getByLabelText(/nama klien/i), "PT X");
    await userEvent.type(screen.getByLabelText("NPWP"), "123");
    await userEvent.click(screen.getByRole("button", { name: "Tambah klien" }));

    expect(await screen.findByText("NPWP harus terdiri dari 15 atau 16 digit.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("edits with the last-read version and surfaces conflicts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(409, {
          error: {
            code: "version_conflict",
            message: "Data telah diubah oleh pengguna lain. Muat ulang lalu ulangi perubahan Anda.",
            details: { current_version: 4 },
            request_id: null,
          },
        }),
      ),
    );
    const onClose = vi.fn();
    renderWithQuery(<ClientFormDialog client={existing} open onClose={onClose} />);

    expect(screen.getByLabelText(/nama klien/i)).toHaveValue("PT Lama");
    await userEvent.click(screen.getByRole("button", { name: "Simpan perubahan" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("diubah oleh pengguna lain");
    expect(onClose).not.toHaveBeenCalled();
    const body = JSON.parse((vi.mocked(fetch).mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ version: 3, is_active: true, city: "Bogor" });
  });
});
