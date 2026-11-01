import { type NextRequest, NextResponse } from "next/server";

// UX only: redirects signed-out visitors to /login. Real authorization is enforced by the AI service on
// every request (the session token is validated there).
// Public paths: sign-in/setup, the widget script and demo page, and the API (which does its own auth).
const PUBLIC = ["/login", "/setup", "/v1/", "/trustdesk.js", "/demo"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();
  if (!req.cookies.get("td_session")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/|favicon.ico|v1/|trustdesk.js|demo).*)"] };
