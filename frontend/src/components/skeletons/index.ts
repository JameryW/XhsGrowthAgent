export { default as SkeletonLoader } from '@/components/SkeletonLoader.vue'
export { default as MetricCardSkeleton } from './MetricCardSkeleton.vue'
export { default as ContentCardSkeleton } from './ContentCardSkeleton.vue'
export { default as DataTableSkeleton } from './DataTableSkeleton.vue'
export { default as DashboardSkeleton } from './DashboardSkeleton.vue'
export { default as AnalyticsSkeletonComponent } from './AnalyticsSkeleton.vue'
export { default as ReviewSkeletonComponent } from './ReviewSkeleton.vue'
export { default as HomeSkeleton } from './HomeSkeleton.vue'

// NEW convenience wrappers using SkeletonLoader
import SkeletonLoader from '@/components/SkeletonLoader.vue'

export const ReviewSkeleton = {
  components: { SkeletonLoader },
  template: `
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SkeletonLoader type="card" :width="300" />
      <SkeletonLoader type="card" :width="300" />
    </div>
  `
}

export const AnalyticsSkeleton = {
  components: { SkeletonLoader },
  template: `
    <div class="space-y-4">
      <SkeletonLoader type="card" :width="600" />
      <SkeletonLoader type="list" />
    </div>
  `
}