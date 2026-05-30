# i18n 语言切换实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现中英文语言切换功能，解决前端中英文混杂问题

**Architecture:** 使用 vue-i18n@9 实现国际化，翻译文件按视图/组件分组，语言偏好持久化到 localStorage

**Tech Stack:** vue-i18n@9, Pinia, Vue 3 Composition API

---

## 文件结构

```
src/locales/
├── zh-CN.json          # 中文翻译
├── en.json             # 英文翻译
└── index.ts            # i18n 配置

src/stores/
└── language.ts         # 语言状态管理

src/components/
└── LanguageSwitcher.vue # 语言切换组件
```

---

### Task 1: 安装 vue-i18n 依赖

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: 安装 vue-i18n**

```bash
cd /test/xhs/frontend && npm install vue-i18n@9
```

- [ ] **Step 2: 验证安装**

```bash
cd /test/xhs/frontend && npm ls vue-i18n
```

Expected: `vue-i18n@9.x.x`

- [ ] **Step 3: 提交**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "deps: add vue-i18n@9 for i18n support"
```

---

### Task 2: 创建中文翻译文件

**Files:**
- Create: `frontend/src/locales/zh-CN.json`

- [ ] **Step 1: 创建中文翻译文件**

```json
{
  "common": {
    "loading": "加载中...",
    "error": "错误",
    "success": "成功",
    "cancel": "取消",
    "confirm": "确认",
    "save": "保存",
    "delete": "删除",
    "retry": "重试",
    "close": "关闭"
  },
  "login": {
    "title": "登录",
    "subtitle": "小红书增长引擎",
    "username": "用户名",
    "password": "密码",
    "usernamePlaceholder": "请输入用户名",
    "passwordPlaceholder": "请输入密码",
    "submit": "登录",
    "error": {
      "usernameRequired": "请输入用户名",
      "passwordRequired": "请输入密码",
      "loginFailed": "登录失败，请重试"
    },
    "dismissError": "关闭错误提示",
    "version": "小红书增长引擎 v0.1.0"
  },
  "nav": {
    "home": "首页",
    "dashboard": "工作流仪表盘",
    "review": "内容审核",
    "analytics": "数据分析",
    "startWorkflow": "启动新工作流",
    "logout": "退出登录",
    "phase": "阶段",
    "account": "账户",
    "version": "版本"
  },
  "home": {
    "title": "小红书增长引擎",
    "subtitle": "AI驱动的自动化内容创作平台",
    "startWorkflow": "启动新工作流",
    "viewDashboard": "查看现有工作流",
    "systemStatus": "系统状态",
    "account": "账户",
    "phase": "阶段",
    "loadingOverlay": "正在执行 {phase} 阶段..."
  },
  "dashboard": {
    "title": "工作流仪表盘",
    "completed": "工作流完成",
    "completedMessage": "内容已成功发布到小红书"
  },
  "review": {
    "title": "内容审核",
    "subtitle": "等待您的决定",
    "pendingApproval": "待审批",
    "copyContent": "文案内容",
    "copyContentEn": "Copy Content",
    "visualPlan": "视觉方案",
    "visualPlanEn": "Visual Plan",
    "actions": "审核操作",
    "selectAction": "SELECT_ACTION",
    "feedbackInput": "反馈输入",
    "feedbackLabel": "FEEDBACK_INPUT",
    "approve": "批准",
    "approveDesc": "直接发布",
    "revise": "修改",
    "reviseDesc": "要求修改",
    "reject": "拒绝",
    "rejectDesc": "放弃内容",
    "feedbackPlaceholder": "请输入审核意见或修改建议...",
    "feedbackAriaLabel": "审核意见输入框",
    "confirmReject": {
      "title": "确认拒绝内容",
      "message": "拒绝后内容将被放弃，此操作不可撤销。确定要拒绝这篇内容吗？",
      "action": "内容将被标记为\"已拒绝\"，工作流将结束。"
    },
    "confirmApprove": {
      "title": "确认批准内容",
      "message": "批准后内容将进入发布流程。确定内容已准备好发布吗？",
      "action": "内容将被标记为\"已批准\"，进入发布阶段。"
    },
    "success": "审核完成",
    "decisionLabel": "决定",
    "submitFailed": "提交失败，请重试",
    "submitFailedTitle": "提交失败",
    "cancelSuccess": "操作已取消",
    "cancelMessage": "您可以继续审核内容"
  },
  "analytics": {
    "title": "数据分析中心",
    "analyticsLabel": "Analytics",
    "postsPublished": "已发布帖子",
    "totalEngagement": "总互动量",
    "avgEngagementRate": "平均互动率",
    "aiCost": "AI 费用 (USD)",
    "thisWeek": "本周",
    "thisMonth": "本月",
    "thisYear": "全年",
    "interactionTrend": "互动趋势",
    "recentPosts": "最近帖子表现",
    "top10": "TOP 10",
    "table": {
      "title": "标题",
      "likes": "点赞",
      "comments": "评论",
      "collects": "收藏",
      "engagementRate": "互动率",
      "publishedAt": "发布时间"
    },
    "weekdays": {
      "mon": "周一",
      "tue": "周二",
      "wed": "周三",
      "thu": "周四",
      "fri": "周五",
      "sat": "周六",
      "sun": "周日"
    },
    "categories": {
      "likes": "点赞",
      "comments": "评论",
      "collects": "收藏",
      "shares": "分享"
    },
    "week": "本周",
    "month": "本月",
    "year": "全年"
  },
  "connection": {
    "connected": "实时连接",
    "connecting": "连接中...",
    "reconnecting": "重连中...",
    "disconnected": "已断开"
  },
  "offline": {
    "recovered": "连接恢复",
    "recoveredMessage": "网络已恢复，可以继续操作",
    "lost": "离线状态",
    "lostMessage": "网络连接丢失，部分功能可能不可用",
    "networkDisconnected": "网络连接已断开",
    "checkNetwork": "请检查网络设置",
    "warning": "网络离线警告"
  },
  "notFound": {
    "title": "404",
    "message": "页面不存在 · 请返回首页继续操作",
    "backHome": "返回首页",
    "backPrev": "返回上页"
  },
  "workflow": {
    "completed": "工作流完成",
    "completedMessage": "内容已成功发布到小红书",
    "error": "工作流错误",
    "phaseChange": "阶段切换",
    "awaitingReview": "等待审核",
    "awaitingReviewMessage": "工作流已暂停，请前往审核页面查看并决定",
    "startSuccess": "工作流启动成功",
    "startFailed": "启动失败",
    "paused": "工作流已暂停",
    "pauseFailed": "暂停失败",
    "resumed": "工作流已恢复",
    "resumeFailed": "恢复失败",
    "statusRefreshFailed": "状态刷新失败",
    "currentPhase": "当前阶段",
    "currentAgent": "当前 Agent",
    "thread": "Thread"
  },
  "help": {
    "center": "帮助中心",
    "menu": "帮助菜单",
    "faq": "常见问题",
    "shortcuts": "快捷键",
    "feedback": "反馈建议"
  },
  "loading": {
    "processing": "正在处理...",
    "cancel": "取消操作"
  },
  "draft": {
    "title": "提交草稿内容",
    "draftBody": "草稿正文",
    "required": "*",
    "placeholder": "输入您的笔记正文内容（至少50字）...",
    "minLength": "正文内容至少需要50字",
    "charCount": "{count} 字",
    "titleLabel": "标题（可选）",
    "titlePlaceholder": "笔记标题...",
    "tagsLabel": "话题标签（可选）",
    "tagsPlaceholder": "#美食 #探店 或 逗号分隔...",
    "viralLinksLabel": "提供爆款参考链接（可选）",
    "viralLinksPlaceholder": "粘贴小红书笔记链接，每行一个...",
    "linksCount": "{count} 个链接",
    "startOptimization": "开始优化分析",
    "skipOptimization": "跳过优化",
    "validContent": "内容长度满足要求",
    "needMoreChars": "还需 {count} 字",
    "enterContent": "请输入正文内容",
    "contentTooShort": "内容太短，至少需要 50 字"
  }
}
```

- [ ] **Step 2: 验证 JSON 格式**

```bash
cd /test/xhs/frontend && node -e "JSON.parse(require('fs').readFileSync('src/locales/zh-CN.json', 'utf8')); console.log('Valid JSON')"
```

Expected: `Valid JSON`

- [ ] **Step 3: 提交**

```bash
git add frontend/src/locales/zh-CN.json
git commit -m "feat: add Chinese translation file"
```

---

### Task 3: 创建英文翻译文件

**Files:**
- Create: `frontend/src/locales/en.json`

- [ ] **Step 1: 创建英文翻译文件**

```json
{
  "common": {
    "loading": "Loading...",
    "error": "Error",
    "success": "Success",
    "cancel": "Cancel",
    "confirm": "Confirm",
    "save": "Save",
    "delete": "Delete",
    "retry": "Retry",
    "close": "Close"
  },
  "login": {
    "title": "Login",
    "subtitle": "XHS Growth Engine",
    "username": "Username",
    "password": "Password",
    "usernamePlaceholder": "Enter username",
    "passwordPlaceholder": "Enter password",
    "submit": "Login",
    "error": {
      "usernameRequired": "Please enter username",
      "passwordRequired": "Please enter password",
      "loginFailed": "Login failed, please try again"
    },
    "dismissError": "Dismiss error",
    "version": "XHS Growth Engine v0.1.0"
  },
  "nav": {
    "home": "Home",
    "dashboard": "Workflow Dashboard",
    "review": "Content Review",
    "analytics": "Analytics",
    "startWorkflow": "Start New Workflow",
    "logout": "Logout",
    "phase": "Phase",
    "account": "Account",
    "version": "Version"
  },
  "home": {
    "title": "XHS Growth Engine",
    "subtitle": "AI-powered automated content creation platform",
    "startWorkflow": "Start New Workflow",
    "viewDashboard": "View Dashboard",
    "systemStatus": "System Status",
    "account": "Account",
    "phase": "Phase",
    "loadingOverlay": "Executing {phase} phase..."
  },
  "dashboard": {
    "title": "Workflow Dashboard",
    "completed": "Workflow Completed",
    "completedMessage": "Content published to Xiaohongshu successfully"
  },
  "review": {
    "title": "Content Review",
    "subtitle": "Awaiting Your Decision",
    "pendingApproval": "PENDING_APPROVAL",
    "copyContent": "文案内容",
    "copyContentEn": "Copy Content",
    "visualPlan": "视觉方案",
    "visualPlanEn": "Visual Plan",
    "actions": "Review Actions",
    "selectAction": "SELECT_ACTION",
    "feedbackInput": "Feedback Input",
    "feedbackLabel": "FEEDBACK_INPUT",
    "approve": "APPROVE",
    "approveDesc": "Publish directly",
    "revise": "REVISE",
    "reviseDesc": "Request changes",
    "reject": "REJECT",
    "rejectDesc": "Discard content",
    "feedbackPlaceholder": "Enter review comments or suggestions...",
    "feedbackAriaLabel": "Review comments input",
    "confirmReject": {
      "title": "Confirm Rejection",
      "message": "Rejected content will be discarded. This action cannot be undone. Are you sure?",
      "action": "Content will be marked as \"rejected\" and the workflow will end."
    },
    "confirmApprove": {
      "title": "Confirm Approval",
      "message": "Approved content will proceed to publishing. Is the content ready?",
      "action": "Content will be marked as \"approved\" and enter the publishing phase."
    },
    "success": "Review completed",
    "decisionLabel": "Decision",
    "submitFailed": "Submit failed, please try again",
    "submitFailedTitle": "Submit Failed",
    "cancelSuccess": "Action cancelled",
    "cancelMessage": "You can continue reviewing the content"
  },
  "analytics": {
    "title": "Analytics Center",
    "analyticsLabel": "Analytics",
    "postsPublished": "Posts Published",
    "totalEngagement": "Total Engagement",
    "avgEngagementRate": "Avg Engagement Rate",
    "aiCost": "AI Cost (USD)",
    "thisWeek": "This Week",
    "thisMonth": "This Month",
    "thisYear": "This Year",
    "interactionTrend": "Interaction Trend",
    "recentPosts": "Recent Post Performance",
    "top10": "TOP 10",
    "table": {
      "title": "Title",
      "likes": "Likes",
      "comments": "Comments",
      "collects": "Collects",
      "engagementRate": "Engagement Rate",
      "publishedAt": "Published At"
    },
    "weekdays": {
      "mon": "Mon",
      "tue": "Tue",
      "wed": "Wed",
      "thu": "Thu",
      "fri": "Fri",
      "sat": "Sat",
      "sun": "Sun"
    },
    "categories": {
      "likes": "Likes",
      "comments": "Comments",
      "collects": "Collects",
      "shares": "Shares"
    },
    "week": "This Week",
    "month": "This Month",
    "year": "This Year"
  },
  "connection": {
    "connected": "Connected",
    "connecting": "Connecting...",
    "reconnecting": "Reconnecting...",
    "disconnected": "Disconnected"
  },
  "offline": {
    "recovered": "Connection Restored",
    "recoveredMessage": "Network is back, you can continue",
    "lost": "Offline",
    "lostMessage": "Network connection lost, some features may be unavailable",
    "networkDisconnected": "Network connection lost",
    "checkNetwork": "Please check network settings",
    "warning": "Network Offline Warning"
  },
  "notFound": {
    "title": "404",
    "message": "Page not found · Please return to home",
    "backHome": "Back to Home",
    "backPrev": "Go Back"
  },
  "workflow": {
    "completed": "Workflow Completed",
    "completedMessage": "Content published to Xiaohongshu successfully",
    "error": "Workflow Error",
    "phaseChange": "Phase Changed",
    "awaitingReview": "Awaiting Review",
    "awaitingReviewMessage": "Workflow paused, please review and decide",
    "startSuccess": "Workflow started successfully",
    "startFailed": "Start failed",
    "paused": "Workflow paused",
    "pauseFailed": "Pause failed",
    "resumed": "Workflow resumed",
    "resumeFailed": "Resume failed",
    "statusRefreshFailed": "Status refresh failed",
    "currentPhase": "Current Phase",
    "currentAgent": "Current Agent",
    "thread": "Thread"
  },
  "help": {
    "center": "Help Center",
    "menu": "Help Menu",
    "faq": "FAQ",
    "shortcuts": "Shortcuts",
    "feedback": "Feedback"
  },
  "loading": {
    "processing": "Processing...",
    "cancel": "Cancel"
  },
  "draft": {
    "title": "Submit Draft Content",
    "draftBody": "Draft Body",
    "required": "*",
    "placeholder": "Enter your note content (at least 50 characters)...",
    "minLength": "Content requires at least 50 characters",
    "charCount": "{count} characters",
    "titleLabel": "Title (optional)",
    "titlePlaceholder": "Note title...",
    "tagsLabel": "Tags (optional)",
    "tagsPlaceholder": "#food #travel or comma separated...",
    "viralLinksLabel": "Provide viral reference links (optional)",
    "viralLinksPlaceholder": "Paste Xiaohongshu note links, one per line...",
    "linksCount": "{count} links",
    "startOptimization": "Start Optimization",
    "skipOptimization": "Skip Optimization",
    "validContent": "Content length meets requirements",
    "needMoreChars": "Need {count} more characters",
    "enterContent": "Please enter content",
    "contentTooShort": "Content too short, need at least 50 characters"
  }
}
```

- [ ] **Step 2: 验证 JSON 格式**

```bash
cd /test/xhs/frontend && node -e "JSON.parse(require('fs').readFileSync('src/locales/en.json', 'utf8')); console.log('Valid JSON')"
```

Expected: `Valid JSON`

- [ ] **Step 3: 提交**

```bash
git add frontend/src/locales/en.json
git commit -m "feat: add English translation file"
```

---

### Task 4: 创建 i18n 配置

**Files:**
- Create: `frontend/src/locales/index.ts`

- [ ] **Step 1: 创建 i18n 配置文件**

```typescript
import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN.json'
import en from './en.json'

const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('language') || 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en': en
  }
})

export default i18n
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/locales/index.ts
git commit -m "feat: create i18n configuration"
```

---

### Task 5: 创建语言切换 Store

**Files:**
- Create: `frontend/src/stores/language.ts`

- [ ] **Step 1: 创建语言切换 Store**

```typescript
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
```

- [ ] **Step 2: 更新 stores/index.ts 导出**

读取 `frontend/src/stores/index.ts` 并添加 language store 导出。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/stores/language.ts frontend/src/stores/index.ts
git commit -m "feat: create language store with persistence"
```

---

### Task 6: 创建语言切换组件

**Files:**
- Create: `frontend/src/components/LanguageSwitcher.vue`

- [ ] **Step 1: 创建语言切换组件**

```vue
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
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/LanguageSwitcher.vue
git commit -m "feat: create language switcher component"
```

---

### Task 7: 注册 i18n 插件并更新 App.vue

**Files:**
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 更新 main.ts 注册 i18n**

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import i18n from './locales'
import './styles/main.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)

app.mount('#app')
```

- [ ] **Step 2: 更新 App.vue 添加 LanguageSwitcher**

在 `App.vue` 的 `<ConnectionStatus />` 旁边添加 `<LanguageSwitcher />`。

需要：
1. 导入 LanguageSwitcher 组件
2. 在 ConnectionStatus 旁边添加 LanguageSwitcher

- [ ] **Step 3: 提交**

```bash
git add frontend/src/main.ts frontend/src/App.vue
git commit -m "feat: register i18n plugin and add language switcher to App"
```

---

### Task 8: 国际化 Login.vue

**Files:**
- Modify: `frontend/src/views/Login.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

替换所有中文文本为 `t('login.xxx')` 调用：
- `登录` → `{{ t('login.title') }}`
- `小红书增长引擎` → `{{ t('login.subtitle') }}`
- `用户名` → `{{ t('login.username') }}`
- `密码` → `{{ t('login.password') }}`
- `请输入用户名` → `{{ t('login.usernamePlaceholder') }}`
- `请输入密码` → `{{ t('login.passwordPlaceholder') }}`
- 错误消息使用 `t('login.error.xxx')`
- `关闭错误提示` → `{{ t('login.dismissError') }}`
- `小红书增长引擎 v0.1.0` → `{{ t('login.version') }}`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Login.vue
git commit -m "feat: internationalize Login.vue"
```

---

### Task 9: 国际化 Home.vue

**Files:**
- Modify: `frontend/src/views/Home.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

替换所有中文文本为 `t('home.xxx')` 调用：
- `小红书增长引擎` → `{{ t('home.title') }}`
- `AI驱动的自动化内容创作平台` → `{{ t('home.subtitle') }}`
- `启动新工作流` → `{{ t('home.startWorkflow') }}`
- `查看现有工作流` → `{{ t('home.viewDashboard') }}`
- `工作流启动面板` → `{{ t('home.systemStatus') }}`
- `正在执行 ${workflowStore.currentPhase} 阶段...` → 使用 `t('home.loadingOverlay', { phase: workflowStore.currentPhase })`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Home.vue
git commit -m "feat: internationalize Home.vue"
```

---

### Task 10: 国际化 Dashboard.vue

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

替换 toast 消息：
- `toastStore.success('工作流完成', '内容已成功发布到小红书')` → `toastStore.success(t('dashboard.completed'), t('dashboard.completedMessage'))`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Dashboard.vue
git commit -m "feat: internationalize Dashboard.vue"
```

---

### Task 11: 国际化 Review.vue

**Files:**
- Modify: `frontend/src/views/Review.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

替换所有中文和英文文本：
- `确认拒绝内容` → `t('review.confirmReject.title')`
- `拒绝后内容将被放弃...` → `t('review.confirmReject.message')`
- `内容将被标记为"已拒绝"...` → `t('review.confirmReject.action')`
- `确认批准内容` → `t('review.confirmApprove.title')`
- `批准后内容将进入发布流程...` → `t('review.confirmApprove.message')`
- `内容将被标记为"已批准"...` → `t('review.confirmApprove.action')`
- `审核完成` → `t('review.success')`
- `决定: ${decision}` → `${t('review.decisionLabel')}: ${decision}`
- `提交失败，请重试` → `t('review.submitFailed')`
- `提交失败` → `t('review.submitFailedTitle')`
- `操作已取消` → `t('review.cancelSuccess')`
- `您可以继续审核内容` → `t('review.cancelMessage')`
- `PENDING_APPROVAL` → `{{ t('review.pendingApproval') }}`
- `内容审核 · 等待您的决定` → `{{ t('review.title') }} · {{ t('review.subtitle') }}`
- `文案内容` → `{{ t('review.copyContent') }}`
- `Copy Content` → `{{ t('review.copyContentEn') }}`
- `视觉方案` → `{{ t('review.visualPlan') }}`
- `Visual Plan` → `{{ t('review.visualPlanEn') }}`
- `审核操作` → `{{ t('review.actions') }}`
- `SELECT_ACTION` → `{{ t('review.selectAction') }}`
- `APPROVE` → `{{ t('review.approve') }}`
- `直接发布` → `{{ t('review.approveDesc') }}`
- `REVISE` → `{{ t('review.revise') }}`
- `要求修改` → `{{ t('review.reviseDesc') }}`
- `REJECT` → `{{ t('review.reject') }}`
- `放弃内容` → `{{ t('review.rejectDesc') }}`
- `反馈输入` → `{{ t('review.feedbackInput') }}`
- `FEEDBACK_INPUT` → `{{ t('review.feedbackLabel') }}`
- `审核意见输入框` → `{{ t('review.feedbackAriaLabel') }}`
- `请输入审核意见或修改建议...` → `{{ t('review.feedbackPlaceholder') }}`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Review.vue
git commit -m "feat: internationalize Review.vue"
```

---

### Task 12: 国际化 Analytics.vue

**Files:**
- Modify: `frontend/src/views/Analytics.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

替换所有中文和英文文本：
- `POSTS_PUBLISHED` → `t('analytics.postsPublished')`
- `TOTAL_ENGAGEMENT` → `t('analytics.totalEngagement')`
- `AVG_ENGAGEMENT_RATE` → `t('analytics.avgEngagementRate')`
- `AI_COST_USD` → `t('analytics.aiCost')`
- `本周` → `t('analytics.thisWeek')`
- `数据分析中心` → `{{ t('analytics.title') }}`
- `Analytics` → `{{ t('analytics.analyticsLabel') }}`
- `本周`/`本月`/`全年` → `t('analytics.week')`/`t('analytics.month')`/`t('analytics.year')`
- `互动趋势` → `{{ t('analytics.interactionTrend') }}`
- `最近帖子表现` → `{{ t('analytics.recentPosts') }}`
- `TOP 10` → `{{ t('analytics.top10') }}`
- 表格列标签使用 `t('analytics.table.xxx')`
- 星期使用 `t('analytics.weekdays.xxx')`
- 分类使用 `t('analytics.categories.xxx')`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Analytics.vue
git commit -m "feat: internationalize Analytics.vue"
```

---

### Task 13: 国际化 NotFound.vue

**Files:**
- Modify: `frontend/src/views/NotFound.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

- `页面不存在 · 请返回首页继续操作` → `{{ t('notFound.message') }}`
- `返回首页` → `{{ t('notFound.backHome') }}`
- `返回上页` → `{{ t('notFound.backPrev') }}`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/NotFound.vue
git commit -m "feat: internationalize NotFound.vue"
```

---

### Task 14: 国际化 ConnectionStatus.vue

**Files:**
- Modify: `frontend/src/components/ConnectionStatus.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

替换 `statusStyles` 中的 `text` 属性：
- `实时连接` → `t('connection.connected')`
- `连接中...` → `t('connection.connecting')`
- `重连中...` → `t('connection.reconnecting')`
- `已断开` → `t('connection.disconnected')`

注意：由于 `statusStyles` 是一个对象，需要改为 computed 或在模板中使用 `t()`。

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/ConnectionStatus.vue
git commit -m "feat: internationalize ConnectionStatus.vue"
```

---

### Task 15: 国际化 OfflineRecovery.vue

**Files:**
- Modify: `frontend/src/components/OfflineRecovery.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

- `toastStore.success('连接恢复', '网络已恢复，可以继续操作')` → `toastStore.success(t('offline.recovered'), t('offline.recoveredMessage'))`
- `toastStore.warning('离线状态', '网络连接丢失，部分功能可能不可用')` → `toastStore.warning(t('offline.lost'), t('offline.lostMessage'))`
- `网络离线警告` → `{{ t('offline.warning') }}`
- `网络连接已断开` → `{{ t('offline.networkDisconnected') }}`
- `请检查网络设置` → `{{ t('offline.checkNetwork') }}`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/OfflineRecovery.vue
git commit -m "feat: internationalize OfflineRecovery.vue"
```

---

### Task 16: 国际化 Navbar.vue

**Files:**
- Modify: `frontend/src/components/Navbar.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

- 导航项标签使用 `t('nav.dashboard')`、`t('nav.review')`、`t('nav.analytics')`
- `增长引擎` → `{{ t('nav.home') }}` 或保持原样
- `启动新工作流` → `{{ t('nav.startWorkflow') }}`
- `退出登录` → `{{ t('nav.logout') }}`
- `主导航` → `{{ t('nav.home') }}`
- `当前工作流阶段` → `{{ t('nav.phase') }}`
- `Account` → `{{ t('nav.account') }}`
- `Version` → `{{ t('nav.version') }}`

注意：`navItems` 数组需要改为 computed。

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/Navbar.vue
git commit -m "feat: internationalize Navbar.vue"
```

---

### Task 17: 国际化 HelpCenter.vue

**Files:**
- Modify: `frontend/src/components/HelpCenter.vue`

- [ ] **Step 1: 添加 useI18n 导入**

```typescript
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```

- [ ] **Step 2: 替换硬编码文本**

- `帮助中心` → `{{ t('help.center') }}`
- `帮助菜单` → `{{ t('help.menu') }}`
- `常见问题` → `{{ t('help.faq') }}`
- `快捷键` → `{{ t('help.shortcuts') }}`
- `反馈建议` → `{{ t('help.feedback') }}`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/HelpCenter.vue
git commit -m "feat: internationalize HelpCenter.vue"
```

---

### Task 18: 国际化 workflow store

**Files:**
- Modify: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: 添加 useI18n 导入**

由于 store 中不能直接使用 `useI18n()`，需要导入 i18n 实例：

```typescript
import i18n from '@/locales'
const { t } = i18n.global
```

- [ ] **Step 2: 替换硬编码文本**

替换所有 toast 消息：
- `等待审核` → `t('workflow.awaitingReview')`
- `工作流已暂停，请前往审核页面查看并决定` → `t('workflow.awaitingReviewMessage')`
- `阶段切换: ${p.old_phase} → ${newPhase}` → `${t('workflow.phaseChange')}: ${p.old_phase} → ${newPhase}`
- `当前 Agent: ${p.current_agent}` → `${t('workflow.currentAgent')}: ${p.current_agent}`
- `工作流完成` → `t('workflow.completed')`
- `Thread: ${p.thread_id}` → `${t('workflow.thread')}: ${p.thread_id}`
- `工作流错误` → `t('workflow.error')`
- `Agent: ${p.agent} - ${p.error}` → `${t('workflow.currentAgent')}: ${p.agent} - ${p.error}`
- `工作流启动成功` → `t('workflow.startSuccess')`
- `启动失败` → `t('workflow.startFailed')`
- `工作流已暂停` → `t('workflow.paused')`
- `暂停失败` → `t('workflow.pauseFailed')`
- `工作流已恢复` → `t('workflow.resumed')`
- `当前阶段: ${workflowState.value?.phase}` → `${t('workflow.currentPhase')}: ${workflowState.value?.phase}`
- `状态刷新失败` → `t('workflow.statusRefreshFailed')`

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "feat: internationalize workflow store"
```

---

### Task 19: 国际化 auth store

**Files:**
- Modify: `frontend/src/stores/auth.ts`

- [ ] **Step 1: 添加 i18n 导入**

```typescript
import i18n from '@/locales'
const { t } = i18n.global
```

- [ ] **Step 2: 替换硬编码文本**

- `登录成功` → `t('login.submit') + t('common.success')` 或直接使用新的翻译键
- `欢迎回来，${result.user.username}` → 可以保持或使用翻译
- `登录失败` → `t('login.error.loginFailed')`
- `请检查用户名和密码` → 可以保持或使用翻译
- `已退出` → 可以保持或使用翻译
- `请重新登录以继续使用` → 可以保持或使用翻译

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/stores/auth.ts
git commit -m "feat: internationalize auth store"
```

---

### Task 20: 国际化其他组件（LoadingOverlay、DraftInput、CircularProgress）

**Files:**
- Modify: `frontend/src/components/LoadingOverlay.vue`
- Modify: `frontend/src/components/DraftInput.vue`
- Modify: `frontend/src/components/CircularProgress.vue`

- [ ] **Step 1: 国际化 LoadingOverlay.vue**

添加 useI18n 并替换：
- `正在处理...` → `{{ t('loading.processing') }}`
- `取消操作` → `{{ t('loading.cancel') }}`

- [ ] **Step 2: 国际化 DraftInput.vue**

添加 useI18n 并替换所有中文文本。

- [ ] **Step 3: 国际化 CircularProgress.vue**

添加 useI18n 并替换 `进度 ${Math.round(percentage)}%`。

- [ ] **Step 4: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/LoadingOverlay.vue frontend/src/components/DraftInput.vue frontend/src/components/CircularProgress.vue
git commit -m "feat: internationalize LoadingOverlay, DraftInput, CircularProgress"
```

---

### Task 21: 国际化剩余 store（offline、analytics）

**Files:**
- Modify: `frontend/src/stores/offline.ts`
- Modify: `frontend/src/stores/analytics.ts`

- [ ] **Step 1: 国际化 offline store**

添加 i18n 导入并替换所有 toast 消息。

- [ ] **Step 2: 国际化 analytics store**

添加 i18n 导入并替换所有 toast 消息。

- [ ] **Step 3: 验证构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/stores/offline.ts frontend/src/stores/analytics.ts
git commit -m "feat: internationalize offline and analytics stores"
```

---

### Task 22: 最终验证

- [ ] **Step 1: 运行类型检查**

```bash
cd /test/xhs/frontend && npm run type-check
```

Expected: 无新增错误

- [ ] **Step 2: 运行构建**

```bash
cd /test/xhs/frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 3: 运行测试**

```bash
cd /test/xhs/frontend && npm run test:run
```

Expected: 所有测试通过

- [ ] **Step 4: 提交最终更改**

```bash
git add -A
git commit -m "feat: complete i18n implementation for all frontend components"
```

---

## 验证清单

- [ ] 默认显示中文
- [ ] 点击 EN 切换到英文
- [ ] 点击 中 切换回中文
- [ ] 刷新页面后语言偏好保持
- [ ] 所有页面文本正确显示对应语言
- [ ] toast 消息正确显示对应语言
- [ ] 无中英文混杂现象
