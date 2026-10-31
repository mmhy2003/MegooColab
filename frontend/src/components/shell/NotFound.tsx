"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button, buttonClass } from "@/components/ui/Button";

/** Whether the page before this one in the tab is one of ours. The Navigation API only lists this site's pages, so
 * another site or a new tab's start page doesn't count; without it, any earlier page does. */
function canGoBack(): boolean {
  const navigation = (window as { navigation?: { canGoBack: boolean } }).navigation;
  return navigation ? navigation.canGoBack : window.history.length > 1;
}

/** The page for an address with nothing behind it: a mistyped link, or a task, project or document that is gone. */
export function NotFoundView() {
  const pathname = usePathname();
  const router = useRouter();
  // with no earlier page of ours to go back to (a link opened in a new tab): the Dashboard instead
  const goBack = () => (canGoBack() ? router.back() : router.push("/"));
  return (
    <div className="mx-auto w-full max-w-md py-10 text-center md:py-16">
      <div aria-hidden className="mb-5 font-brand text-6xl font-bold tracking-wider md:text-8xl">
        <span className="text-cyan-ink glow-cyan">4</span>
        <span className="text-pink glow-pink">0</span>
        <span className="text-cyan-ink glow-cyan">4</span>
      </div>
      <div className="card glow-box p-6">
        <h1 className="mb-2 text-lg font-bold">This page doesn&apos;t exist</h1>
        <p className="mb-4 text-sm text-muted-foreground">
          The address may be mistyped, or what was here has been moved or deleted.
        </p>
        <code className="mb-5 inline-block max-w-full rounded border border-dashed border-line bg-surface-2 px-2 py-1 font-mono text-xs break-all">
          {pathname}
        </code>
        <div className="flex flex-wrap justify-center gap-2">
          <Button onClick={goBack}>
            <ArrowLeft size={14} aria-hidden /> Go back
          </Button>
          <Link href="/" className={buttonClass("ghost")}>
            Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
