import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CATALOG_ID, COMPONENT_PROPS } from "@/components/a2ui/catalog";

type Schema = { properties?: Record<string, unknown>; allOf?: { properties?: Record<string, unknown> }[] };
const backend = JSON.parse(
  readFileSync(join(process.cwd(), "..", "backend", "app", "a2ui", "catalog.json"), "utf8"),
) as { catalogId: string; components: Record<string, Schema> };

/** A component's property names in the backend catalog, without the envelope's "id" and "component". */
function propsOf(schema: Schema): string[] {
  const keys = [
    ...Object.keys(schema.properties ?? {}),
    ...(schema.allOf ?? []).flatMap((item) => Object.keys(item.properties ?? {})),
  ];
  return [...new Set(keys)].filter((k) => k !== "id" && k !== "component").sort();
}

describe("catalog", () => {
  it("the catalog has the same components and properties as the backend", () => {
    const expected = Object.fromEntries(
      Object.entries(backend.components).map(([name, schema]) => [name, propsOf(schema)]),
    );
    const actual = Object.fromEntries(Object.entries(COMPONENT_PROPS).map(([name, props]) => [name, [...props].sort()]));
    expect(actual).toEqual(expected);
    expect(CATALOG_ID).toBe(backend.catalogId);
  });
});
