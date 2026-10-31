"use client";

import { useEffect, useSyncExternalStore } from "react";

/** An account signed in on this browser, for the sign-in page's list. Never a password or a session. */
export type RememberedAccount = { email: string; name: string; lastUsed: number };

const KEY = "megoo-accounts";
const MAX = 10;
const CHANGED = "megoo-accounts-changed";

const norm = (email: string) => email.trim().toLowerCase();

function isAccount(a: unknown): a is RememberedAccount {
  const r = a as RememberedAccount;
  return !!r && typeof r.email === "string" && typeof r.name === "string" && typeof r.lastUsed === "number";
}

function raw(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null; // storage blocked (some private windows): nothing is remembered
  }
}

function parse(text: string | null): RememberedAccount[] {
  try {
    const list: unknown = JSON.parse(text ?? "[]");
    return Array.isArray(list) ? list.filter(isAccount).sort((a, b) => b.lastUsed - a.lastUsed) : [];
  } catch {
    return [];
  }
}

/** The remembered accounts, most recently used first. */
export function readAccounts(): RememberedAccount[] {
  return parse(raw());
}

function write(list: RememberedAccount[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    // storage blocked: the account just isn't remembered
  }
}

/** After a sign-in: the account goes to the top of the list, with its current name. */
export function rememberAccount(user: { email: string; name: string }): void {
  const email = norm(user.email);
  write([{ email, name: user.name, lastUsed: Date.now() }, ...readAccounts().filter((a) => a.email !== email)]);
}

/** The signed-in person's current name, for an account already in the list (a rename shows next time). */
export function renameAccount(user: { email: string; name: string }): void {
  const list = readAccounts();
  const email = norm(user.email);
  if (list.some((a) => a.email === email && a.name !== user.name)) {
    write(list.map((a) => (a.email === email ? { ...a, name: user.name } : a)));
  }
}

export function forgetAccount(email: string): void {
  write(readAccounts().filter((a) => a.email !== norm(email)));
}

// one parsed list per stored text, so the snapshot stays the same object while nothing changes
let cache: { text: string | null; list: RememberedAccount[] } = { text: null, list: [] };
const NONE: RememberedAccount[] = [];

function snapshot(): RememberedAccount[] {
  const text = raw();
  if (text !== cache.text) cache = { text, list: parse(text) };
  return cache.list;
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange); // another tab
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The remembered accounts, live; none while the page is rendered on the server. */
export function useRememberedAccounts(): RememberedAccount[] {
  return useSyncExternalStore(subscribe, snapshot, () => NONE);
}

/** In the app, once the signed-in person is known: a rename shows in the sign-in page's list next time. */
export function useKeepAccountName(user: { email: string; name: string } | undefined): void {
  const email = user?.email;
  const name = user?.name;
  useEffect(() => {
    if (email && name) renameAccount({ email, name });
  }, [email, name]);
}
