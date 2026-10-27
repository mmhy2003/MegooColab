"use client";

import { errorMessage } from "@/lib/errors";
import { KIND_LABELS, type NotificationPref, useNotificationPrefs, useSavePref } from "@/lib/notifications";

/** Per kind: in the app, and by email (email goes out only when an admin set up SMTP). */
export function NotificationPrefs() {
  const prefs = useNotificationPrefs();
  const save = useSavePref();
  if (prefs.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  const toggle = (p: NotificationPref, field: "in_app" | "email") => save.mutate({ ...p, [field]: !p[field] });
  return (
    <div className="space-y-2">
      <table className="card w-full max-w-xl text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="px-3 py-2 font-normal">When</th>
            <th className="px-3 py-2 font-normal">In app</th>
            <th className="px-3 py-2 font-normal">Email</th>
          </tr>
        </thead>
        <tbody>
          {(prefs.data ?? []).map((p) => (
            <tr key={p.kind} className="border-t border-line">
              <td className="px-3 py-2">{KIND_LABELS[p.kind]}</td>
              <td className="px-3 py-2">
                <input type="checkbox" aria-label={`In app: ${KIND_LABELS[p.kind]}`} checked={p.in_app} onChange={() => toggle(p, "in_app")} />
              </td>
              <td className="px-3 py-2">
                <input type="checkbox" aria-label={`Email: ${KIND_LABELS[p.kind]}`} checked={p.email} onChange={() => toggle(p, "email")} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {save.error && <p role="alert" className="text-sm text-pink">{errorMessage(save.error)}</p>}
    </div>
  );
}
