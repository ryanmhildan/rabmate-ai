import { API_BASE } from "./api";

// Same-origin links: the session cookie authorizes the download; nothing is fetched into JS.

export function previewPdfUrl(rabId: string, versionNo: number): string {
  return `${API_BASE}/rab/${rabId}/versions/${versionNo}/preview.pdf`;
}

export function exportXlsxUrl(rabId: string, versionNo: number): string {
  return `${API_BASE}/rab/${rabId}/versions/${versionNo}/export.xlsx`;
}

export function documentFileUrl(documentId: string, format: "pdf" | "xlsx", download = false): string {
  return `${API_BASE}/documents/${documentId}/files/${format}${download ? "?download=true" : ""}`;
}

export function sourceDocumentFileUrl(documentId: string): string {
  return `${API_BASE}/source-documents/${documentId}/file`;
}

/** "64,3 KB", display only. */
export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  const kb = size / 1024;
  if (kb < 1024) return `${kb.toLocaleString("id-ID", { maximumFractionDigits: 1 })} KB`;
  return `${(kb / 1024).toLocaleString("id-ID", { maximumFractionDigits: 1 })} MB`;
}

/** A fresh key per issue attempt; retries of the same attempt reuse it (server returns the same document). */
export function newIdempotencyKey(): string {
  return `issue-${crypto.randomUUID()}`;
}
