import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listConsoleUsers,
  createConsoleUser as apiCreate,
  changeConsoleUserPassword as apiChangePwd,
  deleteConsoleUser as apiDelete,
  type ConsoleUser,
} from '@/api/console_users'

export const useConsoleUsersStore = defineStore('console-users', () => {
  const users = ref<ConsoleUser[]>([])
  const isLoading = ref(false)

  async function fetchUsers() {
    isLoading.value = true
    try {
      users.value = await listConsoleUsers()
    } finally {
      isLoading.value = false
    }
  }

  async function createUser(username: string, password: string) {
    const u = await apiCreate(username, password)
    users.value.push(u)
    return u
  }

  async function changePassword(userId: string, password: string) {
    await apiChangePwd(userId, password)
  }

  async function removeUser(userId: string) {
    await apiDelete(userId)
    users.value = users.value.filter(u => u.id !== userId)
  }

  return { users, isLoading, fetchUsers, createUser, changePassword, removeUser }
})
