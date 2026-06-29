/** xhs_optimization_select — select an optimization version. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface OptimizationSelectResponse {
  thread_id: string;
  status: string;
  next_phase: string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
    version_id: pi.zod.string().describe("Version ID to select (from content_versions)"),
    version_type: pi.zod.string().optional().describe("Version type: A/B/C"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_optimization_select",
    label: "XHS Optimization Select",
    description: "Select a specific optimization version to proceed with",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(`/optimization/select/${params.thread_id}`, {
          version_id: params.version_id,
          version_type: params.version_type,
        })) as OptimizationSelectResponse;
        return textResult(
          `Selected version ${params.version_id} for ${params.thread_id}. Status: ${result.status}, Next: ${result.next_phase}`,
          { ...result },
        );
      } catch (err) {
        return textResult(`Failed to select optimization version: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
