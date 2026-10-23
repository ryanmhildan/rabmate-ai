"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Loader2, MessageSquarePlus, Send, Trash2 } from "lucide-react";
import Link from "next/link";
import { Fragment, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { FormError, Select, Textarea } from "@/components/ui/Field";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api, errorMessage } from "@/lib/api";
import { formatTanggalWaktu } from "@/lib/format";
import { AI_STATE } from "@/lib/labels";
import type { AiStatus, ChatMessage, ChatSource, Conversation, ConversationListItem } from "@/lib/types";
import { aiKeys } from "./AiAssistantCard";

export const MAX_QUESTION = 2000;
const ACTIVE = new Set(["queued", "running"]);

export const chatKeys = {
  list: (projectId: string) => ["ai", "conversations", projectId] as const,
  detail: (id: string) => ["ai", "conversation", id] as const,
};

export function questionError(text: string): string | null {
  const value = text.trim();
  if (value.length < 2) return "Tulis pertanyaan Anda.";
  if (value.length > MAX_QUESTION) return `Pertanyaan maksimal ${MAX_QUESTION} karakter.`;
  return null;
}

/** Where a cited source can be opened in the app, if anywhere. */
export function sourceHref(source: ChatSource): string | null {
  if (!source.ref) return null;
  switch (source.ref.type) {
    case "rab":
      return `/rab/${source.ref.id}`;
    case "catalog_item":
      return `/katalog-harga/${source.ref.id}`;
    case "project":
      return `/proyek/${source.ref.id}`;
    default:
      return null;
  }
}

/** The answer text with its [S1]-style citations shown as small markers. */
export function withCitations(text: string): ReactNode[] {
  return text.split(/(\[S\d+(?:,\s*S\d+)*\])/g).map((part, i) =>
    /^\[S\d+(?:,\s*S\d+)*\]$/.test(part) ? (
      <sup key={i} className="mx-0.5 rounded bg-primary/10 px-1 text-[10px] font-medium text-primary">
        {part.slice(1, -1)}
      </sup>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

export function ProjectChat({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const status = useQuery({
    queryKey: aiKeys.status,
    queryFn: ({ signal }) => api.get<AiStatus>("/ai/status", { signal }),
    staleTime: 30_000,
  });
  const conversations = useQuery({
    queryKey: chatKeys.list(projectId),
    queryFn: ({ signal }) => api.get<ConversationListItem[]>(`/projects/${projectId}/ai-conversations`, { signal }),
  });
  const conversation = useQuery({
    queryKey: chatKeys.detail(selected ?? ""),
    queryFn: ({ signal }) => api.get<Conversation>(`/ai-conversations/${selected}`, { signal }),
    enabled: selected !== null,
    // Poll only while the answer is being prepared in the background.
    refetchInterval: (query) => (ACTIVE.has(query.state.data?.latest_run?.status ?? "") ? 2000 : false),
  });

  const send = useMutation({
    mutationFn: (message: string) =>
      selected
        ? api.post<Conversation>(`/ai-conversations/${selected}/messages`, { message })
        : api.post<Conversation>(`/projects/${projectId}/ai-conversations`, { message }),
    onSuccess: (saved) => {
      queryClient.setQueryData(chatKeys.detail(saved.id), saved);
      setSelected(saved.id);
      setQuestion("");
      void queryClient.invalidateQueries({ queryKey: chatKeys.list(projectId) });
    },
    onError: (caught) => setError(errorMessage(caught)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/ai-conversations/${id}`),
    onSuccess: () => {
      toast.success("Percakapan dihapus.");
      setSelected(null);
      setConfirmDelete(false);
      void queryClient.invalidateQueries({ queryKey: chatKeys.list(projectId) });
    },
    onError: (caught) => {
      setConfirmDelete(false);
      toast.error(errorMessage(caught));
    },
  });

  const ready = status.data?.state === "ready";
  const data = selected ? conversation.data : undefined;
  const pending = ACTIVE.has(data?.latest_run?.status ?? "");
  const submit = () => {
    const problem = questionError(question);
    setError(problem);
    if (!problem) send.mutate(question.trim());
  };

  return (
    <Card title="Tanya asisten AI tentang proyek ini">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Bot aria-hidden className="size-4 text-muted" />
        {status.data ? (
          <StatusBadge tone={AI_STATE[status.data.state].tone}>{AI_STATE[status.data.state].label}</StatusBadge>
        ) : status.isError ? (
          <span className="text-danger">{errorMessage(status.error)}</span>
        ) : (
          <span className="text-muted">Memeriksa AI lokal…</span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select
            aria-label="Pilih percakapan"
            className="h-8 w-56 text-xs"
            value={selected ?? ""}
            onChange={(e) => {
              setSelected(e.target.value || null);
              setError(null);
            }}
          >
            <option value="">Percakapan baru</option>
            {conversations.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title} ({formatTanggalWaktu(c.updated_at)})
              </option>
            ))}
          </Select>
          {selected && (
            <>
              <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
                <MessageSquarePlus aria-hidden className="size-3.5" />
                Baru
              </Button>
              <Button size="sm" variant="ghost" aria-label="Hapus percakapan" disabled={pending} onClick={() => setConfirmDelete(true)}>
                <Trash2 aria-hidden className="size-3.5" />
              </Button>
            </>
          )}
        </div>
      </div>
      {status.data && !ready && <p className="text-xs text-muted">{status.data.message}</p>}
      <p className="text-xs text-muted">
        Jawaban disusun model lokal hanya dari data proyek, RAB, dokumen, dan katalog yang boleh Anda lihat, lengkap dengan
        sumbernya. Asisten tidak dapat mengubah data. Percakapan hanya terlihat oleh Anda.
      </p>

      {selected && conversation.isPending && <p className="text-sm text-muted">Memuat percakapan…</p>}
      {selected && conversation.isError && <p className="text-sm text-danger">{errorMessage(conversation.error)}</p>}
      {data && (
        <ol className="space-y-3" aria-label="Isi percakapan">
          {data.messages.map((m) => (
            <li key={m.id}>
              <MessageView message={m} />
            </li>
          ))}
        </ol>
      )}
      {pending && (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Asisten sedang menyusun jawaban dari data proyek…
        </p>
      )}
      {data?.latest_run?.status === "failed" && (
        <p className="flex items-start gap-1.5 text-sm text-danger" role="alert">
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
          Jawaban gagal: {data.latest_run.error_message ?? "kesalahan tidak diketahui."} Anda dapat mengirim ulang pertanyaan.
        </p>
      )}
      {data && data.unavailable.length > 0 && (
        <p className="text-xs text-muted">Tidak termasuk dalam data jawaban terakhir: {data.unavailable.join(" ")}</p>
      )}

      {ready && (
        <div className="space-y-2">
          <FormError message={error} />
          <Textarea
            aria-label="Pertanyaan untuk asisten"
            rows={3}
            maxLength={MAX_QUESTION}
            placeholder="Contoh: Item mana di RAB yang belum punya harga? Berapa harga kabel UTP di katalog?"
            value={question}
            disabled={pending}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted">Ctrl+Enter untuk mengirim</span>
            <Button size="sm" loading={send.isPending} disabled={pending} onClick={submit}>
              <Send aria-hidden className="size-3.5" />
              {pending ? "Menunggu jawaban…" : "Kirim"}
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Hapus percakapan?"
        message="Percakapan ini beserta jawabannya akan dihapus permanen. Data proyek tidak terpengaruh."
        confirmLabel="Hapus percakapan"
        danger
        loading={remove.isPending}
        onConfirm={() => selected && remove.mutate(selected)}
        onClose={() => setConfirmDelete(false)}
      />
    </Card>
  );
}

function MessageView({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="ml-8 rounded-lg bg-primary/10 px-3 py-2 text-sm whitespace-pre-wrap">
        <span className="sr-only">Anda: </span>
        {message.content}
      </div>
    );
  }
  return (
    <div className="mr-8 space-y-2 rounded-lg border border-border px-3 py-2 text-sm">
      <p className="whitespace-pre-wrap">
        <span className="sr-only">Asisten: </span>
        {withCitations(message.content)}
      </p>
      {message.warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-warning" aria-label="Peringatan jawaban">
          {message.warnings.map((w) => (
            <li key={w} className="flex gap-1">
              <AlertTriangle aria-hidden className="mt-0.5 size-3 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      )}
      <Notes title="Asumsi" items={message.assumptions} />
      <Notes title="Perlu klarifikasi dari Anda" items={message.questions} />
      {message.sources.length > 0 ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted">Sumber data ({message.sources.length})</summary>
          <ul className="mt-1 space-y-1">
            {message.sources.map((s) => (
              <li key={s.id}>
                <SourceView source={s} />
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p className="text-xs text-muted">Jawaban ini tidak mengutip sumber data.</p>
      )}
      <p className="text-[11px] text-muted">{formatTanggalWaktu(message.created_at)}</p>
    </div>
  );
}

function SourceView({ source }: { source: ChatSource }) {
  const href = sourceHref(source);
  return (
    <details>
      <summary className="cursor-pointer">
        <span className="mr-1 rounded bg-primary/10 px-1 font-medium text-primary">{source.id}</span>
        {href ? (
          <Link href={href} className="text-primary hover:underline">
            {source.label}
          </Link>
        ) : (
          source.label
        )}
        {source.cited === false && <span className="ml-1 text-warning">(terkait — tidak dikutip AI)</span>}
      </summary>
      <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface-muted p-2 font-mono text-[11px] whitespace-pre-wrap">
        {JSON.stringify(source.data, null, 1)}
      </pre>
    </details>
  );
}

function Notes({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="text-xs">
      <p className="font-medium text-muted">{title}</p>
      <ul className="list-disc pl-5">
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  );
}
