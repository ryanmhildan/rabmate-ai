"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Field";
import { api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import type { Member, Project } from "@/lib/types";

type Row = { user_id: string; full_name: string; role: "lead" | "member" };

const ROLE_LABEL = { lead: "Ketua", member: "Anggota" } as const;

function rowsOf(project: Project): Row[] {
  return project.members.map((m) => ({ user_id: m.user.id, full_name: m.user.full_name, role: m.role }));
}

export function ProjectMembers({
  project,
  canEdit,
  onSaved,
}: {
  project: Project;
  canEdit: boolean;
  onSaved: (project: Project) => void;
}) {
  const canListUsers = useCan("users.read");
  const editable = canEdit && canListUsers;
  const [draft, setDraft] = useState<Row[] | null>(null);
  const rows = draft ?? rowsOf(project);

  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<Member[]>("/users"),
    enabled: editable && draft !== null,
  });

  const save = useMutation({
    mutationFn: (members: Row[]) =>
      api.put<Project>(`/projects/${project.id}/members`, {
        members: members.map(({ user_id, role }) => ({ user_id, role })),
      }),
    onSuccess: (saved) => {
      onSaved(saved);
      setDraft(null);
      toast.success("Anggota proyek disimpan.");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const candidates = (users.data ?? []).filter(
    (u) => u.is_active && !rows.some((r) => r.user_id === u.id),
  );

  return (
    <Card title="Anggota proyek">
      {rows.length === 0 && <p className="text-sm text-muted">Belum ada anggota.</p>}
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.user_id} className="flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{row.full_name}</span>
            {draft ? (
              <>
                <Select
                  aria-label={`Peran ${row.full_name}`}
                  value={row.role}
                  className="w-28"
                  onChange={(event) =>
                    setDraft(
                      rows.map((r) =>
                        r.user_id === row.user_id ? { ...r, role: event.target.value as Row["role"] } : r,
                      ),
                    )
                  }
                >
                  <option value="lead">{ROLE_LABEL.lead}</option>
                  <option value="member">{ROLE_LABEL.member}</option>
                </Select>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Keluarkan ${row.full_name}`}
                  onClick={() => setDraft(rows.filter((r) => r.user_id !== row.user_id))}
                >
                  <Trash2 className="size-4" />
                </Button>
              </>
            ) : (
              <span className="text-xs text-muted">{ROLE_LABEL[row.role]}</span>
            )}
          </li>
        ))}
      </ul>

      {draft ? (
        <div className="space-y-3 border-t border-border pt-3">
          <Select
            aria-label="Tambah anggota"
            value=""
            disabled={users.isPending || candidates.length === 0}
            onChange={(event) => {
              const user = candidates.find((u) => u.id === event.target.value);
              if (user) setDraft([...rows, { user_id: user.id, full_name: user.full_name, role: "member" }]);
            }}
          >
            <option value="">
              {users.isPending ? "Memuat pengguna…" : candidates.length ? "+ Tambah anggota…" : "Semua pengguna sudah menjadi anggota"}
            </option>
            {candidates.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} ({u.role_label})
              </option>
            ))}
          </Select>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setDraft(null)} disabled={save.isPending}>
              Batal
            </Button>
            <Button size="sm" loading={save.isPending} onClick={() => save.mutate(rows)}>
              Simpan anggota
            </Button>
          </div>
        </div>
      ) : (
        editable && (
          <Button variant="secondary" size="sm" onClick={() => setDraft(rowsOf(project))}>
            Atur anggota
          </Button>
        )
      )}
    </Card>
  );
}
