"use client";

import { useParams } from "next/navigation";

import { ChatsPage } from "@/components/chats/ChatsPage";
import { usePageTitle } from "@/lib/title";

export default function Chat() {
  const { id } = useParams<{ id: string }>();
  usePageTitle("Chats");
  return <ChatsPage chatId={id} />;
}
