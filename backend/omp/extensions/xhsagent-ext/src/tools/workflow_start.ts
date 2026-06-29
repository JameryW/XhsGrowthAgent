/** xhs_workflow_start — start a workflow, subscribe to SSE for real-time progress. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post, subscribeSSE, checkApiHealth } from "../api_client.js";
import { config } from "../config.js";
import { textResult } from "../types.js";
import type { WorkflowStartResponse } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("XHS account ID to run the workflow for"),
    workflow_mode: pi.zod.enum(["trend", "brief"]).default("trend").describe("Workflow mode: trend-based or brief-based"),
    topic: pi.zod.string().optional().describe("Topic or niche to focus on (optional)"),
    async_mode: pi.zod.boolean().default(true).describe("Run workflow asynchronously with SSE progress"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_start",
    label: "XHS Workflow Start",
    description: "Start a XHS content creation workflow with real-time SSE progress",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      // Graceful degradation: check API first
      const healthy = await checkApiHealth();
      if (!healthy) {
        return textResult(
          "XhsGrowthAgent API is not available.\n" +
          "Make sure the API server is running: `xhs-growth serve --port 8000`\n" +
          `Current API base: ${process.env.XHS_AGENT_API_BASE || "http://localhost:8000"}`,
          undefined, true,
        );
      }

      try {
        const body: Record<string, unknown> = {
          account_id: params.account_id,
          workflow_mode: params.workflow_mode,
          async_mode: params.async_mode,
        };
        if (params.topic) body.topic = params.topic;

        const result = (await post("/workflow/start", body)) as WorkflowStartResponse;
        pi.logger.debug("xhs_workflow_start succeeded", { thread_id: result.thread_id, mode: params.workflow_mode });

        // If async mode, subscribe to SSE for real-time progress
        if (params.async_mode && result.thread_id) {
          const sse = subscribeSSE(
            result.thread_id,
            () => {},
          );

          try {
            await Promise.race([
              sse.promise,
              new Promise<void>((_, reject) =>
                setTimeout(() => reject(new Error("SSE timeout")), config.sseTimeout),
              ),
            ]);
          } catch {
            sse.close();
          }
        }

        return textResult(
          `Workflow started!\n` +
          `Thread: ${result.thread_id}\n` +
          `Phase: ${result.phase}\n` +
          `Status: ${result.status}\n` +
          `Mode: ${params.workflow_mode}`,
          { thread_id: result.thread_id, phase: result.phase, status: result.status },
        );
      } catch (err) {
        pi.logger.warn("xhs_workflow_start failed", { error: (err as Error).message });
        return textResult(`Failed to start workflow: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
