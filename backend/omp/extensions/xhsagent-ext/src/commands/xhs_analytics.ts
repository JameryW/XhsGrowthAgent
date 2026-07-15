/** /xhs-analytics command — view analytics, reports, and costs. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs-analytics", {
    description: "View XHS analytics — dashboard, reports, performance, costs",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const accountId = (args || "").trim();
      pi.sendUserMessage([
        accountId ? `View analytics for account: ${accountId}` : "View analytics across all accounts.",
        "",
        "Available analytics tools:",
        "- xhs_analytics_dashboard: summary metrics, costs, insights",
        "- xhs_analytics_report: growth report with metrics and trend topics",
        "- xhs_analytics_performance: post-level likes, comments, engagement rate",
        "- xhs_analytics_costs: LLM cost tracking by model",
        "- xhs_creator_stats: imported Creator Center account/note metrics and top notes",
        "- xhs_creator_analysis: evidence-backed note-performance analysis and recommendations",
        "- xhs_creator_suggestions: trend, brief, or free-creation advice from imported data",
        "- xhs_creator_quality: historical creative-quality score, strengths, gaps, and next-post actions",
        "- xhs_system_health: check system status",
      ].join("\n"));
    },
  });
}
