import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "megoo_session";
const PUBLIC_PREFIXES = ["/login", "/setup", "/invite", "/reset", "/forgot"];

// Optimistic check only: the API is the real authority and answers 401 when the session is bad.
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isPublic = PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  if (isPublic || request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|jpg|webp)$).*)"],
};
