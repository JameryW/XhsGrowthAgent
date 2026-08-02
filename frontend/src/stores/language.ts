import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import i18n, { loadLocaleMessages } from '@/locales'

export const useLanguageStore = defineStore('language', () => {
  const currentLocale = ref(localStorage.getItem('language') || 'zh-CN')
  const { locale } = useI18n()

  async function setLanguage(lang: 'zh-CN' | 'en') {
    // 按需加载目标 locale 消息（懒加载的 locale 首次切换时拉取），再切换。
    await loadLocaleMessages(lang)
    currentLocale.value = lang
    i18n.global.locale.value = lang
    locale.value = lang
    localStorage.setItem('language', lang)
    // 保持 <html lang> 与实际界面语言一致（可访问性/朗读/输入法）。
    document.documentElement.lang = lang
  }

  return { currentLocale, setLanguage }
})
