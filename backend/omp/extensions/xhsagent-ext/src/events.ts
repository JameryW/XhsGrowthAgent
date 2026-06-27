/** Event handlers — API health check on session start + agent context injection. */
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { checkApiHealth } from "./api_client.js";

export default function register(pi: ExtensionAPI) {
  // ── session_start: check API health and notify if unavailable ──
  pi.on("session_start", async (_event, ctx: ExtensionContext) => {
    const healthy = await checkApiHealth();
    if (!healthy && ctx.hasUI) {
      ctx.ui.notify(
        "⚠️ XhsGrowthAgent API is not reachable. Run `xhs-growth serve --port 8000` to start it.",
        "warning",
      );
    }
  });

  // ── before_agent_start: inject XHS context ──
  pi.on("before_agent_start", () => {
    return {
      systemPrompt: [
        "You have access to XhsGrowthAgent tools for Xiaohongshu (小红书) content creation.",
        "Use /xhs to start a creation workflow, /xhs-review to review pending content.",
        "Tools: xhs_workflow_start, xhs_workflow_status, xhs_workflow_pause, xhs_workflow_resume, xhs_workflow_cancel, xhs_review_approve, xhs_review_reject.",
      ],
    };
  });
}
