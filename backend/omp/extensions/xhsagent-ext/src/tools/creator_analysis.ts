/** xhs_creator_analysis — run the backend's deterministic analysis on imported notes. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface CreatorFinding {
  finding_type: string;
  label: string;
  evidence: string;
  score: number;
  sample_count: number;
}

interface CreatorSuggestion {
  category: string;
  title: string;
  advice: string;
  evidence: string;
}

interface CreatorAnalysisResponse {
  analysis: {
    account_id: string;
    note_count: number;
    avg_engagement_rate: number;
    findings: CreatorFinding[];
  };
  suggestions: Record<string, CreatorSuggestion[]>;
}

function formatPercent(value: number | undefined): string {
  const rate = Number(value) || 0;
  return `${(rate <= 1 ? rate * 100 : rate).toFixed(2)}%`;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID with imported Creator Center statistics"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_creator_analysis",
    label: "XHS Creator Data Analysis",
    description:
      "Analyze imported Creator Center notes for engagement patterns, style findings, and actionable recommendations",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/creator-stats/${params.account_id}/analysis`)) as CreatorAnalysisResponse;
        const analysis = result.analysis;
        const findings = Array.isArray(analysis?.findings) ? analysis.findings : [];
        const lines = [
          `Creator Data Analysis — ${params.account_id}:`,
          `  Notes analyzed: ${analysis?.note_count || 0}; average engagement: ${formatPercent(analysis?.avg_engagement_rate)}`,
        ];

        if (!findings.length) {
          lines.push("  No evidence-backed findings yet. Import more notes for a stronger analysis.");
        } else {
          lines.push("  Findings:");
          for (const finding of findings.slice(0, 8)) {
            const evidence = finding.evidence ? ` — ${finding.evidence}` : "";
            lines.push(
              `  - [${finding.finding_type || "pattern"}] ${finding.label || "unnamed"}${evidence} (score ${Number(finding.score || 0).toFixed(3)}, n=${finding.sample_count || 0})`,
            );
          }
        }

        const suggestions = result.suggestions || {};
        for (const [mode, items] of Object.entries(suggestions)) {
          if (!items?.length) continue;
          lines.push(`  ${mode} recommendations:`);
          for (const suggestion of items.slice(0, 2)) {
            lines.push(`  - ${suggestion.title || suggestion.category || "Recommendation"}: ${suggestion.advice || suggestion.evidence || ""}`);
          }
        }
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to analyze Creator Center data: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
