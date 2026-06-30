/** Event handlers — API health check, agent context injection, and structured logging. */
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { checkApiHealth } from "./api_client.js";

export default function register(pi: ExtensionAPI) {
  // ── session_start: check API health and notify if unavailable ──
  pi.on("session_start", async (_event, ctx: ExtensionContext) => {
    const healthy = await checkApiHealth();
    if (!healthy && ctx.hasUI) {
      ctx.ui.notify(
        "⚠️ XhsGrowthAgent API is not reachable. Run `xhs-growth serve --port 8889` to start it.",
        "warning",
      );
    }
    pi.logger.debug("XhsGrowthAgent extension loaded", { apiHealthy: healthy });
  });

  // ── before_agent_start: inject XHS context ──
  pi.on("before_agent_start", () => {
    return {
      systemPrompt: [
        "You have access to XhsGrowthAgent tools for Xiaohongshu (小红书) content creation.",
        "Commands: /xhs (start workflow), /xhs-review (review content), /xhs-analytics (view analytics).",
        "",
        "Workflow lifecycle — follow these stages in order:",
        "1. Start: xhs_workflow_start → xhs_workflow_status (track progress)",
        "2. Blogger gate: xhs_blogger_pending → xhs_blogger_select (or skip)",
        "3. Review gate: xhs_review_pending → xhs_review_approve or xhs_review_reject",
        "4. Ripple gate: xhs_ripple_pending → xhs_ripple_decision (accept/reangle/retopic)",
        "5. Optimization: xhs_optimization_draft → xhs_optimization_select",
        "6. Post-publish: xhs_workflow_trigger_analytics (if analytics not auto-run)",
        "",
        "Use xhs_system_health to check API status. Use xhs_workflow_list to find workflows.",
        "Use xhs_analytics_dashboard/report/performance for insights. Use xhs_analytics_costs for LLM spend.",
      ],
    };
  });

  // ── tool_end: log tool results for debugging ──
  pi.on("tool_end" as any, async (event: any) => {
    const name = event?.toolName || event?.name || "unknown";
    const isError = event?.isError || false;
    if (isError) {
      pi.logger.warn(`XHS tool error: ${name}`, { toolName: name, error: event?.error });
    } else {
      pi.logger.debug(`XHS tool completed: ${name}`, { toolName: name });
    }
  });
}
