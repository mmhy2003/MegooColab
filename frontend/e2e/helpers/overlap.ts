import type { Locator } from "@playwright/test";

/**
 * The text under `cover` inside `area`: each piece of text (per line box), other than `cover`'s own, whose box crosses
 * `cover`'s box. Empty when `cover` hides nothing.
 */
export async function textUnder(cover: Locator, area: Locator): Promise<string[]> {
  const box = await cover.boundingBox();
  if (!box) throw new Error("the cover isn't shown");
  const own = await cover.elementHandle();
  return area.evaluate((root, [b, self]) => {
    const hidden: string[] = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walk.nextNode(); node; node = walk.nextNode()) {
      const text = node.textContent?.trim();
      if (!text || self?.contains(node)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (r.width && r.left < b.x + b.width && r.right > b.x && r.top < b.y + b.height && r.bottom > b.y) {
          hidden.push(text);
          break;
        }
      }
    }
    return hidden;
  }, [box, own] as const);
}
