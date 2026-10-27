"use client";

import { NotificationPrefs } from "@/components/notifications/NotificationPrefs";
import { PageHeader } from "@/components/ui/PageHeader";

export default function NotificationSettingsPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Notifications"
        subtitle="Choose what reaches you in the app and by email. Email is sent only when an admin has set up SMTP."
      />
      <NotificationPrefs />
    </div>
  );
}
