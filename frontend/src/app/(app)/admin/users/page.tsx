"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, MoreHorizontal, ShieldOff, Trash2, UserCheck, UserPlus, UserRoundPlus, UserX } from "lucide-react";
import { useState } from "react";

import { AdminOnly } from "@/components/admin/AdminOnly";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu";
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
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { usePageTitle } from "@/lib/title";

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

type Details = { user_id: string; totp: boolean; passkeys: number; last_login_at: string | null };
type Filter = "all" | "active" | "invited" | "deactivated" | "no2fa";

const day = (d: Date) => d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** "Never", "Today, 09:12", "Yesterday", "3 days ago", or the date. */
export function lastSignIn(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "Never";
  const at = new Date(iso);
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((midnight(now) - midnight(at)) / 86_400_000);
  if (days <= 0) return `Today, ${at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}`;
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return day(at);
}

function twoFactorHow(d: Details | undefined): string | null {
  if (!d || (!d.totp && d.passkeys === 0)) return null;
  const keys = d.passkeys ? `${d.passkeys} passkey${d.passkeys === 1 ? "" : "s"}` : null;
  return [d.totp ? "App" : null, keys].filter(Boolean).join(" + ");
}

/** Deleting can't be undone: it says what goes and what stays, and wants their email typed. */
function DeleteDialog({ user, onClose, onDelete }: { user: User; onClose: () => void; onDelete: () => void }) {
  const [typed, setTyped] = useState("");
  const matches = typed.trim().toLowerCase() === user.email.toLowerCase();
  return (
    <Dialog open title={`Delete ${user.name}?`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p>This can&apos;t be undone. To only stop them signing in, deactivate them instead.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-[11px] tracking-wider text-pink uppercase">Deleted with them</p>
            <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
              <li>Their account and sign-ins</li>
              <li>Access tokens and agents</li>
              <li>Notifications and push devices</li>
              <li>Team memberships</li>
              <li>Their personal memory</li>
            </ul>
          </div>
          <div>
            <p className="mb-1 text-[11px] tracking-wider text-green-ink uppercase">Kept for the team</p>
            <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
              <li>Tasks they created or had (unassigned)</li>
              <li>Comments, documents and decisions</li>
              <li>Knowledge Base pages</li>
              <li>Shown as &ldquo;Someone&rdquo;</li>
            </ul>
          </div>
        </div>
        <Input label={`Type ${user.email} to confirm`} data-autofocus value={typed} onChange={(e) => setTyped(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" disabled={!matches} onClick={onDelete}>Delete</Button>
        </div>
      </div>
    </Dialog>
  );
}

function AdminUsersPageContent() {
  const { ask, dialog: confirmDialog } = useConfirm();
  const { data: me } = useMe();
  const client = useQueryClient();
  const [dialog, setDialog] = useState<"invite" | "create" | null>(null);
  const [resetLink, setResetLink] = useState<{ name: string; url: string } | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const users = useQuery({ queryKey: qk.users(), queryFn: () => api<User[]>("/api/users") });
  // under ["users"], so every change here refetches it too
  const detailsQuery = useQuery({ queryKey: ["users", "details"], queryFn: () => api<Details[]>("/api/admin/users/details") });
  const details = new Map((Array.isArray(detailsQuery.data) ? detailsQuery.data : []).map((d) => [d.user_id, d]));

  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => client.invalidateQueries({ queryKey: ["users"] }),
    onError: (err) => setError(errorMessage(err)),
  });

  const all = users.data ?? [];
  const has2fa = (u: User) => twoFactorHow(details.get(u.id)) !== null;
  const FILTERS: { id: Filter; label: string; test: (u: User) => boolean }[] = [
    { id: "all", label: "All", test: () => true },
    { id: "active", label: "Active", test: (u) => u.status === "active" },
    { id: "invited", label: "Invited", test: (u) => u.status === "invited" },
    { id: "deactivated", label: "Deactivated", test: (u) => u.status === "deactivated" },
    { id: "no2fa", label: "Two-factor off", test: (u) => !has2fa(u) },
  ];
  const q = search.trim().toLowerCase();
  const shown = all
    .filter(FILTERS.find((f) => f.id === filter)!.test)
    .filter((u) => !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q));

  const copyLink = async (u: User) => {
    try {
      const r = await api<{ reset_url: string }>(`/api/admin/users/${u.id}/reset-link`, { method: "POST" });
      setResetLink({ name: u.name, url: r.reset_url });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <>
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
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            type="search"
            aria-label="Search people"
            placeholder="Search name or email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="min-w-48 flex-1 rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-muted-foreground focus:border-cyan focus:outline-none"
          />
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-full border px-3 py-1 text-xs ${filter === f.id ? "border-cyan bg-cyan/10 text-cyan-ink" : "border-line text-muted-foreground hover:text-fg"}`}
            >
              {f.label} {all.filter(f.test).length}
            </button>
          ))}
        </div>
        <div className="card overflow-x-auto max-md:border-0 max-md:bg-transparent max-md:shadow-none">
          {/* on a phone each row is a card: the cells wrap, the header row hides */}
          <table className="w-full text-left text-sm max-md:block">
            <thead className="text-xs tracking-wider text-muted-foreground uppercase max-md:hidden">
              <tr className="border-b border-line">
                <th className="px-3 py-2 font-normal">Person</th>
                <th className="px-3 py-2 font-normal">Role</th>
                <th className="px-3 py-2 font-normal">Status</th>
                <th className="px-3 py-2 font-normal">Two-factor</th>
                <th className="px-3 py-2 font-normal">Last sign-in</th>
                <th className="px-3 py-2 font-normal"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="max-md:block max-md:space-y-2">
              {shown.map((u) => {
                const d = details.get(u.id);
                const how = twoFactorHow(d);
                const own = u.id === me?.id;
                return (
                  <tr
                    key={u.id}
                    className={`border-b border-line last:border-0 max-md:flex max-md:flex-wrap max-md:items-center max-md:gap-2 max-md:rounded max-md:border max-md:bg-surface max-md:p-3 ${u.status === "deactivated" ? "opacity-70" : ""}`}
                  >
                    <td className="px-3 py-2 max-md:w-[calc(100%-3rem)] max-md:p-0">
                      <span className="flex items-center gap-2">
                        <Avatar name={u.name} size={26} />
                        <span className="min-w-0">
                          <span className="block truncate font-semibold">
                            {u.name}
                            {own && <span className="ml-1.5 rounded border border-line px-1 text-[10px] font-normal text-cyan-ink">you</span>}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">{u.email}</span>
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-2 max-md:order-2 max-md:p-0">
                      <select
                        aria-label={`Role of ${u.name}`}
                        className="rounded border border-line bg-surface-2 px-1 py-0.5 text-xs"
                        value={u.role}
                        disabled={own}
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
                    <td className="px-3 py-2 max-md:order-2 max-md:p-0">
                      <Badge tone={STATUS_TONE[u.status]}>{u.status}</Badge>
                    </td>
                    <td className="px-3 py-2 max-md:order-2 max-md:p-0">
                      {how ? (
                        <span className="inline-flex flex-col items-start">
                          <Badge tone="green">● On</Badge>
                          <span className="mt-0.5 text-[11px] text-muted-foreground max-md:hidden">{how}</span>
                        </span>
                      ) : (
                        <Badge>Off</Badge>
                      )}
                    </td>
                    <td className={`px-3 py-2 whitespace-nowrap max-md:order-2 max-md:p-0 max-md:text-xs ${d?.last_login_at ? "" : "text-muted-foreground"}`}>
                      {d ? lastSignIn(d.last_login_at) : ""}
                    </td>
                    <td className="px-3 py-2 text-right max-md:order-1 max-md:ml-auto max-md:p-0">
                      {!own && (
                        <DropdownMenu modal={false}>
                          <DropdownMenuTrigger asChild>
                            <button type="button" className="icon-btn" aria-label={`Actions for ${u.name}`}>
                              <MoreHorizontal size={16} aria-hidden />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" collisionPadding={8} className="w-60">
                            <DropdownMenuItem onSelect={() => void copyLink(u)}>
                              <Link2 size={14} aria-hidden />
                              {u.status === "invited" ? "Copy a new invite link" : "Copy a password-reset link"}
                            </DropdownMenuItem>
                            {how && (
                              <DropdownMenuItem
                                onSelect={async () => {
                                  const sure = await ask({
                                    tone: "danger",
                                    icon: ShieldOff,
                                    title: `Turn off two-factor sign-in for ${u.name}?`,
                                    text: "Their authenticator app and all their passkeys are removed. They sign in with their password alone and can set two-factor sign-in up again from their profile.",
                                    ok: "Turn off",
                                  });
                                  if (sure) act.mutate(() => api(`/api/admin/users/${u.id}/reset-two-factor`, { method: "POST" }));
                                }}
                              >
                                <ShieldOff size={14} aria-hidden />
                                Turn off two-factor sign-in
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            {u.status === "deactivated" ? (
                              <DropdownMenuItem onSelect={() => act.mutate(() => api(`/api/admin/users/${u.id}/reactivate`, { method: "POST" }))}>
                                <UserCheck size={14} aria-hidden />
                                Reactivate
                              </DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem
                                onSelect={async () => {
                                  if (await ask({ tone: "danger", icon: UserX, title: `Deactivate ${u.name}?`, text: "They are signed out everywhere immediately.", ok: "Deactivate" })) {
                                    act.mutate(() => api(`/api/admin/users/${u.id}/deactivate`, { method: "POST" }));
                                  }
                                }}
                              >
                                <UserX size={14} aria-hidden />
                                Deactivate
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuItem className="text-pink focus:text-pink" onSelect={() => setDeleting(u)}>
                              <Trash2 size={14} aria-hidden />
                              Delete…
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </td>
                  </tr>
                );
              })}
              {users.data && shown.length === 0 && (
                <tr className="max-md:block">
                  <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground max-md:block">No one matches.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {dialog && <NewUserDialog mode={dialog} onClose={() => setDialog(null)} />}
        {resetLink && (
          <Dialog open dismissible title={`Link for ${resetLink.name}`} onClose={() => setResetLink(null)}>
            <CopyField label="Single-use link" value={resetLink.url} />
          </Dialog>
        )}
        {deleting && (
          <DeleteDialog
            user={deleting}
            onClose={() => setDeleting(null)}
            onDelete={() => {
              const id = deleting.id;
              setDeleting(null);
              act.mutate(() => api(`/api/admin/users/${id}`, { method: "DELETE" }));
            }}
          />
        )}
      </div>
      {confirmDialog}
    </>
  );
}

export default function AdminUsersPage() {
  usePageTitle("Users", "Admin");
  return (
    <AdminOnly>
      <AdminUsersPageContent />
    </AdminOnly>
  );
}
