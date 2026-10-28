"use client";

import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { useState } from "react";

import { LABEL_HIDDEN, Sidebar } from "@/components/shell/Sidebar";
import type { User } from "@/lib/types";

export const SIDEBAR_KEY = "megoo.sidebar";

function load(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "collapsed";
  } catch {
    return false; // storage blocked (private window, site data off): start expanded
  }
}

function save(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? "collapsed" : "expanded");
  } catch {
    // not remembered this time; the toggle still works
  }
}

/**
 * The sidebar on wide screens. Collapsed, it is a strip of icons; resting the mouse on it (or tabbing into it) slides
 * the full menu out over the page, which does not move (a mouse click on the toggle does not hold it open). The choice is remembered in this browser.
 */
export function DesktopSidebar({ user }: { user: User }) {
  // the app shell renders only in the browser (after the user loads), so reading storage here is safe
  const [collapsed, setCollapsed] = useState(() => typeof window !== "undefined" && load());
  const toggle = () => {
    setCollapsed(!collapsed);
    save(!collapsed);
  };
  const Icon = collapsed ? ChevronsRight : ChevronsLeft;
  return (
    // sticky and one screen tall: it stays in view while a long page scrolls; open, the rail rises above the page
    // and its header (z-30), but only then, so popups still blur it otherwise
    <aside
      data-collapsed={collapsed}
      className={`sticky top-0 hidden h-screen shrink-0 md:block ${collapsed ? "w-14 hover:z-[35] has-[:focus-visible]:z-[35]" : "w-56"}`}
    >
      <div
        className={`group/side flex h-full flex-col border-r border-line ${
          collapsed
            ? "absolute inset-y-0 left-0 w-14 overflow-hidden bg-surface-2 transition-[width,box-shadow] duration-200 hover:w-56 hover:shadow-[8px_0_24px_rgba(0,0,0,0.35)] has-[:focus-visible]:w-56 has-[:focus-visible]:shadow-[8px_0_24px_rgba(0,0,0,0.35)]"
            : "w-56 bg-surface-2/60"
        }`}
      >
        <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
          <Sidebar user={user} collapsed={collapsed} />
        </div>
        <button
          type="button"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={toggle}
          className="m-2 flex items-center gap-2 rounded px-3 py-2 text-sm whitespace-nowrap text-muted hover:bg-surface hover:text-cyan"
        >
          <Icon size={16} aria-hidden className="shrink-0" />
          <span className={collapsed ? LABEL_HIDDEN : ""}>{collapsed ? "Expand" : "Collapse"}</span>
        </button>
      </div>
    </aside>
  );
}
