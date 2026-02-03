const DEFAULT_TTL_MS = 30 * 1000
const USER_TTL_MS = 5 * 60 * 1000 // 用户数据缓存 5 分钟

const makeEntry = (data) => ({ data, ts: Date.now() })

const isFresh = (entry, ttlMs) => {
  if (!entry) return false
  return Date.now() - entry.ts < ttlMs
}

const getEntry = (map, key, ttlMs = DEFAULT_TTL_MS) => {
  const entry = map.get(key)
  if (!isFresh(entry, ttlMs)) return null
  return entry.data
}

const setEntry = (map, key, data) => {
  map.set(key, makeEntry(data))
  return data
}

const threadsList = new Map()
const threadDetail = new Map()
const adminUsersList = new Map()

let statsEntry = null
let currentUserEntry = null

export const getThreadsListCacheKey = (page, pageSize) => `${page}:${pageSize}`
export const getThreadDetailCacheKey = (id, page, pageSize) => `${id}:${page}:${pageSize}`
export const getUsersListCacheKey = (page, pageSize) => `${page}:${pageSize}`

export const getThreadsListCache = (page, pageSize, ttlMs) => getEntry(threadsList, getThreadsListCacheKey(page, pageSize), ttlMs)
export const setThreadsListCache = (page, pageSize, data) => setEntry(threadsList, getThreadsListCacheKey(page, pageSize), data)
export const clearThreadsListCache = () => threadsList.clear()

export const getThreadDetailCache = (id, page, pageSize, ttlMs) => getEntry(threadDetail, getThreadDetailCacheKey(id, page, pageSize), ttlMs)
export const setThreadDetailCache = (id, page, pageSize, data) => setEntry(threadDetail, getThreadDetailCacheKey(id, page, pageSize), data)

export const getAdminUsersCache = (page, pageSize, ttlMs) => getEntry(adminUsersList, getUsersListCacheKey(page, pageSize), ttlMs)
export const setAdminUsersCache = (page, pageSize, data) => setEntry(adminUsersList, getUsersListCacheKey(page, pageSize), data)

export const getStatsCache = (ttlMs = DEFAULT_TTL_MS) => {
  if (!isFresh(statsEntry, ttlMs)) return null
  return statsEntry.data
}
export const setStatsCache = (data) => {
  statsEntry = makeEntry(data)
  return data
}

export const getCurrentUserCache = (ttlMs = USER_TTL_MS) => {
  if (!isFresh(currentUserEntry, ttlMs)) return null
  return currentUserEntry.data
}
export const setCurrentUserCache = (data) => {
  currentUserEntry = makeEntry(data)
  return data
}

export const clearAllCache = () => {
  threadsList.clear()
  threadDetail.clear()
  adminUsersList.clear()
  statsEntry = null
  currentUserEntry = null
}

