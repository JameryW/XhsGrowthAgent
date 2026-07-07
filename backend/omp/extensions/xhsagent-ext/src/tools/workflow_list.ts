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
  total: number;
  limit: number;
  offset: number;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().optional().describe("Filter by account ID"),
    status: pi.zod.string().optional().describe("Filter by status: running/completed/error/cancelled"),
    limit: pi.zod.number().optional().describe("Max workflows to return (1-100, default 20)"),
    offset: pi.zod.number().optional().describe("Pagination offset"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_list",
    label: "XHS Workflow List",
    description: "List workflows with their status and phase (filterable by account/status)",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const query: Record<string, unknown> = {};
        if (params.account_id) query.account_id = params.account_id;
        if (params.status) query.status = params.status;
        if (params.limit) query.limit = params.limit;
        if (params.offset) query.offset = params.offset;
        const result = (await get("/workflow/list", query)) as WorkflowListResponse;

        if (!result.workflows?.length) {
          return textResult("No workflows found.");
        }

        const lines = [
          `Workflows (${result.total ?? result.workflows.length}):`,
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
