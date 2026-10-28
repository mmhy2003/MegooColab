"use client";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { useMe } from "@/lib/me";

/** The home page is the dashboard. */
export default function Home() {
  const { data: user } = useMe();
  return user ? <Dashboard user={user} /> : null;
}
