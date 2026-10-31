"use client";

import { NotificationPrefs } from "@/components/notifications/NotificationPrefs";
import { PushDevices } from "@/components/notifications/PushDevices";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePageTitle } from "@/lib/title";

export default function NotificationSettingsPage() {
  usePageTitle("Notification settings");
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Notifications"
        subtitle="Choose what reaches you in the app, by email and as push notifications. Email is sent only when an admin has set up SMTP."
      />
      <PushDevices />
      <NotificationPrefs />
    </div>
  );
}
