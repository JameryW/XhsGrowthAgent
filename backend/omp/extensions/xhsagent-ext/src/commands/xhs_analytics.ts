/** /xhs-analytics command — view analytics and cost data. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs-analytics", {
    description: "View XHS analytics dashboard and cost data",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const accountId = (args || "").trim();
      pi.sendUserMessage([
        accountId ? `View analytics for account: ${accountId}` : "View analytics across all accounts.",
        "Use xhs_analytics_dashboard to see performance data, xhs_analytics_costs for LLM cost tracking.",
        "Use xhs_system_health to check system status.",
      ].join("\n"));
    },
  });
}
