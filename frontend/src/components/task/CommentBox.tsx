"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";

export function CommentBox({ onSubmit }: { onSubmit: (body: string) => Promise<void> }) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!body.trim()) return;
        setBusy(true);
        try {
          await onSubmit(body);
          setBody("");
        } finally {
          setBusy(false);
        }
      }}
    >
      <textarea
        aria-label="Add a comment"
        placeholder="Add a comment (Markdown supported)"
        className="min-h-20 w-full rounded border border-line bg-surface-2 p-2 text-sm"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
        }}
      />
      <Button type="submit" disabled={busy || !body.trim()}>Comment</Button>
    </form>
  );
}
