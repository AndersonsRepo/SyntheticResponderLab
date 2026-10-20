/** Paths the access gate never guards: framework assets, the readiness probe, the sign-in flow and the
 * public video walkthrough. (The walkthrough's files under /media/ are outside the middleware matcher.) */
export function isAlwaysPublicPath(pathname: string) {
  return (
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico" ||
    pathname === "/api/readiness" ||
    // The video walkthrough is for anyone with the link, signed in or not.
    pathname === "/walkthrough" ||
    pathname.startsWith("/access") ||
    pathname.startsWith("/api/access/") ||
    // Ending a shared-device session only clears a cookie; it must never need one.
    pathname.startsWith("/api/classroom/")
  );
}
