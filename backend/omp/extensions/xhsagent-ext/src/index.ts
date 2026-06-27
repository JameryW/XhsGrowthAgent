/**
 * xhsagent-ext — XhsGrowthAgent domain tools and commands for oh-my-pi.
 *
 * Registers 7 domain tools, 2 commands, and 2 event hooks that connect
 * omp to the XhsGrowthAgent Python API service.
 */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

import registerWorkflowStart from "./tools/workflow_start.js";
import registerWorkflowStatus from "./tools/workflow_status.js";
import registerWorkflowPause from "./tools/workflow_pause.js";
import registerWorkflowResume from "./tools/workflow_resume.js";
import registerWorkflowCancel from "./tools/workflow_cancel.js";
import registerReviewApprove from "./tools/review_approve.js";
import registerReviewReject from "./tools/review_reject.js";

import registerXhsCommand from "./commands/xhs.js";
import registerXhsReviewCommand from "./commands/xhs_review.js";

import registerEvents from "./events.js";

export default function xhsagentExt(pi: ExtensionAPI) {
  // Register domain tools
  registerWorkflowStart(pi);
  registerWorkflowStatus(pi);
  registerWorkflowPause(pi);
  registerWorkflowResume(pi);
  registerWorkflowCancel(pi);
  registerReviewApprove(pi);
  registerReviewReject(pi);

  // Register commands
  registerXhsCommand(pi);
  registerXhsReviewCommand(pi);

  // Register event hooks (API health check + agent context)
  registerEvents(pi);
}
