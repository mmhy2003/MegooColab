"use client";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/shadcn/tooltip";

/**
 * A tooltip naming an icon-only button, on hover and on keyboard focus. The button keeps its own aria-label.
 * It brings its own provider, so it works wherever the button is rendered (tests render components alone).
 */
export function Hint({ label, children }: { label: string; children: React.ReactElement }) {
  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
