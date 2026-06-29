/** xhs_blogger_pending — get pending blogger candidates for a workflow. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface BloggerPendingResponse {
  thread_id: string;
  blogger_candidates: Array<{ user_id: string; nickname: string; note_count?: number; followers?: number }>;
  blogger_candidate_limit: number;
  blogger_note_limit: number;
  is_pending: boolean;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_blogger_pending",
    label: "XHS Blogger Pending",
    description: "Get blogger candidates (only when workflow is at blogger selection gate). Use xhs_workflow_status first to check.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/optimization/blogger-pending/${params.thread_id}`)) as BloggerPendingResponse;

        if (!result.is_pending) {
          return textResult(`Workflow ${params.thread_id} is not at blogger selection gate. Current state may not require blogger selection.`);
        }

        const candidates = result.blogger_candidates;
        if (!candidates.length) {
          return textResult("No blogger candidates available.", { thread_id: params.thread_id });
        }

        const lines = [
          `Blogger Candidates for ${params.thread_id}:`,
          `  Limit: ${result.blogger_candidate_limit}, Notes per blogger: ${result.blogger_note_limit}`,
          "",
          ...candidates.map((c, i) => `  ${i + 1}. ${c.nickname} (ID: ${c.user_id})${c.followers ? ` — ${c.followers} followers` : ""}${c.note_count ? ` — ${c.note_count} notes` : ""}`),
          "",
          "Use xhs_blogger_select to choose one, or pass skip=true to skip.",
        ];
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get blogger candidates: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
