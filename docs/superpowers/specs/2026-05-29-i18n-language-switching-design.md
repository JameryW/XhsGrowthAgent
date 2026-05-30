# 国际化（i18n）语言切换设计

**日期：** 2026-05-29  
**状态：** 已批准  
**范围：** 前端全部用户可见文本

---

## 1. 目标

解决前端中英文混杂问题，支持中英文切换，提升用户体验。

**当前状态：**
- 408 处中文文本
- 部分英文标签（APPROVE、REVISE、REJECT、PENDING_APPROVAL 等）
- 混杂在视图、组件、toast 消息、错误提示中

**目标状态：**
- 统一使用中文作为默认语言
- 支持切换到英文
- 用户语言偏好持久化到 localStorage

---

## 2. 技术方案

### 2.1 依赖

- `vue-i18n@9` — Vue 官方 i18n 方案
- `@intlify/unplugin-vue-i18n` — 编译时优化（可选，减少包体积）

### 2.2 翻译文件结构

```
src/locales/
├── zh-CN.json          # 中文翻译
├── en.json             # 英文翻译
└── index.ts            # i18n 配置
```

翻译键按视图/组件分组：

**中文翻译（zh-CN.json）：**

```json
{
  "common": {
    "loading": "加载中...",
    "error": "错误",
    "success": "成功",
    "cancel": "取消",
    "confirm": "确认",
    "save": "保存",
    "delete": "删除"
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
    }
  },
  "nav": {
    "home": "首页",
    "dashboard": "工作流",
    "review": "审核",
    "analytics": "分析"
  },
  "home": {
    "title": "小红书增长引擎",
    "subtitle": "AI驱动的自动化内容创作平台",
    "startWorkflow": "启动新工作流",
    "viewDashboard": "查看现有工作流"
  },
  "dashboard": {
    "title": "工作流仪表盘",
    "status": "状态",
    "phase": "阶段",
    "progress": "进度"
  },
  "review": {
    "title": "内容审核",
    "subtitle": "等待您的决定",
    "pendingApproval": "待审批",
    "copyContent": "文案内容",
    "visualPlan": "视觉方案",
    "actions": "审核操作",
    "feedbackInput": "反馈输入",
    "approve": "批准",
    "approveDesc": "直接发布",
    "revise": "修改",
    "reviseDesc": "要求修改",
    "reject": "拒绝",
    "rejectDesc": "放弃内容",
    "feedbackPlaceholder": "请输入审核意见或修改建议...",
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
    "cancelSuccess": "操作已取消",
    "cancelMessage": "您可以继续审核内容"
  },
  "analytics": {
    "title": "数据分析中心",
    "postsPublished": "已发布帖子",
    "aiCost": "AI 费用 (USD)",
    "thisWeek": "本周",
    "thisMonth": "本月",
    "thisYear": "全年",
    "interactionTrend": "互动趋势",
    "recentPosts": "最近帖子表现",
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
    }
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
    "lostMessage": "网络连接丢失，部分功能可能不可用"
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
    "awaitingReviewMessage": "工作流已暂停，请前往审核页面查看并决定"
  }
}
```

**英文翻译（en.json）：**

```json
{
  "common": {
    "loading": "Loading...",
    "error": "Error",
    "success": "Success",
    "cancel": "Cancel",
    "confirm": "Confirm",
    "save": "Save",
    "delete": "Delete"
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
    }
  },
  "nav": {
    "home": "Home",
    "dashboard": "Workflow",
    "review": "Review",
    "analytics": "Analytics"
  },
  "home": {
    "title": "XHS Growth Engine",
    "subtitle": "AI-powered automated content creation platform",
    "startWorkflow": "Start New Workflow",
    "viewDashboard": "View Dashboard"
  },
  "dashboard": {
    "title": "Workflow Dashboard",
    "status": "Status",
    "phase": "Phase",
    "progress": "Progress"
  },
  "review": {
    "title": "Content Review",
    "subtitle": "Awaiting Your Decision",
    "pendingApproval": "PENDING_APPROVAL",
    "copyContent": "Copy Content",
    "visualPlan": "Visual Plan",
    "actions": "Review Actions",
    "feedbackInput": "Feedback Input",
    "approve": "APPROVE",
    "approveDesc": "Publish directly",
    "revise": "REVISE",
    "reviseDesc": "Request changes",
    "reject": "REJECT",
    "rejectDesc": "Discard content",
    "feedbackPlaceholder": "Enter review comments or suggestions...",
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
    "cancelSuccess": "Action cancelled",
    "cancelMessage": "You can continue reviewing the content"
  },
  "analytics": {
    "title": "Analytics Center",
    "postsPublished": "Posts Published",
    "aiCost": "AI Cost (USD)",
    "thisWeek": "This Week",
    "thisMonth": "This Month",
    "thisYear": "This Year",
    "interactionTrend": "Interaction Trend",
    "recentPosts": "Recent Post Performance",
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
    }
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
    "lostMessage": "Network connection lost, some features may be unavailable"
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
    "awaitingReviewMessage": "Workflow paused, please review and decide"
  }
}
```

---

## 3. 架构设计

### 3.1 i18n 配置

```typescript
// src/locales/index.ts
import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN.json'
import en from './en.json'

const i18n = createI18n({
  legacy: false,          // 使用 Composition API
  locale: localStorage.getItem('language') || 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en': en
  }
})

export default i18n
```

### 3.2 语言切换 Store

```typescript
// src/stores/language.ts
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

### 3.3 语言切换组件

```vue
<!-- src/components/LanguageSwitcher.vue -->
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

### 3.4 组件使用方式

```vue
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>

<template>
  <h1>{{ t('login.title') }}</h1>
  <p>{{ t('login.subtitle') }}</p>
</template>
```

---

## 4. 需要修改的文件

### 4.1 新增文件

| 文件 | 用途 |
|------|------|
| `src/locales/zh-CN.json` | 中文翻译 |
| `src/locales/en.json` | 英文翻译 |
| `src/locales/index.ts` | i18n 配置 |
| `src/stores/language.ts` | 语言状态管理 |
| `src/components/LanguageSwitcher.vue` | 语言切换组件 |

### 4.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/main.ts` | 注册 vue-i18n 插件 |
| `src/App.vue` | 添加 LanguageSwitcher 组件 |
| `src/views/Login.vue` | 替换硬编码文本 |
| `src/views/Home.vue` | 替换硬编码文本 |
| `src/views/Dashboard.vue` | 替换硬编码文本 |
| `src/views/Review.vue` | 替换硬编码文本 |
| `src/views/Analytics.vue` | 替换硬编码文本 |
| `src/views/NotFound.vue` | 替换硬编码文本 |
| `src/components/ConnectionStatus.vue` | 替换硬编码文本 |
| `src/components/OfflineRecovery.vue` | 替换硬编码文本 |
| `src/stores/workflow.ts` | 替换 toast 消息 |
| `src/stores/review.ts` | 替换 toast 消息 |
| `src/stores/toast.ts` | 替换默认消息 |

---

## 5. UI 布局

语言切换器位于顶部状态栏右侧，与连接状态并排显示：

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  [左侧导航]           [主内容区]           [中] [EN] ●实时连接 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 持久化策略

- **存储位置：** `localStorage`，键名为 `language`
- **默认值：** `zh-CN`（中文）
- **恢复时机：** 应用启动时从 localStorage 读取
- **更新时机：** 用户切换语言时立即保存

---

## 7. 实现顺序

1. 安装 vue-i18n 依赖
2. 创建翻译文件（zh-CN.json、en.json）
3. 创建 i18n 配置
4. 创建语言切换 Store
5. 创建语言切换组件
6. 注册 i18n 插件
7. 修改 App.vue 添加切换器
8. 逐个视图替换硬编码文本
9. 逐个组件替换硬编码文本
10. 替换 store 中的 toast 消息

---

## 8. 验证标准

- [ ] 默认显示中文
- [ ] 点击 EN 切换到英文
- [ ] 点击 中 切换回中文
- [ ] 刷新页面后语言偏好保持
- [ ] 所有页面文本正确显示对应语言
- [ ] toast 消息正确显示对应语言
- [ ] 无中英文混杂现象
