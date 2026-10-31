"use client";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { useMe } from "@/lib/me";
import { usePageTitle } from "@/lib/title";

/** The home page is the dashboard. */
export default function Home() {
  usePageTitle("Dashboard");
  const { data: user } = useMe();
  return user ? <Dashboard user={user} /> : null;
}
