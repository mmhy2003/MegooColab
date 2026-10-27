"use client";

import { useState } from "react";

import { errorMessage } from "@/lib/errors";
import {
  KIND_LABELS,
  type NotificationKind,
  type NotificationPref,
  useNotificationPrefs,
  useSavePref,
} from "@/lib/notifications";

/** Per kind: in the app, and by email (email goes out only when an admin set up SMTP). */
export function NotificationPrefs() {
  const prefs = useNotificationPrefs();
  // a toggle shows at once; once its save settles, the saved choices (or, after a failure, the old ones) show
  const [unsaved, setUnsaved] = useState<Partial<Record<NotificationKind, NotificationPref>>>({});
  const save = useSavePref((pref) =>
    setUnsaved((u) => (u[pref.kind] === pref ? Object.fromEntries(Object.entries(u).filter(([k]) => k !== pref.kind)) : u)),
  );
  if (prefs.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  const toggle = (p: NotificationPref, field: "in_app" | "email") => {
    const next = { ...p, [field]: !p[field] };
    setUnsaved((u) => ({ ...u, [p.kind]: next }));
    save.mutate(next);
  };
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
          {(prefs.data ?? []).map((saved) => unsaved[saved.kind] ?? saved).map((p) => (
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
