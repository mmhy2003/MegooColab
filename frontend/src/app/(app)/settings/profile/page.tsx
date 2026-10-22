"use client";

import { useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useState } from "react";

import { NewPasswordForm } from "@/components/auth/NewPasswordForm";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { qk } from "@/lib/queries";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card space-y-3 p-4">
      <h2 className="text-sm text-cyan-ink">{title}</h2>
      {children}
    </section>
  );
}

function TwoFactor({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; uri: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: qk.me() });

  if (enabled) {
    return (
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/api/auth/totp/disable", { method: "POST", json: { password, code } });
            setMsg({ ok: true, text: "Two-factor sign-in turned off." });
            await refresh();
          } catch (err) {
            setMsg({ ok: false, text: errorMessage(err) });
          }
        }}
      >
        <p className="text-sm text-green-ink">Two-factor sign-in is on.</p>
        <Input label="Password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Input label="Authenticator code" inputMode="numeric" required value={code} onChange={(e) => setCode(e.target.value)} />
        {msg && <p className={`text-sm ${msg.ok ? "text-green-ink" : "text-pink"}`}>{msg.text}</p>}
        <Button type="submit" variant="danger">Turn off</Button>
      </form>
    );
  }
  if (!setup) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">Add a code from an authenticator app to every sign-in.</p>
        <Button
          variant="ghost"
          onClick={async () => {
            try {
              const r = await api<{ secret: string; otpauth_uri: string }>("/api/auth/totp/setup", { method: "POST" });
              setSetup({ secret: r.secret, uri: r.otpauth_uri, qr: await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 180 }) });
            } catch (err) {
              setMsg({ ok: false, text: errorMessage(err) });
            }
          }}
        >
          Set up
        </Button>
        {msg && <p className="text-sm text-pink">{msg.text}</p>}
      </div>
    );
  }
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api("/api/auth/totp/enable", { method: "POST", json: { code } });
          setSetup(null);
          setCode("");
          setMsg({ ok: true, text: "Two-factor sign-in is on." });
          await refresh();
        } catch (err) {
          setMsg({ ok: false, text: errorMessage(err) });
        }
      }}
    >
      <p className="text-sm">Scan this with your authenticator app, then enter the 6-digit code it shows.</p>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={setup.qr} alt="QR code for your authenticator app" width={180} height={180} className="rounded bg-white p-1" />
      <p className="text-xs text-muted break-all">Or enter this key manually: {setup.secret}</p>
      <Input label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
      {msg && <p className={`text-sm ${msg.ok ? "text-green-ink" : "text-pink"}`}>{msg.text}</p>}
      <Button type="submit">Turn on</Button>
    </form>
  );
}

function NameForm({ initial }: { initial: string }) {
  const client = useQueryClient();
  const [name, setName] = useState(initial);
  const [saved, setSaved] = useState<string | null>(null);
  return (
    <>
        <form
          className="flex items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/api/auth/me", { method: "PATCH", json: { name } });
              await client.invalidateQueries({ queryKey: qk.me() });
              setSaved("Saved.");
            } catch (err) {
              setSaved(errorMessage(err));
            }
          }}
        >
          <div className="flex-1"><Input label="Display name" required value={name} onChange={(e) => setName(e.target.value)} /></div>
          <Button type="submit" variant="ghost">Save</Button>
        </form>
        {saved && <p className="text-sm text-muted">{saved}</p>}
    </>
  );
}

export default function ProfilePage() {
  const { data: me } = useMe();
  const [pwDone, setPwDone] = useState(false);

  if (!me) return null;
  return (
    <div className="max-w-xl space-y-4">
      <PageHeader title="Profile" subtitle={me.email} />
      <Section title="Name">
        <NameForm key={me.id} initial={me.name} />
      </Section>
      <Section title="Password">
        {pwDone ? (
          <p className="text-sm text-green-ink">Password changed. Other sessions were signed out.</p>
        ) : (
          <NewPasswordForm
            currentPassword
            submitLabel="Change password"
            onSubmit={async (password, current) => {
              await api("/api/auth/change-password", { method: "POST", json: { current_password: current, new_password: password } });
              setPwDone(true);
            }}
          />
        )}
      </Section>
      <Section title="Two-factor sign-in">
        <TwoFactor enabled={me.totp_enabled} />
      </Section>
    </div>
  );
}
