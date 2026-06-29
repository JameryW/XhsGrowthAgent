/** xhs_workflow_list — list workflows. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface WorkflowEntry {
  thread_id: string;
  phase: string;
  status: string;
  created_at: string;
  updated_at: string;
}

interface WorkflowListResponse {
  workflows: WorkflowEntry[];
  count: number;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({});

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_list",
    label: "XHS Workflow List",
    description: "List all workflows with their status and phase",
    parameters: schema,
    async execute(_id, _params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get("/workflow/list")) as WorkflowListResponse;

        if (!result.workflows?.length) {
          return textResult("No workflows found.");
        }

        const lines = [
          `Workflows (${result.count || result.workflows.length}):`,
          "",
          ...result.workflows.map((w) =>
            `  ${w.thread_id.slice(0, 8)}… | ${w.phase} | ${w.status} | ${w.updated_at || "N/A"}`
          ),
        ];

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to list workflows: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
