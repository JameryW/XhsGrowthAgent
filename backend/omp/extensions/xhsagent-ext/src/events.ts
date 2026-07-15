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

  // ── before_agent_start: inject mode-specific XHS context ──
  pi.on("before_agent_start", () => {
    const isFreeCreationMode = process.env.XHS_AGENT_MODE === "free";
    const systemPrompt = isFreeCreationMode
      ? [
          "You have access to XhsGrowthAgent tools for Xiaohongshu (小红书) Free Creation mode.",
          "Use the thread-less xhs_free_* tools for conversational creation; do not start the fixed workflow from this session.",
          "Commands: /xhs (free creation), /xhs-analytics (view analytics).",
          "",
          "Free creation loop: create a draft, evaluate it, revise when needed, publish only a real approved result, then inspect analytics.",
          "Draft management: xhs_free_draft_list / xhs_free_draft_update / xhs_free_draft_delete.",
          "Call xhs_free_guide for the full usage guide and reuse draft_id across updates, evaluation, and publishing.",
          "Evaluate can degrade (LLM timeout → pass-through fallback with degraded=True): the result is not a real score and must not be published.",
          "Publish failures include a recovery hint; fix the account or login state and retry the same draft_id. Do not request analytics without a successful post_id.",
          "",
          "Use xhs_system_health to check API status. For imported Creator Center notes, use xhs_creator_stats, xhs_creator_analysis, xhs_creator_suggestions, and xhs_creator_quality.",
        ]
      : [
          "You have access to XhsGrowthAgent workflow tools for Xiaohongshu (小红书).",
          "Use the fixed workflow tools for workflow sessions; the Free Creation entry is isolated to its own session.",
          "Commands: /xhs-review (review content), /xhs-analytics (view analytics), /xhs-evaluate (run RQGM evaluation).",
          "Use xhs_system_health to check API status and xhs_workflow_list to find workflows.",
          "Use xhs_analytics_dashboard/report/performance for workflow insights. For imported Creator Center notes, use xhs_creator_stats, xhs_creator_analysis, xhs_creator_suggestions, and xhs_creator_quality. Use xhs_analytics_costs for LLM spend.",
        ];
    return { systemPrompt };
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
