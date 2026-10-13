// src/composables/useDynamicFavicon.js
// 动态切换 favicon 的 composable

import { watch } from 'vue'
import { AI_ROLES } from '@/utils/aiRoles'

/**
 * 设置 favicon
 * @param {string} href - favicon 路径
 */
const setFavicon = (href) => {
  // 查找现有的 favicon 链接
  let link = document.querySelector('link[rel*="icon"]')
  
  // 如果不存在，创建一个新的
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  
  // 更新 favicon 路径
  link.href = href
}

/**
 * 根据角色获取对应的 favicon 路径
 * @param {string} roleId - 角色 ID
 * @returns {string} favicon 路径
 */
const getFaviconByRole = (roleId) => {
  const role = AI_ROLES[roleId]
  if (role && role.icons && role.icons.favicon) {
    return role.icons.favicon
  }
  // 默认返回通用 favicon
  return '/favicon.svg'
}

/**
 * 使用动态 favicon
 * @param {Ref<string>} currentRole - 当前角色的响应式引用
 */
export const useDynamicFavicon = (currentRole) => {
  // 监听角色变化，自动切换 favicon
  watch(
    currentRole,
    (newRole) => {
      const faviconPath = getFaviconByRole(newRole)
      setFavicon(faviconPath)
    },
    { immediate: true } // 立即执行一次，设置初始 favicon
  )
}

export default useDynamicFavicon
