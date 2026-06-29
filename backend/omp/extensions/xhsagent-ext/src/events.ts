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
        "Commands: /xhs (start workflow), /xhs-review (review content), /xhs-analytics (view analytics).",
        "Workflow: xhs_workflow_start, xhs_workflow_status, xhs_workflow_list, xhs_workflow_history, xhs_workflow_pause, xhs_workflow_resume, xhs_workflow_cancel, xhs_workflow_delete, xhs_workflow_trigger_analytics.",
        "Review: xhs_review_pending, xhs_review_versions, xhs_review_approve, xhs_review_reject.",
        "Ripple: xhs_ripple_pending, xhs_ripple_decision, xhs_ripple_retry.",
        "Blogger: xhs_blogger_pending, xhs_blogger_select.",
        "Optimization: xhs_optimization_draft, xhs_optimization_select.",
        "Analytics: xhs_analytics_dashboard, xhs_analytics_costs, xhs_analytics_report, xhs_analytics_performance, xhs_system_health.",
        ],
    };
  });
}
