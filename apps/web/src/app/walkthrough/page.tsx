import type { Metadata } from "next";

import { WalkthroughPage } from "@/components/walkthrough/walkthrough-page";

export const metadata: Metadata = {
  title: "Video walkthrough · Grounded Synthetic Respondent Lab",
  description: "A narrated, chaptered tour of the Grounded Synthetic Respondent Lab, recorded in demo mode.",
};

export default function Page() {
  return <WalkthroughPage />;
}
