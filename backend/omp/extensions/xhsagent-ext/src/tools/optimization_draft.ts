/** xhs_optimization_draft — generate optimization draft for content. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface OptimizationResponse {
  thread_id: string;
  status: string;
  optimization_analysis: Record<string, unknown>;
  draft_content: Record<string, unknown>;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_optimization_draft",
    label: "XHS Optimization Draft",
    description: "Generate an optimization draft for content at the optimization stage",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(`/optimization/draft/${params.thread_id}`)) as OptimizationResponse;

        const lines: string[] = [
          `Optimization Draft — ${params.thread_id}:`,
          `  Status: ${result.status}`,
        ];

        const analysis = result.optimization_analysis;
        if (analysis && Object.keys(analysis).length) {
          lines.push("  Analysis available");
        }

        const draft = result.draft_content;
        if (draft && Object.keys(draft).length) {
          const title = (draft as any).title || "";
          const body = (draft as any).body || "";
          if (title) lines.push(`  Title: ${title}`);
          if (body) lines.push(`  Body: ${typeof body === "string" ? body.slice(0, 500) : JSON.stringify(body).slice(0, 500)}`);
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to generate optimization draft: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
