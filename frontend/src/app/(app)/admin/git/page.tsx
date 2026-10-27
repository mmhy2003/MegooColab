"use client";

import { GitConnections } from "@/components/git/GitConnections";
import { PageHeader } from "@/components/ui/PageHeader";
import { useMe } from "@/lib/me";

export default function AdminGitPage() {
  const { data: me } = useMe();
  if (!me) return null;
  if (me.role !== "admin") {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">You don&apos;t have permission to do that.</p>
      </div>
    );
  }
  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader
        title="Git"
        subtitle="Read-only tokens that let MegooColab follow pull requests. Project managers link each repository to one. Tokens and secrets are stored encrypted and never shown again."
      />
      <GitConnections />
    </div>
  );
}
