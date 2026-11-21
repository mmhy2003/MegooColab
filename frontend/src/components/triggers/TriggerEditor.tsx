"use client";

import { Dialog } from "@/components/ui/Dialog";

/** A stub of the trigger editor; its fields come with the next step. */
export function TriggerEditor({ projectKey, onClose }: { projectKey: string; onClose: () => void }) {
  return <Dialog open onClose={onClose} title={`New trigger · ${projectKey}`}>{null}</Dialog>;
}
