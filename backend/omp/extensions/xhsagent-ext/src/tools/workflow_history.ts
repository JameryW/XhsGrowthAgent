/** xhs_workflow_history — get checkpoint history for a workflow. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface CheckpointEntry {
  checkpoint_id: string;
  step: number;
  source: string;
  phase: string;
  current_agent: string;
  created_at: string | null;
  next_nodes: string[];
}

interface HistoryResponse {
  thread_id: string;
  checkpoints: CheckpointEntry[];
  has_more: boolean;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
    limit: pi.zod.number().default(20).describe("Max checkpoints to return (1-100)"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_history",
    label: "XHS Workflow History",
    description: "Get checkpoint history for a workflow (execution timeline with phase/agent transitions)",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/workflow/history/${params.thread_id}`, {
          limit: params.limit,
        })) as HistoryResponse;

        if (!result.checkpoints?.length) {
          return textResult(`No history found for workflow ${params.thread_id}.`, { thread_id: params.thread_id });
        }

        const lines = [
          `Workflow History — ${params.thread_id} (${result.checkpoints.length} checkpoints${result.has_more ? ", more available" : ""}):`,
          "",
          ...result.checkpoints.map((c) => {
            const time = c.created_at || "N/A";
            return `  Step ${c.step} | ${c.phase} | ${c.current_agent || "—"} | ${time}`;
          }),
        ];

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get history: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
