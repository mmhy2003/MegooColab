"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PlatformToggle } from "@/components/agents/PlatformToggle";
import { Snippet } from "@/components/agents/Snippet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys } from "@/lib/hub";
import { qk } from "@/lib/queries";
import { both, detectPlatform, loginCommand, OMP_INSTALL, R, RELEASES, RUNNER_INSTALL, type Platform } from "@/lib/runner";

/** A runner token made in Add a machine: shown once, so it is kept by the Runner tab, not by these steps. */
export type MadeToken = { id: string; name: string; secret: string };

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span aria-hidden className="flex size-6 shrink-0 items-center justify-center rounded-full border border-cyan text-xs text-cyan-ink">
        {n}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <h3 className="text-sm font-bold">{title}</h3>
        {children}
      </div>
    </li>
  );
}

/** Setting the runner up on a new machine: name it (which makes its runner token), install, sign in with that token,
 * check it and keep it running, then wait for it to connect. */
export function AddMachine({
  made,
  connected,
  onMade,
  onAddAgent,
  onAnother,
}: {
  made: MadeToken | null;
  connected: boolean;
  onMade: (token: MadeToken) => void;
  onAddAgent: (machine: string) => void;
  /** start over for another machine, once this one has connected */
  onAnother: () => void;
}) {
  const client = useQueryClient();
  const [platform, setPlatform] = useState<Platform>(detectPlatform);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const note = "text-xs text-muted-foreground";

  const make = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ token: { id: string; name: string }; secret: string }>("/api/tokens", {
        method: "POST",
        json: { name: name.trim(), scopes: ["runner"], expires_in_days: null },
      });
      onMade({ id: res.token.id, name: res.token.name, secret: res.secret });
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.tokens() }),
        client.invalidateQueries({ queryKey: hubKeys.machines() }),
      ]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="add-machine-heading" className="card min-w-0 space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="add-machine-heading" className="flex-1 text-sm font-bold">Add a machine</h2>
        <PlatformToggle value={platform} onChange={setPlatform} />
      </div>
      <p className="text-sm text-muted-foreground">
        The runner is a small program on your computer that starts your agents when a task is assigned to them. Your code never leaves your machine.
      </p>
      <ol className="space-y-5">
        <Step n={1} title="Name it">
          {made ? (
            <p className="text-sm">
              <span className="font-bold">{made.name}</span> <span className={note}>· its runner token is made</span>
            </p>
          ) : (
            <form
              className="flex flex-wrap items-end gap-2 max-sm:flex-col max-sm:items-stretch"
              onSubmit={(e) => {
                e.preventDefault();
                void make();
              }}
            >
              <div className="min-w-0 flex-1">
                <Input label="Machine name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Laptop" maxLength={100} />
              </div>
              <Button type="submit" disabled={busy || !name.trim()}>Make token</Button>
            </form>
          )}
          {error && <p role="alert" className="text-sm text-pink">{error}</p>}
          <p className={note}>This makes a runner token for this machine; the name shows wherever you pick a machine.</p>
        </Step>
        <Step n={2} title="Install the runner">
          <Snippet label="Install the runner" value={RUNNER_INSTALL[platform]} />
          <p className={note}>
            Or <a href={RELEASES} target="_blank" rel="noreferrer">download it from GitHub</a>.
          </p>
        </Step>
        <Step n={3} title="Sign in">
          <Snippet label="Sign in" value={loginCommand(made ? made.secret : "<make the token in step 1>")} />
          {made && <p className="text-xs text-amber">The token is shown only now. If you leave this page, make another.</p>}
        </Step>
        <Step n={4} title="Check it, then keep it running">
          <Snippet label="Check it's ready" value={`${R} doctor`} />
          <Snippet label="Turn it on: register it and start it now" value={both(platform, `${R} service install`, `${R} service start`)} />
          {platform === "unix" && <Snippet label="Linux: keep it running after you sign out" value="loginctl enable-linger $USER" />}
          <Snippet label="Or start it in this terminal" value={`${R} run`} />
          <p className={note}>Started in a terminal, it stops when you close the terminal.</p>
        </Step>
      </ol>
      <details className="rounded border border-line p-3">
        <summary className="cursor-pointer text-sm">Using OMP agents on this machine</summary>
        <div className="mt-3 space-y-3">
          <Snippet label="OMP agents only: install OMP" value={OMP_INSTALL[platform]} />
          <Snippet label="OMP agents only: sign in to your model providers" value="omp auth-broker login" />
          <p className={note}>OMP 18.12.6 or newer. Claude Code and Codex agents don&apos;t need it.</p>
        </div>
      </details>
      {made &&
        (connected ? (
          <div className="flex flex-wrap items-center gap-2 rounded border border-green/50 p-3">
            <span className="flex-1 text-sm text-green-ink">Connected</span>
            <Button variant="ghost" onClick={onAnother}>Set up another machine</Button>
            <Button onClick={() => onAddAgent(made.id)}>Add an agent on it</Button>
          </div>
        ) : (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <span aria-hidden className="size-2 animate-pulse rounded-full bg-amber" />
            Waiting for the runner to connect…
          </p>
        ))}
    </section>
  );
}
