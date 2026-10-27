"use client";

import { Download, ExternalLink, Eye, Loader2, Minus, Plus } from "lucide-react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, buttonClass } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { fetchPdf, loadPdfJs } from "@/lib/pdf";

/** Zoom steps relative to "fit the dialog width". */
export const ZOOMS = [0.75, 1, 1.25, 1.5, 2] as const;

/** `url` with `download=true`, so the server answers with an attachment. */
export function downloadUrlOf(url: string): string {
  return `${url}${url.includes("?") ? "&" : "?"}download=true`;
}

type PreviewProps = {
  url: string;
  title: string;
  label?: ReactNode;
  /** Accessible name when the visible label alone is ambiguous (e.g. "PDF" in a table row). */
  ariaLabel?: string;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
};

/** A button that shows a PDF in a dialog inside the app, whatever the browser can display. */
export function PdfPreviewButton({
  url,
  title,
  label = "Pratinjau PDF",
  ariaLabel,
  variant = "secondary",
  size = "sm",
}: PreviewProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant={variant} size={size} aria-label={ariaLabel} onClick={() => setOpen(true)}>
        <Eye aria-hidden className="size-3.5" />
        {label}
      </Button>
      <PdfPreviewDialog open={open} onClose={() => setOpen(false)} url={url} title={title} />
    </>
  );
}

export function PdfPreviewDialog({
  open,
  onClose,
  url,
  title,
}: {
  open: boolean;
  onClose: () => void;
  url: string;
  title: string;
}) {
  const [zoom, setZoom] = useState<(typeof ZOOMS)[number]>(1);
  const [attempt, setAttempt] = useState(0);
  const [pages, setPages] = useState<number | null>(null);
  const step = ZOOMS.indexOf(zoom);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      size="xl"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1 text-sm text-muted">
            <Button
              variant="ghost"
              size="sm"
              aria-label="Perkecil"
              className="min-w-11 sm:min-w-8"
              disabled={step <= 0}
              onClick={() => setZoom(ZOOMS[step - 1])}
            >
              <Minus aria-hidden className="size-4" />
            </Button>
            <span className="tabular w-12 text-center" aria-live="polite">
              {Math.round(zoom * 100)}%
            </span>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Perbesar"
              className="min-w-11 sm:min-w-8"
              disabled={step >= ZOOMS.length - 1}
              onClick={() => setZoom(ZOOMS[step + 1])}
            >
              <Plus aria-hidden className="size-4" />
            </Button>
            {pages !== null && <span className="ml-2">{pages} halaman</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            {/* For printing from the browser's own viewer, where it has one. */}
            <a href={url} target="_blank" rel="noopener" className={buttonClass({ variant: "ghost", size: "sm" })}>
              <ExternalLink aria-hidden className="size-3.5" />
              Tab baru
            </a>
            <a href={downloadUrlOf(url)} className={buttonClass({ size: "sm" })}>
              <Download aria-hidden className="size-3.5" />
              Unduh PDF
            </a>
          </div>
        </div>
      }
    >
      {open && (
        <PdfViewer
          key={`${url}#${attempt}`}
          url={url}
          zoom={zoom}
          onPages={setPages}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      )}
    </Dialog>
  );
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; doc: PDFDocumentProxy }
  | { status: "error"; message: string };

function PdfViewer({
  url,
  zoom,
  onPages,
  onRetry,
}: {
  url: string;
  zoom: number;
  onPages: (count: number | null) => void;
  onRetry: () => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [width, setWidth] = useState(0);
  const frame = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let loadingTask: PDFDocumentLoadingTask | null = null;
    void (async () => {
      try {
        const [pdfjs, data] = await Promise.all([loadPdfJs(), fetchPdf(url, controller.signal)]);
        if (controller.signal.aborted) return;
        // Errors only: the expected "fake worker" notice would otherwise log on every preview.
        loadingTask = pdfjs.getDocument({ data, verbosity: pdfjs.VerbosityLevel.ERRORS });
        const doc = await loadingTask.promise;
        if (controller.signal.aborted) return;
        setState({ status: "ready", doc });
        onPages(doc.numPages);
      } catch (error) {
        if (controller.signal.aborted) return;
        onPages(null);
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Pratinjau gagal dimuat.",
        });
      }
    })();
    return () => {
      controller.abort();
      // Frees the document and its worker-side data.
      void loadingTask?.destroy();
    };
  }, [url, onPages]);

  // Page width follows the dialog: fit-to-width at 100%, wider (with horizontal scroll) above.
  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const pageWidth = Math.max(0, Math.floor(width * zoom) - 2);

  return (
    <div ref={frame} className="-mx-5 -my-4 min-h-64 bg-surface-muted px-3 py-4 sm:px-5">
      {state.status === "loading" && (
        <p role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Menyiapkan pratinjau…
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="space-y-3 py-12 text-center text-sm">
          <p className="font-medium text-danger">Pratinjau gagal dimuat.</p>
          <p className="text-muted">{state.message}</p>
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Coba lagi
          </Button>
        </div>
      )}
      {state.status === "ready" && pageWidth > 0 && (
        <div className="overflow-x-auto">
          <div className="mx-auto w-max space-y-4">
            {Array.from({ length: state.doc.numPages }, (_, index) => (
              <PdfPage
                key={index}
                doc={state.doc}
                number={index + 1}
                total={state.doc.numPages}
                width={pageWidth}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PdfPage({
  doc,
  number,
  total,
  width,
}: {
  doc: PDFDocumentProxy;
  number: number;
  total: number;
  width: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");
  const [height, setHeight] = useState<number | null>(null);

  // Long documents: draw a page only when it comes near the visible area.
  useEffect(() => {
    if (visible || !holder.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setVisible(true);
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(holder.current);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    const target = canvas.current;
    if (!visible || !target || width <= 0) return;
    let cancelled = false;
    let task: RenderTask | null = null;
    void (async () => {
      const page = await doc.getPage(number);
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const scale = width / base.width;
      // Sharp on high-density screens: draw at device pixels, show at CSS pixels.
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      target.width = Math.floor(viewport.width);
      target.height = Math.floor(viewport.height);
      target.style.width = `${width}px`;
      target.style.height = `${Math.floor(viewport.height / ratio)}px`;
      setHeight(Math.floor(viewport.height / ratio));
      task = page.render({ canvas: target, viewport });
      try {
        await task.promise;
      } catch {
        // cancelled because the zoom changed or the dialog closed
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, number, width, visible]);

  return (
    <div
      ref={holder}
      className="border border-border bg-white"
      style={{ width, height: height ?? Math.round(width * 1.414) }}
    >
      <canvas ref={canvas} role="img" aria-label={`Halaman ${number} dari ${total}`} />
    </div>
  );
}
