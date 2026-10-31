"use client";

import { startAuthentication, startRegistration } from "@simplewebauthn/browser";

/** The browser creates a passkey for these options (from POST /api/auth/passkeys/options); its answer goes back
 * to the server as is. */
export function createPasskey(options: unknown): Promise<unknown> {
  return startRegistration({ optionsJSON: options as Parameters<typeof startRegistration>[0]["optionsJSON"] });
}

/** The browser asks for one of the person's passkeys for these options (a sign-in or a removal). */
export function getPasskey(options: unknown): Promise<unknown> {
  return startAuthentication({ optionsJSON: options as Parameters<typeof startAuthentication>[0]["optionsJSON"] });
}

type WebAuthnLike = { name?: unknown; code?: unknown; cause?: unknown };

/** The person closed or ignored the browser's prompt (or it timed out): not an error to explain, just try again. */
export function isDismissed(err: unknown): boolean {
  const e = (err ?? {}) as WebAuthnLike;
  if (e.code === "ERROR_CEREMONY_ABORTED") return true;
  if (e.name === "NotAllowedError" || e.name === "AbortError") return true;
  const cause = (e.cause ?? {}) as WebAuthnLike;
  return cause.name === "NotAllowedError" || cause.name === "AbortError";
}

/** A browser-side problem worth saying in words; null when there is nothing specific to say. */
export function passkeyProblem(err: unknown): string | null {
  const code = ((err ?? {}) as WebAuthnLike).code;
  if (code === "ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED") return "This device already has a passkey for your account.";
  return null;
}

/** A first guess at a new passkey's name, from the device it is made on. */
export function guessPasskeyName(userAgent: string): string {
  if (/iPhone/.test(userAgent)) return "iPhone";
  if (/iPad/.test(userAgent)) return "iPad";
  if (/Android/.test(userAgent)) return "Android phone";
  if (/Macintosh|Mac OS X/.test(userAgent)) return "Mac";
  if (/Windows/.test(userAgent)) return "Windows";
  if (/Linux|X11/.test(userAgent)) return "Linux";
  return "Security key";
}
