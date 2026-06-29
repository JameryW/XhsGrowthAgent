/** /xhs-review command — review pending XHS content or Ripple decision. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs-review", {
    description: "Review pending XHS content or Ripple CAS decision",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const threadId = (args || "").trim();
      pi.sendUserMessage([
        "Review the XHS content that is awaiting a decision.",
        threadId ? `Check workflow: ${threadId}` : "Find the workflow awaiting review using xhs_workflow_list or xhs_workflow_status.",
        "",
        "At review gate: use xhs_review_pending to see content, then xhs_review_approve or xhs_review_reject.",
        "At ripple gate: use xhs_ripple_pending to see prediction, then xhs_ripple_decision (accept/reangle/retopic).",
        "At optimization: use xhs_optimization_draft then xhs_optimization_select.",
      ].join("\n"));
    },
  });
}
