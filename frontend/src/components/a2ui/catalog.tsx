"use client";

import { useState, type ReactNode } from "react";

import { Input } from "@/components/ui/Input";
import { Markdown } from "@/components/ui/Markdown";

/** MegooColab's A2UI catalog (backend/app/a2ui/catalog.json). */
export const CATALOG_ID = "urn:megoocolab:a2ui:catalog:v1";

/** What every input of the catalog takes. `FormSurface` adapts the renderer's resolved props to it. */
export type FieldProps<V> = {
  id: string;
  label?: string;
  value: V;
  onChange: (v: V) => void;
  readOnly: boolean;
  /** the first failing check's message */
  error?: string;
};

export function Column({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-3">{children}</div>;
}

export function Text({ text }: { text: string }) {
  return <Markdown compact>{text}</Markdown>;
}

export function TextField({ id, label, value, onChange, readOnly, error }: FieldProps<string>) {
  // a check message waits until the person has touched the field
  const [touched, setTouched] = useState(false);
  return (
    <Input
      id={id}
      label={label}
      value={value}
      disabled={readOnly}
      error={touched && !readOnly ? error : undefined}
      onChange={(e) => {
        setTouched(true);
        onChange(e.target.value);
      }}
      onBlur={() => setTouched(true)}
    />
  );
}
