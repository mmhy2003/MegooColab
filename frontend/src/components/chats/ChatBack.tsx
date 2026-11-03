"use client";

import { ChevronLeft } from "lucide-react";
import { useRouter } from "next/navigation";

/** An open chat's way back to the list on a phone: the list it came from (a project's Chats tab, or all chats), or
 * all chats when it was opened from anywhere else (a link, a notification). */
export function ChatBack({ fallback }: { fallback: string }) {
  const router = useRouter();
  const back = () => {
    let from: URL | null = null;
    try {
      from = document.referrer ? new URL(document.referrer) : null;
    } catch {
      from = null;
    }
    const fromList =
      from !== null && from.origin === window.location.origin && (from.pathname === "/chats" || /^\/projects\/[^/]+\/chats$/.test(from.pathname));
    if (fromList) router.back();
    else router.push(fallback);
  };
  return (
    <button type="button" onClick={back} aria-label="All chats" className="icon-btn -ml-1 size-8 shrink-0 md:hidden">
      <ChevronLeft size={18} aria-hidden />
    </button>
  );
}
