import { describe, expect, it } from "vitest";

import { middleTruncate } from "@/lib/paths";

describe("middleTruncate", () => {
  it("keeps the first part and the end of a long path", () => {
    expect(middleTruncate("C:\\Users\\hammad\\Projects\\checkout-service", 30)).toBe("C:\\…\\Projects\\checkout-service");
    expect(middleTruncate("C:\\Users\\hammad\\Projects\\checkout-service", 28)).toBe("C:\\…\\checkout-service");
    expect(middleTruncate("/home/me/a/very/deep/tree/checkout-service", 24)).toBe("/home/…/checkout-service");
  });

  it("leaves a path that fits as it is", () => {
    expect(middleTruncate("/home/me/work/checkout-service", 40)).toBe("/home/me/work/checkout-service");
  });

  it("keeps at least the last part, even when that alone is too long", () => {
    expect(middleTruncate("C:\\x\\a-very-long-folder-name-indeed", 10)).toBe("C:\\…\\a-very-long-folder-name-indeed");
  });
});
