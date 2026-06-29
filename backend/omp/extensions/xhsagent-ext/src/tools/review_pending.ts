/** xhs_review_pending — get content awaiting review at the review gate. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface ReviewPendingResponse {
  status: string;
  content_plan: Record<string, unknown>;
  copy_content: Record<string, unknown>;
  visual_plan: Record<string, unknown>;
  version_history: Record<string, unknown>[];
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_review_pending",
    label: "XHS Review Pending",
    description: "Get content awaiting review (only when workflow is at review gate). Use xhs_workflow_status first to check if review is pending.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/review/pending/${params.thread_id}`)) as ReviewPendingResponse;

        if (result.status !== "awaiting_review") {
          return textResult(`Workflow ${params.thread_id} is not at review gate.`, { thread_id: params.thread_id, status: result.status });
        }

        const lines: string[] = [
          `Content Pending Review — ${params.thread_id}:`,
        ];

        // Summarize available data sections
        const sections: string[] = [];
        if (result.copy_content && Object.keys(result.copy_content).length) sections.push("copy_content");
        if (result.visual_plan && Object.keys(result.visual_plan).length) sections.push("visual_plan");
        if (result.content_plan && Object.keys(result.content_plan).length) sections.push("content_plan");
        if (result.version_history && result.version_history.length) sections.push(`version_history (${result.version_history.length})`);
        if (sections.length) lines.push(`  Available: ${sections.join(", ")}`);

        // Include key fields inline for quick decision-making
        const draft = result.copy_content || {};
        const title = (draft as any).selected_title || (draft as any).title || "";
        const body = (draft as any).body_text || (draft as any).body || "";
        if (title) lines.push(`  Title: ${title}`);
        if (body) lines.push(`  Body: ${typeof body === "string" ? body.slice(0, 500) : JSON.stringify(body).slice(0, 500)}`);

        lines.push("", "Use xhs_review_approve or xhs_review_reject to make a decision.");

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get review content: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
