/**
 * pdf.js, loaded only in the browser and only when a preview opens (it is large). Browsers
 * without a built-in PDF viewer (Android, in-app browsers) download PDFs instead of showing them;
 * drawing the pages ourselves makes the preview work everywhere.
 *
 * The worker module is imported like any other module and handed to pdf.js as `pdfjsWorker`, so
 * parsing runs on the main thread. A separate Worker built from `new URL(..., import.meta.url)`
 * kept the dev server's Fast Refresh reloading the page in a loop; our documents are a few pages,
 * so the main thread is fast enough.
 */
type PdfJs = typeof import("pdfjs-dist");

let loading: Promise<PdfJs> | null = null;

export function loadPdfJs(): Promise<PdfJs> {
  loading ??= Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs"),
  ]).then(([pdfjs, worker]) => {
    (globalThis as { pdfjsWorker?: unknown }).pdfjsWorker = worker;
    return pdfjs;
  });
  return loading;
}

/** The PDF bytes, or the API's own error message (JSON envelope) when the request fails. */
export async function fetchPdf(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Tidak dapat terhubung ke server.");
  }
  if (!response.ok) {
    let message = `Server mengembalikan status ${response.status}.`;
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      // not JSON: keep the status message
    }
    throw new Error(message);
  }
  return response.arrayBuffer();
}
