"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { recordVisit } from "@/lib/backNav";
import { backNameOf, useShownTrail } from "@/lib/trail";

/** Records each page the tab shows, with its name, so Back can lead where the person came from. */
export function NavRecorder() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const label = backNameOf(useShownTrail(pathname));
  const url = search ? `${pathname}?${search}` : pathname;
  useEffect(() => recordVisit(url, label), [url, label]);
  return null;
}
