/**
 * xhsagent-ext — XhsGrowthAgent domain tools and commands for oh-my-pi.
 *
 * Registers XHS domain tools, commands, and event hooks that connect omp to the
 * XhsGrowthAgent Python API service.
 */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

import registerWorkflowStatus from "./tools/workflow_status.js";
import registerWorkflowPause from "./tools/workflow_pause.js";
import registerWorkflowResume from "./tools/workflow_resume.js";
import registerWorkflowCancel from "./tools/workflow_cancel.js";
import registerWorkflowList from "./tools/workflow_list.js";
import registerWorkflowDelete from "./tools/workflow_delete.js";
import registerWorkflowHistory from "./tools/workflow_history.js";
import registerWorkflowTriggerAnalytics from "./tools/workflow_trigger_analytics.js";
import registerPublishRetry from "./tools/publish_retry.js";
import registerReviewApprove from "./tools/review_approve.js";
import registerReviewReject from "./tools/review_reject.js";
import registerReviewPending from "./tools/review_pending.js";
import registerReviewVersions from "./tools/review_versions.js";
import registerEvaluationResult from "./tools/evaluation_result.js";
import registerEvaluationRun from "./tools/evaluation_run.js";
import registerEvaluationEpochs from "./tools/evaluation_epochs.js";
import registerEvaluationWeights from "./tools/evaluation_weights.js";
import registerEvaluationSamples from "./tools/evaluation_samples.js";
import registerEvaluationTrend from "./tools/evaluation_trend.js";
import registerRipplePending from "./tools/ripple_pending.js";
import registerRippleDecision from "./tools/ripple_decision.js";
import registerRippleRetry from "./tools/ripple_retry.js";
import registerBloggerPending from "./tools/blogger_pending.js";
import registerBloggerSelect from "./tools/blogger_select.js";
import registerOptimizationDraft from "./tools/optimization_draft.js";
import registerOptimizationSelect from "./tools/optimization_select.js";
import registerAnalyticsDashboard from "./tools/analytics_dashboard.js";
import registerAnalyticsCosts from "./tools/analytics_costs.js";
import registerAnalyticsReport from "./tools/analytics_report.js";
import registerAnalyticsPerformance from "./tools/analytics_performance.js";
import registerCreatorStats from "./tools/creator_stats.js";
import registerCreatorAnalysis from "./tools/creator_analysis.js";
import registerCreatorSuggestions from "./tools/creator_suggestions.js";
import registerCreatorQuality from "./tools/creator_quality.js";
import registerSystemHealth from "./tools/system_health.js";

import registerXhsCommand from "./commands/xhs.js";
import registerXhsReviewCommand from "./commands/xhs_review.js";
import registerXhsAnalyticsCommand from "./commands/xhs_analytics.js";
import registerXhsEvaluateCommand from "./commands/xhs_evaluate.js";

import registerEvents from "./events.js";

export default function xhsagentExt(pi: ExtensionAPI) {
  // Workflow tools
  registerWorkflowStatus(pi);
  registerWorkflowPause(pi);
  registerWorkflowResume(pi);
  registerWorkflowCancel(pi);
  registerWorkflowList(pi);
  registerWorkflowDelete(pi);
  registerWorkflowHistory(pi);
  registerWorkflowTriggerAnalytics(pi);
  registerPublishRetry(pi);

  // Review tools
  registerReviewApprove(pi);
  registerReviewReject(pi);
  registerReviewPending(pi);
  registerReviewVersions(pi);

  // Evaluation tools (RQGM agent-as-a-judge)
  registerEvaluationResult(pi);
  registerEvaluationRun(pi);
  registerEvaluationEpochs(pi);
  registerEvaluationWeights(pi);
  registerEvaluationSamples(pi);
  registerEvaluationTrend(pi);

  // Ripple tools
  registerRipplePending(pi);
  registerRippleDecision(pi);
  registerRippleRetry(pi);

  // Blogger selection tools
  registerBloggerPending(pi);
  registerBloggerSelect(pi);

  // Optimization tools
  registerOptimizationDraft(pi);
  registerOptimizationSelect(pi);

  // Analytics tools
  registerAnalyticsDashboard(pi);
  registerAnalyticsCosts(pi);
  registerAnalyticsReport(pi);
  registerAnalyticsPerformance(pi);
  registerCreatorStats(pi);
  registerCreatorAnalysis(pi);
  registerCreatorSuggestions(pi);
  registerCreatorQuality(pi);

  // System tools
  registerSystemHealth(pi);

  // Commands
  registerXhsCommand(pi);
  registerXhsReviewCommand(pi);
  registerXhsAnalyticsCommand(pi);
  registerXhsEvaluateCommand(pi);

  // Event hooks (API health check + agent context)
  registerEvents(pi);
}
