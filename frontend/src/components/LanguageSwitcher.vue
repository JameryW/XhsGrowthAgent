<script setup lang="ts">
import { useLanguageStore } from '@/stores/language'

const languageStore = useLanguageStore()
</script>

<template>
  <div class="flex items-center gap-1">
    <button
      @click="languageStore.setLanguage('zh-CN')"
      :class="[
        'px-2 py-1 rounded text-xs font-medium transition-all',
        languageStore.currentLocale === 'zh-CN'
          ? 'bg-teal-500 text-white'
          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
      ]"
    >
      中
    </button>
    <button
      @click="languageStore.setLanguage('en')"
      :class="[
        'px-2 py-1 rounded text-xs font-medium transition-all',
        languageStore.currentLocale === 'en'
          ? 'bg-teal-500 text-white'
          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
      ]"
    >
      EN
    </button>
  </div>
</template>
