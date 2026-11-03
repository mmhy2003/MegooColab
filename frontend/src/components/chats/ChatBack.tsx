"use client";

import { ChevronLeft } from "lucide-react";
import { useRouter } from "next/navigation";

import { originFor } from "@/lib/backNav";

const LIST = /^\/(chats|projects\/[^/]+\/chats)$/;

/** An open chat's way back to the list on a phone: the list it was opened from (a project's Chats tab, or all chats),
 * as this tab's own record of its pages says, or all chats when it came from anywhere else (a link, a notification).
 * Not the browser's Back: a chat opened in a new tab has none. */
export function ChatBack({ fallback }: { fallback: string }) {
  const router = useRouter();
  const back = () => {
    const from = originFor("chat")?.url;
    router.push(from && LIST.test(from.split(/[?#]/)[0]) ? from : fallback);
  };
  return (
    <button type="button" onClick={back} aria-label="All chats" className="icon-btn -ml-1 size-8 shrink-0 md:hidden">
      <ChevronLeft size={18} aria-hidden />
    </button>
  );
}
