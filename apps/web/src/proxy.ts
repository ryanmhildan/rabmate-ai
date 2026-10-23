import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "rabmate_session";

/**
 * Cheap pre-check: pages need a session cookie, otherwise go straight to /login.
 * Whether the session is actually valid is decided by the API (AuthGate handles 401s).
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();

  const url = request.nextUrl.clone();
  const target = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  url.pathname = "/login";
  url.search = target && target !== "/" ? `?next=${encodeURIComponent(target)}` : "";
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except the API rewrite, Next internals, static files and the login page itself.
  matcher: ["/((?!api/|_next/|login|favicon\\.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
