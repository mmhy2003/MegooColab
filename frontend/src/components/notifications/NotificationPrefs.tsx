"use client";

import { useState } from "react";

import { CARD_TABLE } from "@/components/ui/cardTable";
import { ScrollX } from "@/components/ui/ScrollX";
import { errorMessage } from "@/lib/errors";
import {
  KIND_LABELS,
  type NotificationKind,
  type NotificationPref,
  useNotificationPrefs,
  useSavePref,
} from "@/lib/notifications";
import { useMyTelegram } from "@/lib/telegram";

/** Per kind: in the app, by email (only once an admin set up SMTP), as push (to the devices turned on above), and in
 * Telegram (while the site has a bot; ticked once this person connected their chat). */
export function NotificationPrefs() {
  const prefs = useNotificationPrefs();
  const telegram = useMyTelegram().data;
  // a toggle shows at once; once its save settles, the saved choices (or, after a failure, the old ones) show
  const [unsaved, setUnsaved] = useState<Partial<Record<NotificationKind, NotificationPref>>>({});
  const save = useSavePref((pref) =>
    setUnsaved((u) => {
      const shown = u[pref.kind];
      if (
        !shown || shown.in_app !== pref.in_app || shown.email !== pref.email || shown.push !== pref.push
        || shown.telegram !== pref.telegram
      ) {
        return u; // a newer toggle waits
      }
      const rest = { ...u };
      delete rest[pref.kind];
      return rest;
    }),
  );
  if (prefs.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const toggle = (p: NotificationPref, field: "in_app" | "email" | "push" | "telegram") => {
    const next = { ...p, [field]: !p[field] };
    setUnsaved((u) => ({ ...u, [p.kind]: next }));
    save.mutate(next);
  };
  return (
    <div className="space-y-2">
      {/* four or five columns: a wide screen has the table; a phone a card per event, its channels in a row */}
      <ScrollX className={`max-w-xl ${CARD_TABLE.box}`}>
        <table className={`w-full text-sm ${CARD_TABLE.table}`}>
          <thead className={CARD_TABLE.thead}>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="px-2 py-2 sm:px-3 font-normal">When</th>
              <th className="px-2 py-2 sm:px-3 font-normal">In app</th>
              <th className="px-2 py-2 sm:px-3 font-normal">Email</th>
              <th className="px-2 py-2 sm:px-3 font-normal">Push</th>
              {telegram?.available && <th className="px-2 py-2 sm:px-3 font-normal">Telegram</th>}
            </tr>
          </thead>
          <tbody className={CARD_TABLE.tbody}>
            {(prefs.data ?? []).map((saved) => unsaved[saved.kind] ?? saved).map((p) => (
              <tr key={p.kind} className={`border-t border-line ${CARD_TABLE.tr}`}>
                <td className="px-2 py-2 sm:px-3 max-md:block max-md:p-0 max-md:pb-1.5 max-md:font-medium">{KIND_LABELS[p.kind]}</td>
                <td data-label="In app" className="px-2 py-2 sm:px-3 max-md:mr-4 max-md:inline-flex max-md:items-center max-md:gap-1.5 max-md:p-0 max-md:text-xs max-md:text-muted-foreground max-md:before:content-[attr(data-label)]">
                  <input type="checkbox" aria-label={`In app: ${KIND_LABELS[p.kind]}`} checked={p.in_app} onChange={() => toggle(p, "in_app")} />
                </td>
                <td data-label="Email" className="px-2 py-2 sm:px-3 max-md:mr-4 max-md:inline-flex max-md:items-center max-md:gap-1.5 max-md:p-0 max-md:text-xs max-md:text-muted-foreground max-md:before:content-[attr(data-label)]">
                  <input type="checkbox" aria-label={`Email: ${KIND_LABELS[p.kind]}`} checked={p.email} onChange={() => toggle(p, "email")} />
                </td>
                <td data-label="Push" className="px-2 py-2 sm:px-3 max-md:mr-4 max-md:inline-flex max-md:items-center max-md:gap-1.5 max-md:p-0 max-md:text-xs max-md:text-muted-foreground max-md:before:content-[attr(data-label)]">
                  <input type="checkbox" aria-label={`Push: ${KIND_LABELS[p.kind]}`} checked={p.push ?? false} onChange={() => toggle(p, "push")} />
                </td>
                {telegram?.available && (
                  <td data-label="Telegram" className="px-2 py-2 sm:px-3 max-md:mr-4 max-md:inline-flex max-md:items-center max-md:gap-1.5 max-md:p-0 max-md:text-xs max-md:text-muted-foreground max-md:before:content-[attr(data-label)]">
                    <input
                      type="checkbox"
                      aria-label={`Telegram: ${KIND_LABELS[p.kind]}`}
                      checked={p.telegram ?? false}
                      disabled={!telegram.linked}
                      title={telegram.linked ? undefined : "Connect Telegram first"}
                      onChange={() => toggle(p, "telegram")}
                    />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      {save.error && <p role="alert" className="text-sm text-pink">{errorMessage(save.error)}</p>}
    </div>
  );
}
