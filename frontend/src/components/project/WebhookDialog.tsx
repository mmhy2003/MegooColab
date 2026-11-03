"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { CopyField } from "@/components/ui/CopyField";
import { Dialog } from "@/components/ui/Dialog";
import { api, ApiError } from "@/lib/api";
import { shortDuration } from "@/lib/dashboard";
import { errorMessage } from "@/lib/errors";
import { HOOK_STEPS, HOST_NAME, hookError, type GitKind, type WebhookInfo, type WebhookRenewed } from "@/lib/git";
import type { Repo } from "@/lib/types";

/** What a repository's webhook is doing, in a few words: shown on its row and in its dialog. */
export function webhookStatusText(status: Repo["webhook_status"], lastAt: string | null | undefined): string {
  if (status === "failing") return "Webhook failing";
  if (status === "working" && lastAt) return `Webhook working · last event ${shortDuration(Date.now() - Date.parse(lastAt))} ago`;
  if (status === "working") return "Webhook working";
  return "Webhook not set up";
}

/** A repository's own webhook: its address and secret to paste on the host with that host's steps, or Create it for
 * me; a new secret on request; and whether deliveries arrive (checked every few seconds while open). */
export function WebhookDialog({ projectKey, repo, onClose }: { projectKey: string; repo: Repo; onClose: () => void }) {
  const base = `/api/projects/${projectKey}/repositories/${repo.id}/webhook`;
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const info = useQuery({ queryKey: ["git", "webhook", repo.id], queryFn: () => api<WebhookInfo>(base), refetchInterval: 3000 });
  const [secret, setSecret] = useState<string | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const kind = (info.data?.kind ?? repo.provider) as GitKind;
  const host = HOST_NAME[kind] ?? "the host";

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setNote(null);
    try {
      await fn();
    } catch (err) {
      setNote({ ok: false, text: err instanceof ApiError && err.status === 422 ? hookError(err.detail) : errorMessage(err) });
    } finally {
      setBusy(false);
      void client.invalidateQueries({ queryKey: ["git", "webhook", repo.id] });
    }
  };

  return (
    <Dialog open title={`Webhook for ${repo.name}`} onClose={onClose} wide phoneFull>
      <div className="space-y-4 p-4 text-sm">
        <p className="text-xs text-muted-foreground">
          So MegooColab sees this repository&apos;s pull requests open, get reviewed and merge as it happens, without
          checking every few minutes.
        </p>
        {info.error && <p role="alert" className="text-pink">{errorMessage(info.error)}</p>}
        {info.data && (
          <>
            <p role="status" className={info.data.status === "working" ? "text-green-ink" : info.data.status === "failing" ? "text-pink" : "text-amber"}>
              {webhookStatusText(info.data.status, info.data.last_at)}
            </p>
            <CopyField label="Payload URL" value={info.data.url} />
            {info.data.public_url_is_default && (
              <p className="text-xs text-amber">
                This address is the default localhost one, which GitHub and GitLab can&apos;t reach. Set PUBLIC_URL to the
                address people use.
              </p>
            )}
            <div className="space-y-1">
              {secret ? (
                <CopyField label="Secret" value={secret} />
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xs tracking-wider text-muted-foreground uppercase">Secret</span>
                  <span className="font-mono text-xs text-muted-foreground">••••••••••••••••</span>
                  <Button variant="ghost" onClick={() => act(async () => setSecret((await api<{ secret: string }>(`${base}/secret`)).secret))}>
                    Show
                  </Button>
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                Made for this repository only.{" "}
                <button
                  type="button"
                  className="text-cyan-ink underline"
                  disabled={busy}
                  onClick={async () => {
                    if (!(await ask({ tone: "warn", title: "Make a new secret?", text: "The old secret stops working at once.", ok: "Make a new one" }))) return;
                    await act(async () => {
                      const renewed = await api<WebhookRenewed>(`${base}/secret`, { method: "POST" });
                      setSecret(renewed.secret);
                      if (renewed.host_updated === true) setNote({ ok: true, text: `Updated on ${host} too.` });
                      else if (renewed.host_updated === false) setNote({ ok: false, text: `Update it on ${host} too, or use Create it for me.` });
                    });
                  }}
                >
                  Make a new one
                </button>
              </p>
            </div>
            <div className="space-y-1">
              <h3 className="text-xs tracking-wider text-muted-foreground uppercase">On {host}</h3>
              <ol className="list-decimal space-y-1 pl-5 text-xs">
                {HOOK_STEPS[kind].map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <a href={info.data.hook_page_url} target="_blank" rel="noopener noreferrer" className="text-xs">
                Open {host}&apos;s webhook page ↗
              </a>
            </div>
            {note && <p role={note.ok ? "status" : "alert"} className={`text-xs ${note.ok ? "text-green-ink" : "text-pink"}`}>{note.text}</p>}
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await api(`${base}/install`, { method: "POST" });
                    setNote({ ok: true, text: `Created on ${host}.` });
                  })
                }
              >
                Create it for me
              </Button>
              <Button variant="ghost" onClick={onClose}>Done</Button>
            </div>
          </>
        )}
      </div>
      {dialog}
    </Dialog>
  );
}
