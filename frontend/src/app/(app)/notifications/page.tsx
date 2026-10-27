"use client";

import Link from "next/link";

import { NotificationList } from "@/components/notifications/NotificationList";
import { PageHeader } from "@/components/ui/PageHeader";

export default function NotificationsPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Notifications"
        subtitle="Tasks and questions that need you, assignments, mentions, and agents that went offline."
        actions={<Link href="/settings/notifications" className="text-sm">Settings</Link>}
      />
      <NotificationList />
    </div>
  );
}
