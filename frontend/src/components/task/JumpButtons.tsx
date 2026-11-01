"use client";

import { ArrowDown, ArrowUp, Flag } from "lucide-react";
import { type RefObject, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Hint } from "@/components/ui/Hint";

const NEAR_TOP = 200;
const AT_BOTTOM = 4; // px of slack: a fractional scroll position still counts as the bottom
const MAX_EARLIER_PAGES = 10;
const WAITING = "[data-waiting]";
const FLASH_MS = 1600;
const flashes = new WeakMap<HTMLElement, ReturnType<typeof setTimeout>>();

type Entry = { id: string; at: string };

const smooth = (): ScrollBehavior =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
const atBottomOf = (el: HTMLElement) => el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM;

/** Scrolls the waiting item into view, highlights it for a moment and moves focus there (keyboard users go on
 * with Tab from it). */
function reveal(scroller: HTMLElement, target: HTMLElement) {
  const top = scroller.scrollTop + target.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 16;
  scroller.scrollTo({ top, behavior: smooth() });
  clearTimeout(flashes.get(target));
  target.classList.remove("jump-flash");
  void target.offsetWidth; // restart the animation when the same item is jumped to again
  target.classList.add("jump-flash");
  // a timer, not animationend: with reduced motion the animation ends at once and the still outline must stay a while
  flashes.set(target, setTimeout(() => target.classList.remove("jump-flash"), FLASH_MS));
  if (!target.hasAttribute("tabindex")) target.tabIndex = -1;
  target.focus({ preventScroll: true });
}

// the corner stack: 1rem from the bottom and right edges, up to three 36px buttons with 8px gaps, about 3rem wide
const STACK_ZONE = 16 + 3 * 44;
const STACK_WIDTH = 64;
const PILL_WIDTH = 160; // "Following live", in the bottom-left corner
const PILL_ZONE = 16 + 28;

export type Lift = { right: number; left: number };
const NO_LIFT: Lift = { right: 0, left: 0 };

/**
 * How far the corner buttons (right) and the "Following live" note (left) must rise so they never cover `avoid`
 * (the floating comment box): the distance from the scroller's bottom to its top while it sits in that corner,
 * else 0. On a wide layout the box is in the left column, away from the buttons; on a narrow one it floats right
 * under them.
 */
export function useLiftAbove(scrollRef: RefObject<HTMLElement | null>, avoid: HTMLElement | null): Lift {
  const [lift, setLift] = useState<Lift>(NO_LIFT);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !avoid) return;
    const measure = () => {
      const s = el.getBoundingClientRect();
      const c = avoid.getBoundingClientRect();
      const visible = c.top < s.bottom;
      const rise = Math.ceil(s.bottom - c.top);
      const right = visible && c.right > s.right - STACK_WIDTH && c.bottom > s.bottom - STACK_ZONE ? rise : 0;
      const left = visible && c.left < s.left + PILL_WIDTH && c.bottom > s.bottom - PILL_ZONE ? rise : 0;
      setLift((was) => (was.right === right && was.left === left ? was : { right, left }));
    };
    measure();
    el.addEventListener("scroll", measure, { passive: true });
    const sizes = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    sizes?.observe(el);
    sizes?.observe(avoid);
    return () => {
      el.removeEventListener("scroll", measure);
      sizes?.disconnect();
    };
  }, [scrollRef, avoid]);
  return avoid ? lift : NO_LIFT;
}

/**
 * The corner buttons of a task: back to top, go to the latest Activity and follow it live, and jump to what waits
 * on the person. Anything a person can decide marks itself with `data-waiting` (its kind); they are counted and
 * visited in page order. Following stops only when the person scrolls up, and starts again when they reach the
 * bottom themselves.
 *
 * `activity` is the live Activity page, oldest first: what arrives while not following is counted on ↓.
 * `expectQuestion` with `loadEarlier`: an agent question waits on the person but may be older than the loaded
 * Activity; it counts, and jumping to it loads earlier pages until it shows.
 */
export function JumpButtons({
  scrollRef,
  activity,
  loadEarlier,
  expectQuestion = false,
  lift = NO_LIFT,
}: {
  scrollRef: RefObject<HTMLElement | null>;
  activity: Entry[];
  loadEarlier?: () => Promise<boolean>;
  expectQuestion?: boolean;
  /** px each corner rises: the floating comment box's height where it sits under it (useLiftAbove) */
  lift?: Lift;
}) {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const el = scrollRef.current;
      if (!el) return () => {};
      el.addEventListener("scroll", onChange, { passive: true });
      const sizes = new ResizeObserver(onChange);
      sizes.observe(el);
      if (el.firstElementChild) sizes.observe(el.firstElementChild);
      const marks = new MutationObserver(onChange);
      marks.observe(el, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-waiting"] });
      return () => {
        el.removeEventListener("scroll", onChange);
        sizes.disconnect();
        marks.disconnect();
      };
    },
    [scrollRef],
  );
  // one string, so React compares the reading by value
  const reading = useSyncExternalStore(
    subscribe,
    () => {
      const el = scrollRef.current;
      if (!el) return "top bottom 0 -";
      return [
        el.scrollTop < NEAR_TOP ? "top" : "-",
        atBottomOf(el) ? "bottom" : "-",
        el.querySelectorAll(WAITING).length,
        el.querySelector('[data-waiting="question"]') ? "question" : "-",
      ].join(" ");
    },
    () => "top bottom 0 -",
  );
  const [nearTop, atBottom, marked, question] = reading.split(" ");

  const newest = activity.length ? activity[activity.length - 1].at : null;
  const newestRef = useRef(newest);
  useEffect(() => {
    newestRef.current = newest;
  }, [newest]);

  const [following, setFollowingState] = useState(false);
  const followingRef = useRef(false);
  // the newest entry the person has seen: what came after it, while not following, is counted on ↓
  const [seenAt, setSeenAt] = useState(newest);
  const follow = useCallback((on: boolean) => {
    followingRef.current = on;
    setFollowingState(on);
    setSeenAt(newestRef.current);
  }, []);

  // only the person's own scrolling decides: up stops following, reaching the bottom starts it again. The page
  // getting shorter under them (the browser moving the position up by itself) is not them scrolling up.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let lastTop = el.scrollTop;
    let lastHeight = el.scrollHeight;
    const onScroll = () => {
      if (atBottomOf(el)) {
        if (!followingRef.current) follow(true);
      } else if (followingRef.current && el.scrollTop < lastTop && el.scrollHeight >= lastHeight) {
        follow(false);
      }
      lastTop = el.scrollTop;
      lastHeight = el.scrollHeight;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [scrollRef, follow]);

  // following: new entries, and anything that grows (an image, a diagram), keep the bottom in view
  useEffect(() => {
    const el = scrollRef.current;
    if (el && followingRef.current) el.scrollTo({ top: el.scrollHeight, behavior: "auto" });
  }, [scrollRef, activity]);
  useEffect(() => {
    const el = scrollRef.current;
    const content = el?.firstElementChild;
    if (!el || !content || !following) return;
    const sizes = new ResizeObserver(() => {
      if (followingRef.current) el.scrollTo({ top: el.scrollHeight, behavior: "auto" });
    });
    sizes.observe(content);
    return () => sizes.disconnect();
  }, [scrollRef, following]);

  const missingQuestion = expectQuestion && !!loadEarlier && question !== "question";
  const waiting = Number(marked) + (missingQuestion ? 1 : 0);
  const unseen = following || !seenAt ? 0 : activity.filter((a) => Date.parse(a.at) > Date.parse(seenAt)).length;

  const next = useRef(0);
  const jumpToWaiting = async () => {
    const el = scrollRef.current;
    if (!el || waiting === 0) return;
    follow(false);
    const targets = [...el.querySelectorAll<HTMLElement>(WAITING)];
    const i = next.current % waiting;
    next.current = i + 1;
    let target: HTMLElement | null = targets[i] ?? null;
    if (!target && loadEarlier) {
      // the older agent question: load earlier Activity until it shows
      for (let page = 0; page < MAX_EARLIER_PAGES && !target; page++) {
        if (!(await loadEarlier())) break;
        await settle();
        target = el.querySelector<HTMLElement>('[data-waiting="question"]');
      }
    }
    if (target) reveal(el, target);
  };

  const toTop = () => {
    follow(false);
    scrollRef.current?.scrollTo({ top: 0, behavior: smooth() });
  };
  const toLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    follow(true);
    el.scrollTo({ top: el.scrollHeight, behavior: smooth() });
  };

  const round =
    "pointer-events-auto relative flex size-9 items-center justify-center rounded-full border bg-surface shadow-lg transition-colors hover:border-cyan";
  const bottom = `calc(1rem + ${lift.right}px)`;
  const downLabel = unseen ? `Go to the latest and follow (${unseen} new)` : "Go to the latest and follow";
  return (
    <>
      {following && (
        <p
          role="status"
          className="pointer-events-none absolute left-4 z-20 rounded-full border border-cyan bg-surface px-2 py-0.5 text-[11px] text-cyan-ink"
          style={{ bottom: `calc(1rem + ${lift.left}px)` }}
        >
          <span aria-hidden>● </span>Following live
        </p>
      )}
      <div data-jump-buttons className="pointer-events-none absolute right-4 z-20 flex flex-col items-end gap-2" style={{ bottom }}>
        {waiting > 0 && (
          <Hint label="Go to the next thing waiting on you">
            <button
              type="button"
              onClick={() => void jumpToWaiting()}
              className="pointer-events-auto flex h-9 items-center gap-1.5 rounded-full bg-amber px-3.5 text-sm font-semibold whitespace-nowrap text-on-accent shadow-[0_0_12px_rgba(255,209,102,0.45)]"
            >
              <Flag size={14} aria-hidden />
              {waiting} waiting on you
            </button>
          </Hint>
        )}
        {nearTop !== "top" && (
          <Hint label="Back to top">
            <button type="button" aria-label="Back to top" onClick={toTop} className={`${round} border-line text-fg`}>
              <ArrowUp size={16} aria-hidden />
            </button>
          </Hint>
        )}
        {atBottom !== "bottom" && (
          <Hint label={following ? "Following the latest" : "Go to the latest and follow"}>
            <button
              type="button"
              aria-label={downLabel}
              onClick={toLatest}
              className={`${round} ${following ? "border-cyan text-cyan-ink glow-box" : "border-line text-fg"}`}
            >
              <ArrowDown size={16} aria-hidden />
              {unseen > 0 && (
                <span
                  aria-hidden
                  className="absolute -top-1.5 -right-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-cyan px-1 text-[11px] font-bold text-on-accent"
                >
                  {unseen}
                </span>
              )}
            </button>
          </Hint>
        )}
      </div>
    </>
  );
}
