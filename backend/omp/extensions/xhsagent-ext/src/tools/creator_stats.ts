/** xhs_creator_stats — inspect imported Creator Center account and note metrics. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface CreatorAccountStats {
  views: number;
  likes: number;
  comments: number;
  collects: number;
  shares: number;
  fans: number;
  note_count: number;
  period: string;
  synced_at: string;
  source: string;
}

interface CreatorNoteStats {
  note_id: string;
  title: string;
  views: number;
  likes: number;
  comments: number;
  collects: number;
  shares: number;
  engagement_rate: number;
}

interface CreatorStatsResponse {
  account_id: string;
  account: CreatorAccountStats | null;
  notes: CreatorNoteStats[];
  total: number;
}

function formatPercent(value: number | undefined): string {
  const rate = Number(value) || 0;
  return `${(rate <= 1 ? rate * 100 : rate).toFixed(2)}%`;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID with imported Creator Center statistics"),
    limit: pi.zod.number().default(20).describe("Maximum imported notes to inspect (1-200)"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_creator_stats",
    label: "XHS Creator Statistics",
    description:
      "Inspect imported Creator Center account and note metrics; summarizes engagement and top notes without triggering a live sync",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/creator-stats/${params.account_id}`, {
          limit: params.limit,
        })) as CreatorStatsResponse;
        const notes = Array.isArray(result.notes) ? result.notes : [];
        const lines = [`Creator Statistics — ${params.account_id}:`];

        if (result.account) {
          const account = result.account;
          lines.push(
            `  Account (${account.period || "unknown window"}): ${account.views || 0} views, ${account.likes || 0} likes, ${account.collects || 0} collects, ${account.comments || 0} comments, ${account.shares || 0} shares`,
            `  Followers: ${account.fans || 0}; reported notes: ${account.note_count || result.total || 0}; source: ${account.source || "unknown"}`,
          );
        }

        if (!notes.length) {
          lines.push("  No imported notes are available. Sync Creator Center statistics before analyzing content.");
          return textResult(lines.join("\n"), { ...result });
        }

        const averageRate = notes.reduce((sum, note) => sum + (Number(note.engagement_rate) || 0), 0) / notes.length;
        const topNotes = [...notes]
          .sort((a, b) => (Number(b.engagement_rate) || 0) - (Number(a.engagement_rate) || 0) || (b.views || 0) - (a.views || 0))
          .slice(0, 5);
        lines.push(`  Loaded: ${notes.length}/${result.total || notes.length} notes; average note engagement: ${formatPercent(averageRate)}`);
        lines.push("  Top notes by engagement:");
        for (const [index, note] of topNotes.entries()) {
          lines.push(
            `  ${index + 1}. ${note.title || "(untitled)"} — ${formatPercent(note.engagement_rate)}; ${note.views || 0} views; ❤️${note.likes || 0} ⭐${note.collects || 0} 💬${note.comments || 0}`,
          );
        }
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get Creator Center statistics: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
