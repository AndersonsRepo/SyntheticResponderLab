"use client";

import { SignedIn, UserButton } from "@clerk/nextjs";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  CLASSROOM_MODE_COOKIE_NAME,
  isClassroomStudentPage,
} from "@/lib/classroom-access";

function useIsClassroomDevice(pathname: string) {
  // Read after mount: the marker is a cookie, and the server rendered this HTML before it
  // could know whether the browser had one.
  const [isClassroom, setIsClassroom] = useState(false);
  useEffect(() => {
    setIsClassroom(
      isClassroomStudentPage(pathname) &&
        document.cookie
          .split("; ")
          .some((entry) => entry.startsWith(`${CLASSROOM_MODE_COOKIE_NAME}=`))
    );
  }, [pathname]);
  return isClassroom;
}

export function UserMenuSlot() {
  const pathname = usePathname();
  const isClassroomDevice = useIsClassroomDevice(pathname);
  const isClerkConfigured =
    (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim() || "") !== "";

  // A shared classroom machine needs the only way to end its session, and classroom mode
  // runs with or without Clerk — so this cannot key off which auth the deployment uses.
  const endSession = isClassroomDevice ? (
    <button
      type="button"
      onClick={async () => {
        await fetch("/api/classroom/end-session", { method: "POST" });
        window.location.reload();
      }}
      title="Ends your session so the next student on this device gets a clean room list"
      className="shrink-0 whitespace-nowrap rounded-full border px-3 py-2 text-[0.7rem] text-app-muted transition hover:text-app-text [background:var(--button-secondary-bg)] [border-color:var(--button-secondary-border)]"
    >
      End session
    </button>
  ) : null;

  if (!isClerkConfigured) {
    return endSession;
  }

  return (
    <>
      {endSession}
      <SignedIn>
        <div className="flex items-center">
          <UserButton
            afterSignOutUrl="/"
            appearance={{
              elements: {
                userButtonAvatarBox:
                  "h-9 w-9 ring-1 ring-app-cyan/25 hover:ring-app-cyan/50 transition",
              },
            }}
          />
        </div>
      </SignedIn>
    </>
  );
}
