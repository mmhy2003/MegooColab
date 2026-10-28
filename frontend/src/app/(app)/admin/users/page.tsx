"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, UserPlus, UserRoundPlus } from "lucide-react";
import { useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopyField } from "@/components/ui/CopyField";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { qk } from "@/lib/queries";
import type { Role, User } from "@/lib/types";
import { Hint } from "@/components/ui/Hint";

const ROLES: Role[] = ["admin", "manager", "member", "viewer"];
const STATUS_TONE = { active: "green", invited: "amber", deactivated: "muted" } as const;

function NewUserDialog({ mode, onClose }: { mode: "invite" | "create"; onClose: () => void }) {
  const client = useQueryClient();
  const [form, setForm] = useState({ email: "", name: "", role: "member" as Role, temporary_password: "" });
  const [error, setError] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [emailSent, setEmailSent] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (mode === "invite") {
        const r = await api<{ invite_url: string; email_sent: boolean }>("/api/admin/users/invite", {
          method: "POST",
          json: { email: form.email, name: form.name, role: form.role },
        });
        setInviteUrl(r.invite_url);
        setEmailSent(r.email_sent);
      } else {
        await api("/api/admin/users", { method: "POST", json: form });
        onClose();
      }
      await client.invalidateQueries({ queryKey: ["users"] });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Dialog open title={mode === "invite" ? "Invite user" : "Create user"} onClose={onClose}>
      {inviteUrl ? (
        <div className="space-y-4 text-sm">
          <p>{emailSent ? "Invitation sent by email. You can also share this link:" : "Email isn't set up, so share this link with them:"}</p>
          <CopyField label="Invite link (valid 7 days)" value={inviteUrl} />
          <Button onClick={onClose}>Done</Button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Input label="Email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input label="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Select label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </Select>
          {mode === "create" && (
            <Input
              label="Temporary password (min 10 characters)"
              type="text"
              required
              minLength={10}
              value={form.temporary_password}
              onChange={(e) => setForm({ ...form, temporary_password: e.target.value })}
            />
          )}
          {error && <p role="alert" className="text-sm text-pink">{error}</p>}
          <Button type="submit">{mode === "invite" ? "Send invite" : "Create"}</Button>
        </form>
      )}
    </Dialog>
  );
}

export default function AdminUsersPage() {
  const { data: me } = useMe();
  const client = useQueryClient();
  const [dialog, setDialog] = useState<"invite" | "create" | null>(null);
  const [resetLink, setResetLink] = useState<{ name: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const users = useQuery({ queryKey: qk.users(), queryFn: () => api<User[]>("/api/users") });

  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => client.invalidateQueries({ queryKey: ["users"] }),
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Invite people by email or create accounts directly."
        actions={
          <>
            <Button variant="ghost" onClick={() => setDialog("create")}>
              <UserRoundPlus size={14} aria-hidden /> Create
            </Button>
            <Button onClick={() => setDialog("invite")}>
              <UserPlus size={14} aria-hidden /> Invite
            </Button>
          </>
        }
      />
      {error && <p role="alert" className="mb-3 text-sm text-pink">{error}</p>}
      <div className="card overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs tracking-wider text-muted-foreground uppercase">
            <tr className="border-b border-line">
              <th className="px-3 py-2 font-normal">Name</th>
              <th className="px-3 py-2 font-normal">Email</th>
              <th className="px-3 py-2 font-normal">Role</th>
              <th className="px-3 py-2 font-normal">Status</th>
              <th className="px-3 py-2 font-normal"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2">
                  <span className="flex items-center gap-2"><Avatar name={u.name} /> {u.name}</span>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{u.email}</td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`Role of ${u.name}`}
                    className="rounded border border-line bg-surface-2 px-1 py-0.5 text-xs"
                    value={u.role}
                    disabled={u.id === me?.id}
                    onChange={(e) => {
                      // read the choice now: the request runs later, after React has put the select back to u.role
                      const role = e.target.value;
                      act.mutate(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", json: { role } }));
                    }}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2">
                  <Badge tone={STATUS_TONE[u.status]}>{u.status}</Badge>
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <Hint label="Copy a password-reset (or new invite) link">
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label={`Reset link for ${u.name}`}
                      onClick={async () => {
                        try {
                          const r = await api<{ reset_url: string }>(`/api/admin/users/${u.id}/reset-link`, { method: "POST" });
                          setResetLink({ name: u.name, url: r.reset_url });
                        } catch (err) {
                          setError(errorMessage(err));
                        }
                      }}
                    >
                      <Link2 size={14} aria-hidden />
                    </button>
                  </Hint>
                  {u.id !== me?.id &&
                    (u.status === "deactivated" ? (
                      <Button variant="ghost" className="ml-2" onClick={() => act.mutate(() => api(`/api/admin/users/${u.id}/reactivate`, { method: "POST" }))}>
                        Reactivate
                      </Button>
                    ) : (
                      <Button
                        variant="danger"
                        className="ml-2"
                        onClick={() => {
                          if (confirm(`Deactivate ${u.name}? They are signed out everywhere immediately.`)) {
                            act.mutate(() => api(`/api/admin/users/${u.id}/deactivate`, { method: "POST" }));
                          }
                        }}
                      >
                        Deactivate
                      </Button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dialog && <NewUserDialog mode={dialog} onClose={() => setDialog(null)} />}
      {resetLink && (
        <Dialog open dismissible title={`Link for ${resetLink.name}`} onClose={() => setResetLink(null)}>
          <CopyField label="Single-use link" value={resetLink.url} />
        </Dialog>
      )}
    </div>
  );
}
