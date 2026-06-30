import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN.json'

// ponytail: 默认 locale 静态打入 entry（避免首屏异步闪烁）；非默认 locale 懒加载，从 entry chunk 剥离。
// en.json (~48K) 不再阻塞首屏，切到 en 时按需拉取。
const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('language') || 'zh-CN',
  fallbackLocale: 'zh-CN',
  // en 占位空对象（运行时由 loadLocaleMessages 懒加载填充），保留 locale 字面量联合类型。
  messages: {
    'zh-CN': zhCN,
    'en': {},
  },
})

const loaded: Record<string, boolean> = { 'zh-CN': true }

/** 按需加载某 locale 的消息；若已加载则跳过。切换语言时调用。 */
export async function loadLocaleMessages(locale: string): Promise<void> {
  if (loaded[locale]) return
  if (locale === 'en') {
    const en = await import('./en.json')
    i18n.global.setLocaleMessage('en', en.default)
    loaded['en'] = true
  }
}

// 启动时若用户存的是非默认 locale，异步补加载（首屏先用 fallback，加载后切换，避免阻塞 mount）
const initialLocale = localStorage.getItem('language') || 'zh-CN'
if (initialLocale !== 'zh-CN') {
  loadLocaleMessages(initialLocale).then(() => {
    i18n.global.locale.value = initialLocale as 'zh-CN' | 'en'
  })
}

export default i18n
