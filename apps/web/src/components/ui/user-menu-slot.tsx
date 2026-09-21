"use client";

import { SignedIn, UserButton } from "@clerk/nextjs";
import { usePathname } from "next/navigation";

import { isClassroomStudentPage } from "@/lib/classroom-access";

export function UserMenuSlot() {
  const pathname = usePathname();
  const isClerkConfigured =
    (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim() || "") !== "";

  if (!isClerkConfigured) {
    // ponytail: no Clerk means the classroom cookie IS the session, so the student pages
    // need the only way to end it. It lives in the nav where a sign-out would be.
    if (!isClassroomStudentPage(pathname)) return null;
    return (
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
    );
  }

  return (
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
  );
}
