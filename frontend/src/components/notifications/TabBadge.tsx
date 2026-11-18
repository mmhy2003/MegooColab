"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { setFaviconBadge } from "@/lib/favicon";
import { useUnreadCount } from "@/lib/notifications";
import { setTitleCount } from "@/lib/title";

/** Marks the browser tab while anything is unread: a bell on the favicon and "(3) " before the title. Renders nothing. */
export function TabBadge() {
  const count = useUnreadCount().data?.count ?? 0;
  // a page change may re-render the head's icon links and title: mark them again
  const pathname = usePathname();
  useEffect(() => {
    setFaviconBadge(count > 0);
    setTitleCount(count);
  }, [count, pathname]);
  useEffect(
    () => () => {
      setFaviconBadge(false);
      setTitleCount(0);
    },
    [],
  );
  return null;
}
