/**
 * The favicon's unread mark: a small red bell drawn in the browser over the app's own icon. Every `rel="icon"`
 * link points at the drawing while the mark is on and gets its own address back when it goes. The Apple touch icon
 * and the manifest's icons are not `rel="icon"` and stay as they are.
 */

const SIZE = 64;
// the badge: a red circle in the top-right corner, with a gap cut around it so it stands apart on any tab colour
const BADGE = { x: 46, y: 18, r: 16, gap: 3 };
const RED = "#ef4444";

let wanted = false;
let badged: string | null = null; // the drawing, made once per page load
let drawing = false;

function links(): HTMLLinkElement[] {
  return Array.from(document.head.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]'));
}

// the link's own address, also while it points at the drawing
const own = (link: HTMLLinkElement) => link.dataset.megooHref ?? link.getAttribute("href");

function source(): string | null {
  const all = links();
  const png = all.find((l) => l.type === "image/png") ?? all[0];
  return png ? own(png) : null;
}

function point() {
  for (const link of links()) {
    if (wanted && badged) {
      if (link.dataset.megooHref === undefined) link.dataset.megooHref = link.getAttribute("href") ?? "";
      link.href = badged;
    } else if (link.dataset.megooHref !== undefined) {
      link.setAttribute("href", link.dataset.megooHref);
      delete link.dataset.megooHref;
    }
  }
}

function draw(icon: HTMLImageElement): string {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2D canvas");
  ctx.drawImage(icon, 0, 0, SIZE, SIZE);
  const circle = (x: number, y: number, r: number) => {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();
  };
  ctx.globalCompositeOperation = "destination-out";
  circle(BADGE.x, BADGE.y, BADGE.r + BADGE.gap);
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = RED;
  circle(BADGE.x, BADGE.y, BADGE.r);
  // the bell: body, clapper and knob
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.moveTo(37, 24);
  ctx.lineTo(55, 24);
  ctx.lineTo(52, 20);
  ctx.lineTo(52, 15);
  ctx.arc(46, 15, 6, 0, Math.PI, true);
  ctx.lineTo(40, 20);
  ctx.closePath();
  ctx.fill();
  circle(46, 26.5, 2.5);
  circle(46, 8.5, 1.5);
  return canvas.toDataURL("image/png");
}

/** Shows or hides the bell badge on the tab's icon. Never throws: if it can't draw, the icon stays as it is. */
export function setFaviconBadge(on: boolean): void {
  wanted = on;
  if (!on || badged) {
    point();
    return;
  }
  const src = source();
  if (drawing || !src) return;
  drawing = true;
  const icon = new Image();
  icon.onload = () => {
    drawing = false;
    try {
      badged = draw(icon);
    } catch {
      return;
    }
    point(); // applies only if the badge is still wanted
  };
  icon.onerror = () => {
    drawing = false; // the next change of the count tries again
  };
  icon.src = src;
}
