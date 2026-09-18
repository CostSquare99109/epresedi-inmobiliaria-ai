import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/proxy/auth/login", "/api/proxy/auth/refresh", "/api/proxy/health"];
const STATIC_PATHS = ["/_next", "/static", "/favicon.ico", "/icon.svg"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow static assets and public paths
  if (STATIC_PATHS.some(p => pathname.startsWith(p)) || PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }

  // Check for auth cookie or Authorization header
  const hasAuthCookie = request.cookies.has("admin_access_token");
  const hasAuthHeader = request.headers.get("authorization")?.startsWith("Bearer ");

  if (!hasAuthCookie && !hasAuthHeader) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|icon.svg|.*\\.png$).*)",
  ],
};