import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

export const useLanguageStore = defineStore('language', () => {
  const currentLocale = ref(localStorage.getItem('language') || 'zh-CN')
  const { locale } = useI18n()

  function setLanguage(lang: 'zh-CN' | 'en') {
    currentLocale.value = lang
    locale.value = lang
    localStorage.setItem('language', lang)
  }

  return { currentLocale, setLanguage }
})
