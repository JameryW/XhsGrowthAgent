import client from './client'
import type {
  PublicCase,
  PublicCaseListResponse,
  PublicFinalSummaryResponse,
  PublicReplayManifestResponse,
  PublicReplayStep,
} from '@/types/publicShowcase'

type RequestOptions = { suppressToast?: boolean; signal?: AbortSignal }

export type PublicReplayManifestOptions = RequestOptions & {
  limit?: number
  offset?: number
}

export interface PublicCaseQuery {
  limit?: number
  offset?: number
  q?: string
  mode?: 'trend' | 'brief'
  status?: 'completed' | 'in_progress' | 'attention'
  sort?: 'recent' | 'title'
}

export async function listPublicCases(
  params?: PublicCaseQuery,
  options?: RequestOptions,
): Promise<PublicCaseListResponse> {
  return client.get('/public/showcase/cases', { params, ...options }) as unknown as PublicCaseListResponse
}

export async function getPublicCase(
  publicId: string,
  options?: RequestOptions,
): Promise<PublicCase> {
  return client.get(`/public/showcase/cases/${encodeURIComponent(publicId)}`, options) as unknown as PublicCase
}

export async function getPublicReplayManifest(
  publicId: string,
  includeTechnical = false,
  options?: PublicReplayManifestOptions,
): Promise<PublicReplayManifestResponse> {
  const { limit, offset, ...requestOptions } = options || {}
  return client.get(`/public/replays/${encodeURIComponent(publicId)}/manifest`, {
    params: {
      include_technical: includeTechnical,
      ...(limit === undefined ? {} : { limit }),
      ...(offset === undefined ? {} : { offset }),
    },
    ...requestOptions,
  }) as unknown as PublicReplayManifestResponse
}

export async function getPublicReplayCheckpoint(
  publicId: string,
  checkpointPublicId: string,
  includeTechnical = false,
  options?: RequestOptions,
): Promise<PublicReplayStep> {
  return client.get(
    `/public/replays/${encodeURIComponent(publicId)}/checkpoints/${encodeURIComponent(checkpointPublicId)}`,
    {
      params: { include_technical: includeTechnical },
      ...options,
    },
  ) as unknown as PublicReplayStep
}

export async function getPublicFinalSummary(
  publicId: string,
  options?: RequestOptions,
): Promise<PublicFinalSummaryResponse> {
  return client.get(`/public/replays/${encodeURIComponent(publicId)}/final-summary`, options) as unknown as PublicFinalSummaryResponse
}
