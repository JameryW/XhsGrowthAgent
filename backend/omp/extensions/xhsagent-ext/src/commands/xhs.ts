/** /xhs command — start a XHS content creation workflow. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs", {
    description: "Start a XHS content creation workflow",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const topic = (args || "").trim();
      pi.sendUserMessage([
        `Create a Xiaohongshu (小红书) content post.`,
        topic ? `Topic: ${topic}` : "Pick a trending topic using the workflow.",
        "Use xhs_workflow_start to launch the workflow, then track progress with xhs_workflow_status.",
        "At blogger selection: xhs_blogger_pending then xhs_blogger_select.",
        "At review: xhs_review_pending then xhs_review_approve or xhs_review_reject.",
        "At optimization: xhs_optimization_draft then xhs_optimization_select.",
      ].join("\n"));
    },
  });
}
