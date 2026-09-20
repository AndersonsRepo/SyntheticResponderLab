import { NextResponse } from "next/server";

import { CLASSROOM_SESSION_COOKIE_NAME } from "@/lib/classroom-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Hand the shared classroom machine to the next student.
 *
 * Clearing the session cookie is what makes the isolation real: the backend owns
 * each room under `classroom:<session id>`, so a new cookie is a new owner, and the
 * previous student's rooms and memo are no longer addressable from this device.
 */
export async function POST() {
  const response = NextResponse.json({ data: { ended: true } });
  response.cookies.delete(CLASSROOM_SESSION_COOKIE_NAME);
  return response;
}
