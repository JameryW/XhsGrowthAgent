// D6 / EV-04: single source of truth for evaluation score thresholds and
// dimension weights. Frontend scoring tiers mirror backend defaults
// (backend/db/evaluator_config.py can override per account); when the backend
// returns thresholds/weights with /evaluation/result, prefer those.
//
// ponytail: plain constants, no class. If per-account override lands, the
// result payload carries the values and callers skip these defaults.

export const SCORE_THRESHOLDS: ScoreThresholds = {
  pass: 70,
  warn: 50,
}

/**
 * Default weighted dimensions used by the backend evaluator.
 *
 * The API may return account-specific overrides in `weights`; this map is the
 * honest fallback for older responses and for surfaces that only have a
 * historical evaluation payload. `bias_check` is deliberately absent because
 * it is a separate penalty signal, not part of the weighted average.
 */
export const DEFAULT_DIMENSION_WEIGHTS: Readonly<Record<string, number>> = {
  copywriting: 0.18,
  visual: 0.13,
  compliance: 0.14,
  reach: 0.13,
  audience: 0.13,
  ai_taste: 0.08,
  image_quality: 0.07,
  commercial_tone: 0.05,
  altruism: 0.09,
}

export type ScoreTier = 'pass' | 'warn' | 'fail' | 'none'

export interface ScoreThresholds {
  pass: number
  warn: number
}

export function scoreTier(
  score: number | null | undefined,
  thresholds: ScoreThresholds = SCORE_THRESHOLDS,
): ScoreTier {
  if (score === null || score === undefined || !Number.isFinite(score)) return 'none'
  if (score >= thresholds.pass) return 'pass'
  if (score >= thresholds.warn) return 'warn'
  return 'fail'
}

// D7: dimensions excluded from the weighted radar (shown separately instead).
// bias_check's bias_severity is inversely related to score, so it must not
// share the radar's scale.
export const RADAR_EXCLUDED_DIMENSIONS = ['bias_check']

// EV-10: single source for dimension → i18n label key. Consumers (EvaluationView,
// Review, CreatorNoteQualityPanel, EvaluationRadar) all read this map instead of
// each maintaining a copy. The map covers label/tooltip text only — it is NOT a
// declaration of the full dimension set (the backend can vary dimensions).
export const DIMENSION_LABEL_KEYS: Record<string, string> = {
  copywriting: 'evaluation.dim.copywriting',
  visual: 'evaluation.dim.visual',
  compliance: 'evaluation.dim.compliance',
  reach: 'evaluation.dim.reach',
  audience: 'evaluation.dim.audience',
  ai_taste: 'evaluation.dim.ai_taste',
  image_quality: 'evaluation.dim.image_quality',
  commercial_tone: 'evaluation.dim.commercial_tone',
  altruism: 'evaluation.dim.altruism',
  bias_check: 'evaluation.dim.bias_check',
}
