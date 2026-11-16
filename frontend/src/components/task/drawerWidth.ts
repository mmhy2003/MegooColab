"use client";

import { useStoredState } from "@/lib/stored";

export const DRAWER_WIDTH_KEY = "tasks.drawerWidth";
export const DRAWER_DEFAULT_WIDTH = 896; // max-w-4xl, the width before it could be resized
export const DRAWER_MIN_WIDTH = 720; // the task keeps its two columns
export const DRAWER_MARGIN = 48; // a strip of the page stays visible beside the drawer
export const DRAWER_STEP = 32; // one arrow key press

/** The widest the drawer may be in a window this wide; never under the narrowest. */
export function drawerMaxWidth(windowWidth: number): number {
  return Math.max(DRAWER_MIN_WIDTH, windowWidth - DRAWER_MARGIN);
}

/** A width within the drawer's range for this window, in whole pixels. */
export function clampDrawerWidth(width: number, windowWidth: number): number {
  const w = Number.isFinite(width) ? width : DRAWER_DEFAULT_WIDTH;
  return Math.round(Math.min(drawerMaxWidth(windowWidth), Math.max(DRAWER_MIN_WIDTH, w)));
}

/** The width the person chose, kept in this browser; clamped where it is used, so a smaller window squeezes it. */
export function useDrawerWidth(): [number, (width: number) => void] {
  return useStoredState(DRAWER_WIDTH_KEY, DRAWER_DEFAULT_WIDTH, "local");
}
