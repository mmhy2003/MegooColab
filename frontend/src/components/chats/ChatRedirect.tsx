"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** A round of an agent chat has no task page of its own until it is added to the board: its links open the chat. */
export function ChatRedirect({ chatId }: { chatId: string }) {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/chats/${chatId}`);
  }, [router, chatId]);
  return (
    <p className="p-4 text-sm text-muted-foreground">
      This is part of a chat. <Link href={`/chats/${chatId}`}>Open the chat</Link>
    </p>
  );
}
