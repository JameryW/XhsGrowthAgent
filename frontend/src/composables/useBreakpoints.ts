import { ref, onMounted, onUnmounted } from 'vue'

const MOBILE_QUERY = '(max-width: 767px)'
const TABLET_QUERY = '(min-width: 768px) and (max-width: 1023px)'

export function useBreakpoints() {
  const isMobile = ref(false)
  const isTablet = ref(false)
  const isDesktop = ref(true)

  let mobileMq: MediaQueryList
  let tabletMq: MediaQueryList

  const update = () => {
    isMobile.value = mobileMq.matches
    isTablet.value = tabletMq.matches
    isDesktop.value = !mobileMq.matches && !tabletMq.matches
  }

  onMounted(() => {
    mobileMq = window.matchMedia(MOBILE_QUERY)
    tabletMq = window.matchMedia(TABLET_QUERY)
    update()
    mobileMq.addEventListener('change', update)
    tabletMq.addEventListener('change', update)
  })

  onUnmounted(() => {
    mobileMq?.removeEventListener('change', update)
    tabletMq?.removeEventListener('change', update)
  })

  return { isMobile, isTablet, isDesktop }
}
