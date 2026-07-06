/** /xhs-evaluate command — evaluate creation quality (RQGM agent-as-a-judge) for XHS content. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs-evaluate", {
    description: "Evaluate XHS creation quality (RQGM agent-as-a-judge panel)",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const threadId = (args || "").trim();
      pi.sendUserMessage([
        "Evaluate the creation quality of an XHS workflow using the RQGM agent-as-a-judge panel.",
        threadId ? `Workflow: ${threadId}` : "Find the workflow using xhs_workflow_list or xhs_workflow_status.",
        "",
        "Use xhs_evaluation_run to evaluate the current content (copy/visual), then xhs_evaluation_result to read the verdict.",
        "The panel scores 9 dimensions: copywriting, visual, compliance, reach, audience, AI taste, image quality, commercial tone, and an adversarial bias check.",
        "If decision is needs_revision, the workflow auto-routes back to the copywriter with revision hints.",
      ].join("\n"));
    },
  });
}
