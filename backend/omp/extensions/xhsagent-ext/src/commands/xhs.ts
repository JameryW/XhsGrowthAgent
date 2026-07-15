/** /xhs command — free-create XHS content. */
import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.registerCommand("xhs", {
    description: "Free-create XHS content, evaluation, and publishing",
    async handler(args: string, _ctx: ExtensionCommandContext) {
      const topic = (args || "").trim();
      pi.sendUserMessage([
        "Create a Xiaohongshu (小红书) post in Free Creation mode.",
        topic ? `Topic: ${topic}` : "Ask clarifying questions or propose a topic before drafting.",
        "Do not start the fixed workflow from OMP; the fixed workflow belongs to Simple Mode in the web UI.",
        "Use the thread-less xhs_free_* tools (no workflow thread_id):",
        "  Create: draft title/body/hashtags/image prompts, then persist via xhs_free_draft_create → draft_id (reuse across evaluate/publish).",
        "  Evaluate: xhs_free_evaluate(draft_id) → RQGM quality verdict. If needs_revision/rejected, revise per revision_hints via xhs_free_draft_update (keep draft_id), then re-evaluate before publish.",
        "  Publish: xhs_free_publish(draft_id); then xhs_free_analytics(draft_id) for post-publish engagement.",
        "For existing workflow content with a thread_id, use xhs_review_approve or xhs_publish_retry instead.",
      ].join("\n"));
    },
  });
}
