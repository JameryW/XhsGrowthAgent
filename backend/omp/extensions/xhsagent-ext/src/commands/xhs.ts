/** /xhs command — free-orchestrate XHS content creation. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs", {
    description: "Free-orchestrate XHS content creation, evaluation, and publishing",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const topic = (args || "").trim();
      pi.sendUserMessage([
        "Free-orchestrate a Xiaohongshu (小红书) content post.",
        topic ? `Topic: ${topic}` : "Ask clarifying questions or propose a topic before drafting.",
        "Do not start the fixed workflow from OMP; the fixed workflow belongs to Simple Mode in the web UI.",
        "Create: draft titles, body copy, hashtags, and image prompts directly in the conversation.",
        "Evaluate: check AI taste, image quality, commercial tone, compliance, reach, and audience fit. Use xhs_evaluation_run/result only when a workflow thread_id exists.",
        "Publish: for existing workflow content, use xhs_review_approve or xhs_publish_retry; otherwise prepare publish-ready copy and ask the user before publishing.",
      ].join("\n"));
    },
  });
}
