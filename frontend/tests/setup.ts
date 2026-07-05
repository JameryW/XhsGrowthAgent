// ponytail: globally install i18n + pinia plugins so component tests that mount
// useI18n()-using components don't each need to repeat `plugins: [i18n]`.
// Without this, ~14 spec files fail with "Need to install with `app.use`".
import { config } from '@vue/test-utils'
import i18n from '@/locales'

config.global.plugins = [...(config.global.plugins ?? []), i18n]
