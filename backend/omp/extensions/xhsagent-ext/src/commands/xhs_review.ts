/** /xhs-review command — review pending XHS content. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs-review", {
    description: "Review pending XHS content awaiting approval",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const threadId = (args || "").trim();
      pi.sendUserMessage([
        "Review the XHS content that is awaiting approval.",
        threadId ? `Check workflow status for thread: ${threadId} using xhs_workflow_status.` : "First check which workflow is awaiting review using xhs_workflow_status.",
        "Then decide whether to approve (xhs_review_approve) or reject with feedback (xhs_review_reject).",
      ].join("\n"));
    },
  });
}
