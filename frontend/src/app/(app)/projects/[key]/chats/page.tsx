"use client";

import { useParams } from "next/navigation";

import { ChatsPage } from "@/components/chats/ChatsPage";
import { usePageTitle } from "@/lib/title";

export default function ProjectChats() {
  const { key } = useParams<{ key: string }>();
  usePageTitle("Chats");
  return <ChatsPage projectKey={key.toUpperCase()} />;
}
