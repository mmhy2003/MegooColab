"use client";

import { ChatsPage } from "@/components/chats/ChatsPage";
import { usePageTitle } from "@/lib/title";

export default function Chats() {
  usePageTitle("Chats");
  return <ChatsPage />;
}
