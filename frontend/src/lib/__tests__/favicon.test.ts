import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

type FakeImage = { onload: (() => void) | null; onerror: (() => void) | null; src: string };

const BADGE = "data:image/png;base64,BADGE";
const ORIGINAL = ["/favicon.ico", "/icon.png?abc", "/apple-icon.png?def"];

let images: FakeImage[] = [];
let setFaviconBadge: (on: boolean) => void;
let getContext: MockInstance;
let ctx: Record<string, unknown> & { arc: ReturnType<typeof vi.fn> };

const hrefs = () => [...document.head.querySelectorAll("link")].map((l) => l.getAttribute("href"));

beforeEach(async () => {
  vi.resetModules();
  ({ setFaviconBadge } = await import("@/lib/favicon"));
  document.head.innerHTML = [
    '<link rel="icon" href="/favicon.ico" sizes="any" type="image/x-icon">',
    '<link rel="icon" href="/icon.png?abc" type="image/png" sizes="512x512">',
    '<link rel="apple-touch-icon" href="/apple-icon.png?def">',
  ].join("");
  images = [];
  vi.stubGlobal(
    "Image",
    class {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      src = "";
      constructor() {
        images.push(this);
      }
    },
  );
  ctx = {
    drawImage: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    globalCompositeOperation: "",
    fillStyle: "",
  };
  getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue(BADGE);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.head.innerHTML = "";
});

describe("setFaviconBadge", () => {
  it("loads the PNG icon and points every icon link at the badge", () => {
    setFaviconBadge(true);
    expect(images).toHaveLength(1);
    expect(images[0].src).toBe("/icon.png?abc");
    expect(hrefs()).toEqual(ORIGINAL);

    images[0].onload!();
    expect(hrefs()).toEqual([BADGE, BADGE, "/apple-icon.png?def"]);
    expect(ctx.arc).toHaveBeenCalledWith(46, 18, 16, 0, 2 * Math.PI);
  });

  it("off puts the original addresses back", () => {
    setFaviconBadge(true);
    images[0].onload!();
    setFaviconBadge(false);
    expect(hrefs()).toEqual(ORIGINAL);
    expect(document.head.querySelector("[data-megoo-href]")).toBeNull();
  });

  it("a failed load leaves the links alone and throws nothing", () => {
    setFaviconBadge(true);
    expect(() => images[0].onerror!()).not.toThrow();
    expect(hrefs()).toEqual(ORIGINAL);

    setFaviconBadge(true);
    expect(images).toHaveLength(2);
  });

  it("no 2D canvas: the icon stays", () => {
    getContext.mockReturnValue(null);
    setFaviconBadge(true);
    expect(() => images[0].onload!()).not.toThrow();
    expect(hrefs()).toEqual(ORIGINAL);
  });

  it("off before the icon loads: the late drawing is not applied", () => {
    setFaviconBadge(true);
    setFaviconBadge(false);
    images[0].onload!();
    expect(hrefs()).toEqual(ORIGINAL);
  });

  it("draws once for repeated on and off", () => {
    setFaviconBadge(true);
    images[0].onload!();
    setFaviconBadge(false);
    setFaviconBadge(true);
    setFaviconBadge(false);
    setFaviconBadge(true);
    expect(images).toHaveLength(1);
    expect(getContext).toHaveBeenCalledTimes(1);
    expect(hrefs()).toEqual([BADGE, BADGE, "/apple-icon.png?def"]);
  });
});
