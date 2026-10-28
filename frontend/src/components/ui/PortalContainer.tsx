"use client";

import { createContext, useContext } from "react";

/**
 * Where Radix popups (tooltips, popovers, menus) render. Normally <body>; inside an open MegooColab Dialog, the
 * <dialog> itself: a modal dialog sits in the browser's top layer, above anything in <body>, and makes the rest of
 * the page inert, so a popup rendered in <body> would be hidden behind it and unclickable.
 */
export const PortalContainerContext = createContext<HTMLElement | null>(null);

export function usePortalContainer(): HTMLElement | null {
  return useContext(PortalContainerContext);
}
