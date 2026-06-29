/**
 * xhsagent-ext — XhsGrowthAgent domain tools and commands for oh-my-pi.
 *
 * Registers 17 domain tools, 3 commands, and 2 event hooks that connect
 * omp to the XhsGrowthAgent Python API service.
 */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

import registerWorkflowStart from "./tools/workflow_start.js";
import registerWorkflowStatus from "./tools/workflow_status.js";
import registerWorkflowPause from "./tools/workflow_pause.js";
import registerWorkflowResume from "./tools/workflow_resume.js";
import registerWorkflowCancel from "./tools/workflow_cancel.js";
import registerWorkflowList from "./tools/workflow_list.js";
import registerWorkflowDelete from "./tools/workflow_delete.js";
import registerReviewApprove from "./tools/review_approve.js";
import registerReviewReject from "./tools/review_reject.js";
import registerReviewPending from "./tools/review_pending.js";
import registerReviewVersions from "./tools/review_versions.js";
import registerBloggerPending from "./tools/blogger_pending.js";
import registerBloggerSelect from "./tools/blogger_select.js";
import registerOptimizationDraft from "./tools/optimization_draft.js";
import registerOptimizationSelect from "./tools/optimization_select.js";
import registerAnalyticsDashboard from "./tools/analytics_dashboard.js";
import registerAnalyticsCosts from "./tools/analytics_costs.js";
import registerSystemHealth from "./tools/system_health.js";

import registerXhsCommand from "./commands/xhs.js";
import registerXhsReviewCommand from "./commands/xhs_review.js";
import registerXhsAnalyticsCommand from "./commands/xhs_analytics.js";

import registerEvents from "./events.js";

export default function xhsagentExt(pi: ExtensionAPI) {
  // Workflow tools
  registerWorkflowStart(pi);
  registerWorkflowStatus(pi);
  registerWorkflowPause(pi);
  registerWorkflowResume(pi);
  registerWorkflowCancel(pi);
  registerWorkflowList(pi);
  registerWorkflowDelete(pi);

  // Review tools
  registerReviewApprove(pi);
  registerReviewReject(pi);
  registerReviewPending(pi);
  registerReviewVersions(pi);

  // Blogger selection tools
  registerBloggerPending(pi);
  registerBloggerSelect(pi);

  // Optimization tools
  registerOptimizationDraft(pi);
  registerOptimizationSelect(pi);

  // Analytics tools
  registerAnalyticsDashboard(pi);
  registerAnalyticsCosts(pi);

  // System tools
  registerSystemHealth(pi);

  // Commands
  registerXhsCommand(pi);
  registerXhsReviewCommand(pi);
  registerXhsAnalyticsCommand(pi);

  // Event hooks (API health check + agent context)
  registerEvents(pi);
}
