export const standaloneAppLinks = [
  { href: "/interview", label: "Student Interview" },
  { href: "/focus-group", label: "Focus Group" },
] as const;

export function canOpenCompactAppMenu(
  workflowNavigationLocked: boolean,
  standaloneDestinationCount: number
) {
  return !workflowNavigationLocked || standaloneDestinationCount > 0;
}
