"use client";

import { useMe } from "@/lib/me";

/** An admin page's own guard: nothing while the user loads, a plain refusal for anyone else. The page's data
 *  hooks live in its children, so a non-admin never asks the server for admin data. */
export function AdminOnly({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe();
  if (!me) return null;
  if (me.role !== "admin") {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">You don&apos;t have permission to do that.</p>
      </div>
    );
  }
  return <>{children}</>;
}
