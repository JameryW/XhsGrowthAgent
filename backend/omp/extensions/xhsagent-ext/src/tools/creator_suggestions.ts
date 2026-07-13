/** xhs_creator_suggestions — get mode-specific advice derived from imported Creator Center data. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface CreatorSuggestion {
  mode: string;
  category: string;
  title: string;
  advice: string;
  priority: number;
  evidence: string;
}

interface CreatorSuggestionsResponse {
  account_id: string;
  mode: string;
  suggestions: CreatorSuggestion[];
  count: number;
  cold_start: boolean;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID with imported Creator Center statistics"),
    mode: pi.zod.enum(["trend", "brief", "free"]).default("trend").describe("Creation mode to guide"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_creator_suggestions",
    label: "XHS Creator Suggestions",
    description:
      "Get trend, brief, or free-creation recommendations derived from an account's imported Creator Center statistics",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/creator-stats/${params.account_id}/suggestions`, {
          mode: params.mode,
        })) as CreatorSuggestionsResponse;
        const suggestions = Array.isArray(result.suggestions) ? result.suggestions : [];
        const lines = [`Creator Suggestions — ${params.account_id} (${result.mode || params.mode}):`];
        if (result.cold_start) {
          lines.push("  Note: this account is in cold start; recommendations use limited evidence.");
        }
        if (!suggestions.length) {
          lines.push("  No suggestions are available yet. Import and analyze Creator Center notes first.");
          return textResult(lines.join("\n"), { ...result });
        }
        for (const suggestion of suggestions) {
          const evidence = suggestion.evidence ? ` Evidence: ${suggestion.evidence}` : "";
          lines.push(
            `  - [P${suggestion.priority ?? "?"}] ${suggestion.title || suggestion.category || "Recommendation"}: ${suggestion.advice || ""}${evidence}`,
          );
        }
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get Creator Center suggestions: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
