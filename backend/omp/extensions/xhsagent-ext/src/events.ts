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
        "You have access to XhsGrowthAgent tools for Xiaohongshu (小红书) free orchestration.",
        "Do not start the fixed workflow from OMP. The fixed workflow is only launched from the Simple Mode UI.",
        "Commands: /xhs (free creation orchestration), /xhs-review (review content), /xhs-analytics (view analytics).",
        "",
        "Free orchestration loop (no workflow thread — use thread-less xhs_free_* tools):",
        "1. CREATE: xhs_free_draft_create (title, body, hashtags, image_paths) → returns draft_id.",
        "2. EVALUATE: xhs_free_evaluate (draft_id) → 6-dimension RQGM quality score + decision.",
        "3. PUBLISH: xhs_free_publish (draft_id) → publishes via account CDP login state.",
        "4. ANALYTICS: xhs_free_analytics (draft_id) → post-publish engagement (views/likes/collects/comments/shares/engagement_rate).",
        "Draft management: xhs_free_draft_list / xhs_free_draft_update / xhs_free_draft_delete.",
        "Call xhs_free_guide for the full orchestration guide.",
        "Reuse draft_id across create→evaluate→publish; run xhs_free_evaluate before xhs_free_publish.",
        "After publish, call xhs_free_analytics to check engagement feedback.",
        "Do NOT call thread-bound tools (xhs_workflow_status/pause/resume/cancel, xhs_review_*, xhs_optimization_*) in free mode — there is no thread_id.",
        "For existing workflow content with a thread_id, use xhs_review_approve or xhs_publish_retry instead.",
        "Post-publish: xhs_workflow_trigger_analytics (only when a thread_id exists).",
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
