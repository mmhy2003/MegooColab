import { describe, expect, it } from "vitest";

import { guessPasskeyName, isDismissed, passkeyProblem } from "@/lib/passkeys";

describe("passkeys", () => {
  it.each([
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", "iPhone"],
    ["Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)", "iPad"],
    ["Mozilla/5.0 (Linux; Android 15; Pixel 9)", "Android phone"],
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)", "Mac"],
    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Windows"],
    ["Mozilla/5.0 (X11; Linux x86_64)", "Linux"],
    ["curl/8", "Security key"],
  ])("names a passkey after the device: %s", (ua, name) => expect(guessPasskeyName(ua)).toBe(name));

  it("tells a dismissed prompt from a real failure", () => {
    expect(isDismissed(new DOMException("x", "NotAllowedError"))).toBe(true);
    expect(isDismissed(new DOMException("x", "AbortError"))).toBe(true);
    expect(isDismissed(Object.assign(new Error("x"), { name: "NotAllowedError", code: "ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY" }))).toBe(true);
    expect(isDismissed(Object.assign(new Error("x"), { code: "ERROR_CEREMONY_ABORTED" }))).toBe(true);
    expect(isDismissed(new Error("x"))).toBe(false);
  });

  it("says when the device already has a passkey for the account", () => {
    expect(passkeyProblem(Object.assign(new Error("x"), { code: "ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED" }))).toBe(
      "This device already has a passkey for your account.",
    );
    expect(passkeyProblem(new Error("x"))).toBeNull();
  });
});
