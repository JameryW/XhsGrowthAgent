import axios, { AxiosInstance, AxiosError } from 'axios'

// 创建 axios 实例
const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
client.interceptors.request.use(
  (config) => {
    // 可添加认证 token
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
client.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError) => {
    console.error('API Error:', error.message)
    return Promise.reject(error)
  }
)

export default client