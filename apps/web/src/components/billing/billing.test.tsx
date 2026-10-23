import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Invoice, PaymentTerm } from "@/lib/types";
import { WorkflowButtons } from "./DocWorkflow";
import { invoiceFormSchema, invoicePayload } from "./InvoiceDetail";
import { RecordPaymentDialog, paymentPayload, paymentSchema } from "./RecordPaymentDialog";
import { TermsEditor, rowsFrom, termsPayload, validateRows } from "./TermsEditor";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("TermsEditor", () => {
  it("fills presets and sends values as strings for the server to compute", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<TermsEditor initial={[]} onSave={onSave} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "50/50" }));
    expect(screen.getAllByRole("group")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "30/40/30" }));
    await user.type(screen.getByLabelText("Jatuh tempo termin 1"), "2026-11-01");
    await user.click(screen.getByRole("button", { name: "Simpan jadwal" }));

    await vi.waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toEqual([
      { name: "Uang muka", basis: "percent", value: "30", due_date: "2026-11-01", description: null },
      { name: "Termin 2", basis: "percent", value: "40", due_date: null, description: null },
      { name: "Pelunasan", basis: "percent", value: "30", due_date: null, description: null },
    ]);
  });

  it("shows the server's refusal", async () => {
    const { ApiError } = await import("@/lib/api");
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(422, { code: "validation_error", message: "Total persentase termin harus 100% (saat ini 90%).", details: null, request_id: null }),
    );
    render(<TermsEditor initial={[]} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Simpan jadwal" }));
    expect(await screen.findByText(/saat ini 90%/)).toBeInTheDocument();
  });

  it("validates rows before calling the server", () => {
    expect(validateRows([])).toMatch(/minimal satu/);
    expect(validateRows([{ name: "A", basis: "percent", value: "120", due_date: "", description: "" }])).toMatch(/maks. 100/);
    expect(validateRows([{ name: "A", basis: "amount", value: "1.500.000", due_date: "", description: "" }])).toBeNull();
    expect(validateRows([{ name: "A", basis: "amount", value: "1,500.00", due_date: "", description: "" }])).toMatch(/1.500.000/);
    expect(termsPayload([{ name: "A", basis: "amount", value: "1.500.000,50", due_date: "", description: "" }])[0]?.value).toBe(
      "1500000.50",
    );
    expect(validateRows([{ name: " ", basis: "amount", value: "1", due_date: "", description: "" }])).toMatch(/nama wajib/);
  });

  it("maps stored terms back to editable rows", () => {
    const term = (overrides: Partial<PaymentTerm>): PaymentTerm => ({
      id: "t", position: 1, name: "DP", basis: "percent", percent: "30.00", amount: "3000000.00",
      tax_amount: "330000.00", total_amount: "3330000.00", due_date: null, description: null, invoice: null, ...overrides,
    });
    expect(rowsFrom([term({}), term({ basis: "amount", percent: null, amount: "2500000.50" })]).map((r) => r.value)).toEqual(["30", "2500000.5"]);
    expect(termsPayload([{ name: " X ", basis: "amount", value: " 5 ", due_date: "", description: " " }])).toEqual([
      { name: "X", basis: "amount", value: "5", due_date: null, description: null },
    ]);
  });
});

function invoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: "inv1", number: "INV-2026-0001", kind: "term", status: "issued", title: "Uang muka",
    project: { id: "p", number: "PRJ-1", name: "Proyek" }, client: { id: "c1", number: null, name: "CV Klien" },
    quotation: { id: "q", number: "PNW-2026-0001" }, issue_date: "2026-10-19", due_date: "2026-11-02",
    currency: "IDR", grand_total: "3233929.50", amount_paid: "0.00", outstanding: "3233929.50",
    payment_state: "unpaid", overdue: false, created_at: "2026-10-19T00:00:00Z",
    payment_term: { id: "t1", name: "Uang muka", percent: "30.00" }, tax_label: "PPN", tax_rate_percent: "11.00",
    subtotal: "2913450.00", tax_amount: "320479.50", notes: null, items: [], allocations: [],
    submitted_by: null, submitted_at: null, decided_by: null, decided_at: null, voided_at: null, void_reason: null,
    version: 4, approvals: [], allowed_actions: [], editable: false, lines_editable: false,
    can_issue: false, can_void: false, can_delete: false, can_record_payment: true,
    ...overrides,
  };
}

describe("RecordPaymentDialog", () => {
  it("allocates the payment to this invoice and retries with the same key", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValueOnce(json(201, { id: "pay1", amount: "1000000.00", currency: "IDR" }));
    vi.stubGlobal("fetch", fetchMock);
    const onRecorded = vi.fn();
    render(<RecordPaymentDialog invoice={invoice()} onClose={vi.fn()} onRecorded={onRecorded} />);
    const user = userEvent.setup();
    const amount = screen.getByLabelText(/^jumlah/i);
    expect(amount).toHaveValue("3233929.5"); // defaults to the outstanding balance
    await user.clear(amount);
    await user.type(amount, "1000000");
    await user.type(screen.getByLabelText(/referensi/i), "TRF-77");

    await user.click(screen.getByRole("button", { name: "Catat pembayaran" }));
    expect(await screen.findByText(/Tidak dapat terhubung/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Catat pembayaran" }));
    await vi.waitFor(() => expect(onRecorded).toHaveBeenCalled());

    const calls = fetchMock.mock.calls.map(([url, init]) => ({
      url: String(url),
      key: new Headers((init as RequestInit).headers).get("Idempotency-Key"),
      body: JSON.parse((init as RequestInit).body as string),
    }));
    expect(calls[0].url).toBe("/api/v1/payments");
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[0].body).toMatchObject({
      client_id: "c1",
      amount: "1000000",
      currency: "IDR",
      method: "transfer",
      reference: "TRF-77",
      allocations: [{ invoice_id: "inv1", amount: "1000000" }],
    });
  });

  it("rejects ambiguous or future values before sending", () => {
    const base = { amount: "1000", payment_date: "2026-01-01", method: "cash" as const, reference: "", notes: "" };
    expect(paymentSchema.safeParse(base).success).toBe(true);
    expect(paymentSchema.parse({ ...base, amount: "1.500.000" }).amount).toBe("1500000"); // unambiguous
    expect(paymentSchema.safeParse({ ...base, amount: "1,500.00" }).success).toBe(false);
    expect(paymentSchema.safeParse({ ...base, amount: "0" }).success).toBe(false);
    expect(paymentSchema.safeParse({ ...base, payment_date: "2999-01-01" }).success).toBe(false);
    expect(paymentPayload(invoice(), { ...base, notes: " " })).toMatchObject({ notes: null, reference: null });
  });
});

describe("invoice editing", () => {
  const values = {
    title: "Jasa",
    due_date: "",
    notes: "",
    tax_label: "PPN",
    tax_rate_percent: "11",
    items: [{ description: " Konsultasi ", quantity: "1", unit: "ls ", unit_price: "1000000" }],
  };

  it("sends lines and tax only for manual invoices", () => {
    const manual = invoicePayload(invoice({ kind: "manual", lines_editable: true, version: 2 }), values);
    expect(manual).toMatchObject({ version: 2, due_date: null, tax_rate_percent: "11", items: [{ description: "Konsultasi", unit: "ls" }] });
    const term = invoicePayload(invoice({ lines_editable: false }), values);
    expect(term).not.toHaveProperty("items");
    expect(term).toMatchObject({ tax_label: "PPN", tax_rate_percent: "11.00" }); // unchanged from the invoice
  });

  it("validates line decimals and paired tax fields", () => {
    expect(invoiceFormSchema.safeParse(values).success).toBe(true);
    expect(invoiceFormSchema.safeParse({ ...values, tax_rate_percent: "" }).success).toBe(false);
    const bad = { ...values, items: [{ ...values.items[0], unit_price: "95.000" }] };
    expect(invoiceFormSchema.safeParse(bad).success).toBe(false); // ambiguous thousands
  });
});

describe("WorkflowButtons", () => {
  it("requires a reason to reject and posts the transition", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { id: "x", status: "rejected" }));
    vi.stubGlobal("fetch", fetchMock);
    const onDone = vi.fn();
    render(<WorkflowButtons base="/invoices/inv1" actions={["approve", "reject"]} onDone={onDone} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Tolak" }));
    await user.click(screen.getAllByRole("button", { name: "Tolak" }).at(-1)!);
    expect(await screen.findByText("Alasan wajib diisi.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/alasan/i), "Nilai salah");
    await user.click(screen.getAllByRole("button", { name: "Tolak" }).at(-1)!);
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/invoices/inv1/transitions/reject");
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({ note: "Nilai salah" });
  });
});
