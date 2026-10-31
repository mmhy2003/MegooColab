import { redirect } from "next/navigation";

/** The settings crumb opens the profile, the first of a person's settings. */
export default function SettingsPage() {
  redirect("/settings/profile");
}
