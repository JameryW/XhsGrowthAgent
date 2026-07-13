/** xhs_creator_quality — summarize historical creative quality from imported notes. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface QualityDimension {
  key?: string;
  score?: number;
  evidence?: string;
}

interface QualityInsight {
  dimension?: string;
  title?: string;
  evidence?: string;
  related_note_ids?: string[];
}

interface QualityRecommendation extends QualityInsight {
  priority?: number;
  advice?: string;
}

interface CreatorQualityResponse {
  account_id?: string;
  total_notes?: number;
  notes_analyzed?: number;
  scope?: string;
  overall_score?: number | null;
  grade?: string;
  confidence?: string;
  summary?: string;
  dimensions?: QualityDimension[];
  strengths?: QualityInsight[];
  weaknesses?: QualityInsight[];
  recommendations?: QualityRecommendation[];
  cold_start?: boolean;
  insufficient_data?: boolean;
}

function formatScore(score: number | null | undefined): string {
  if (typeof score !== "number" || !Number.isFinite(score)) return "not scored";
  return `${score.toFixed(Number.isInteger(score) ? 0 : 1)}/100`;
}

function insightLine(insight: QualityInsight, fallback: string): string {
  const title = insight.title || insight.dimension || fallback;
  return insight.evidence ? `${title} — ${insight.evidence}` : title;
}

function recommendationLine(recommendation: QualityRecommendation, index: number): string {
  const priority = Number.isFinite(recommendation.priority) ? recommendation.priority : index + 1;
  const title = recommendation.title || recommendation.dimension || "Action";
  const advice = recommendation.advice || recommendation.evidence || "Review this area in the next post.";
  const evidence = recommendation.evidence && recommendation.advice ? ` Evidence: ${recommendation.evidence}` : "";
  return `[P${priority}] ${title}: ${advice}${evidence}`;
}

function isInsufficientHistory(result: CreatorQualityResponse): boolean {
  const notesAnalyzed = Number(result.notes_analyzed) || 0;
  return Boolean(result.cold_start || result.insufficient_data || result.grade === "insufficient_data" || notesAnalyzed < 3);
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID with imported Creator Center note history"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_creator_quality",
    label: "XHS Historical Creative Quality",
    description:
      "Assess the overall creative-quality signal of an account's imported historical Creator Center notes, including strengths, gaps, and prioritized next-post actions without triggering a sync",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/creator-stats/${params.account_id}/quality?locale=en`)) as CreatorQualityResponse;
        const accountId = result.account_id || params.account_id;
        const notesAnalyzed = Number(result.notes_analyzed) || 0;
        const totalNotes = Number(result.total_notes) || 0;
        const lines = [`Historical Creative Quality — ${accountId}:`];

        if (isInsufficientHistory(result)) {
          lines.push(
            `  Imported history is not yet sufficient (${notesAnalyzed}/${totalNotes} notes analyzed). Import more Creator Center history before drawing quality conclusions.`,
            `  Overall: ${formatScore(result.overall_score)}; grade: ${result.grade || "insufficient_data"}; confidence: ${result.confidence || "low"}`,
          );
          if (result.scope) lines.push(`  Scope: ${result.scope}`);
          if (result.summary) lines.push(`  ${result.summary}`);
          const firstRecommendation = Array.isArray(result.recommendations)
            ? result.recommendations[0]
            : undefined;
          if (firstRecommendation) {
            lines.push(`  Next action: ${recommendationLine(firstRecommendation, 0)}`);
          }
          return textResult(lines.join("\n"), { ...result });
        }

        lines.push(
          `  Overall: ${formatScore(result.overall_score)}; grade: ${result.grade || "unknown"}; confidence: ${result.confidence || "unknown"}`,
          `  Scope: ${result.scope || "imported history"}; notes analyzed: ${notesAnalyzed}/${totalNotes}`,
        );
        if (result.summary) lines.push(`  Summary: ${result.summary}`);

        const strengths = Array.isArray(result.strengths) ? result.strengths : [];
        lines.push("  Strengths:");
        if (strengths.length) {
          for (const strength of strengths) lines.push(`  - ${insightLine(strength, "Strength")}`);
        } else {
          lines.push("  - No evidence-backed strengths were returned.");
        }

        const weaknesses = Array.isArray(result.weaknesses) ? result.weaknesses : [];
        lines.push("  Gaps:");
        if (weaknesses.length) {
          for (const weakness of weaknesses) lines.push(`  - ${insightLine(weakness, "Gap")}`);
        } else {
          lines.push("  - No evidence-backed gaps were returned.");
        }

        const recommendations = Array.isArray(result.recommendations) ? result.recommendations : [];
        lines.push("  Priority actions:");
        if (recommendations.length) {
          const priorityActions = recommendations
            .map((recommendation, index) => ({ recommendation, index }))
            .sort(
              (a, b) =>
                (a.recommendation.priority ?? Number.MAX_SAFE_INTEGER) -
                  (b.recommendation.priority ?? Number.MAX_SAFE_INTEGER) ||
                a.index - b.index,
            )
            .slice(0, 3);
          for (const { recommendation, index } of priorityActions) {
            lines.push(`  - ${recommendationLine(recommendation, index)}`);
          }
        } else {
          lines.push("  - No prioritized actions were returned.");
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get historical Creator Center quality report: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
