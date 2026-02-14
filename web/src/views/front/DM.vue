<template>
  <div class="dm-page">
    <div class="dm-shell glass-card">
      <aside class="conversation-panel" :class="{ hidden: isMobile && mobileShowChat }">
        <div class="panel-header">
          <div class="title-wrap">
            <h2>聊天</h2>
            <span class="count">{{ filteredConversations.length }}</span>
            <span
              class="live-status"
              :class="{ online: sseConnected, connecting: sseConnecting }"
              :title="sseError || '私聊实时连接状态'"
            >
              <span class="dot"></span>
              {{ sseConnected ? '实时中' : (sseConnecting ? '连接中' : '已断开') }}
            </span>
          </div>
          <button class="icon-btn" @click="loadConversations" :disabled="listLoading" title="刷新会话">
            <el-icon><Refresh /></el-icon>
          </button>
        </div>

        <div class="search-box">
          <el-icon><Search /></el-icon>
          <input
            v-model.trim="keyword"
            type="text"
            placeholder="搜索会话"
          >
        </div>

        <div v-if="listLoading" class="list-loading">
          <div class="skeleton-item" v-for="i in 6" :key="i">
            <div class="skeleton-avatar"></div>
            <div class="skeleton-content">
              <div class="skeleton-name"></div>
              <div class="skeleton-preview"></div>
            </div>
          </div>
        </div>

        <div v-else-if="filteredConversations.length === 0" class="list-empty">
          暂无私聊会话
        </div>

        <ul v-else class="conversation-list">
          <li
            v-for="conv in filteredConversations"
            :key="conv.id"
            class="conversation-item"
            :class="{ active: conv.id === activeConversationId }"
            @click="openConversation(conv)"
          >
            <CachedAvatar
              :size="44"
              :src="conv.peer.avatar"
              avatar-class="peer-avatar"
            >
              {{ (conv.peer.nickname || conv.peer.username || '?')[0] }}
            </CachedAvatar>
            <div class="conversation-main">
              <div class="name-row">
                <span class="name">{{ conv.peer.nickname || conv.peer.username }}</span>
                <span class="time">{{ formatListTime(conv.last_message_at || conv.created_at) }}</span>
              </div>
              <div class="preview-row">
                <span class="preview">{{ conv.last_message_preview || '暂无消息' }}</span>
              </div>
            </div>
          </li>
        </ul>
      </aside>

      <section class="chat-panel" :class="{ hidden: isMobile && !mobileShowChat }">
        <div v-if="activeConversation" class="chat-header">
          <button v-if="isMobile" class="icon-btn" @click="mobileShowChat = false" title="返回会话列表">
            <el-icon><ArrowLeft /></el-icon>
          </button>
          <div class="chat-title">
            <h3>{{ activeConversation.peer.nickname || activeConversation.peer.username }}</h3>
            <span class="meta">共 {{ activeConversation.message_count || 0 }} 条消息</span>
          </div>
          <button class="icon-btn" @click="refreshCurrentConversation" :disabled="messageLoading" title="刷新消息">
            <el-icon><Refresh /></el-icon>
          </button>
        </div>

        <div v-if="!activeConversation" class="chat-empty">
          请选择左侧会话查看聊天记录
        </div>

        <div v-else class="chat-body" ref="messageViewport">
          <div class="load-more-wrap" v-if="hasMore || loadingMore">
            <button class="load-more-btn" @click="loadMore" :disabled="loadingMore">
              {{ loadingMore ? '加载中...' : '加载更早消息' }}
            </button>
          </div>

          <div v-if="messageLoading && messages.length === 0" class="message-loading">
            <div class="skeleton-message" v-for="i in 8" :key="i" :class="{ 'skeleton-mine': i % 3 === 0 }">
              <div class="skeleton-msg-avatar"></div>
              <div class="skeleton-msg-bubble"></div>
            </div>
          </div>

          <template v-else>
            <div v-if="messages.length === 0" class="message-empty">这个会话还没有消息</div>
            <div v-else class="message-list">
              <div
                v-for="msg in messages"
                :key="msg.id"
                class="message-row"
                :class="{ mine: msg.is_mine }"
              >
                <CachedAvatar
                  :size="36"
                  :src="msg.sender.avatar"
                  avatar-class="msg-avatar"
                >
                  {{ (msg.sender.nickname || msg.sender.username || '?')[0] }}
                </CachedAvatar>
                <div class="bubble-wrap">
                  <div class="sender">{{ msg.sender.nickname || msg.sender.username }}</div>
                  <div class="bubble">{{ msg.content }}</div>
                  <div class="time">{{ formatMessageTime(msg.created_at) }}</div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'FrontDM' })

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh, Search } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import 'element-plus/es/components/message/style/css'

import { getBotToken, getDmConversations, getDmMessages } from '../../api'
import CachedAvatar from '../../components/CachedAvatar.vue'

const router = useRouter()
const route = useRoute()

const keyword = ref('')
const debouncedKeyword = ref('')
const listLoading = ref(false)
const messageLoading = ref(false)
const loadingMore = ref(false)
const conversations = ref([])
const messages = ref([])
const activeConversationId = ref(null)
const hasMore = ref(false)
const messageViewport = ref(null)
const mobileShowChat = ref(false)
const isMobile = ref(window.innerWidth <= 900)
const sseConnected = ref(false)
const sseConnecting = ref(false)
const sseError = ref('')
const fallbackSyncing = ref(false)
const pageSize = 40
const fallbackIntervalMs = 15000
let dmEventSource = null
let fallbackTimer = null
let searchDebounceTimer = null
let resizeThrottleTimer = null

const filteredConversations = computed(() => {
  const kw = debouncedKeyword.value.toLowerCase()
  if (!kw) return conversations.value
  return conversations.value.filter((c) => {
    const nickname = (c.peer.nickname || '').toLowerCase()
    const username = (c.peer.username || '').toLowerCase()
    return nickname.includes(kw) || username.includes(kw)
  })
})

const activeConversation = computed(() => {
  return conversations.value.find((c) => c.id === activeConversationId.value) || null
})

const handleResize = () => {
  if (resizeThrottleTimer) return
  resizeThrottleTimer = setTimeout(() => {
    resizeThrottleTimer = null
    isMobile.value = window.innerWidth <= 900
    if (!isMobile.value) {
      mobileShowChat.value = true
    } else if (!activeConversationId.value) {
      mobileShowChat.value = false
    }
  }, 200)
}

const formatListTime = (value) => {
  if (!value) return ''
  const dt = dayjs(value)
  if (dt.isSame(dayjs(), 'day')) return dt.format('HH:mm')
  if (dt.isSame(dayjs(), 'year')) return dt.format('MM-DD')
  return dt.format('YYYY-MM-DD')
}

const formatMessageTime = (value) => {
  if (!value) return ''
  return dayjs(value).format('MM-DD HH:mm')
}

const trimPreview = (content = '') => {
  if (content.length <= 200) return content
  return `${content.slice(0, 197)}...`
}

const closeSse = () => {
  if (!dmEventSource) return
  dmEventSource.close()
  dmEventSource = null
  sseConnected.value = false
  sseConnecting.value = false
}

const getBotTokenForSse = async () => {
  const cached = localStorage.getItem('bot_token')
  if (cached) return cached

  try {
    const res = await getBotToken()
    const token = res?.token || ''
    if (token) localStorage.setItem('bot_token', token)
    return token
  } catch (error) {
    console.error('Failed to get bot token for SSE:', error)
    return ''
  }
}

const stopFallbackSync = () => {
  if (!fallbackTimer) return
  clearInterval(fallbackTimer)
  fallbackTimer = null
}

const fallbackSyncOnce = async () => {
  if (fallbackSyncing.value || listLoading.value || loadingMore.value) return

  fallbackSyncing.value = true
  try {
    const res = await getDmConversations({ page: 1, page_size: 100 })
    const latestConversations = res.items || []
    const previousActiveId = activeConversationId.value
    const previousActive = conversations.value.find((c) => c.id === previousActiveId)
    const previousLastMessageId = Number(previousActive?.last_message_id || 0)
    const shouldStickBottom = isNearBottom()

    conversations.value = latestConversations

    if (latestConversations.length === 0) {
      activeConversationId.value = null
      messages.value = []
      hasMore.value = false
      if (isMobile.value) mobileShowChat.value = false
      return
    }

    const nextActive = latestConversations.find((c) => c.id === previousActiveId) || latestConversations[0]
    if (!nextActive) return

    if (nextActive.id !== previousActiveId) {
      await openConversation(nextActive)
      return
    }

    const latestLastMessageId = Number(nextActive.last_message_id || 0)
    if (latestLastMessageId <= previousLastMessageId) return

    const list = await loadMessages(nextActive.peer?.id)
    messages.value = Array.isArray(list) ? list : []
    hasMore.value = messages.value.length === pageSize
    if (shouldStickBottom) {
      scrollToBottom()
    }
  } catch (error) {
    console.error('Fallback DM sync failed:', error)
  } finally {
    fallbackSyncing.value = false
  }
}

const startFallbackSync = () => {
  if (fallbackTimer) return
  fallbackSyncOnce().catch(() => {})
  fallbackTimer = setInterval(() => {
    fallbackSyncOnce().catch(() => {})
  }, fallbackIntervalMs)
}

const isNearBottom = () => {
  const viewport = messageViewport.value
  if (!viewport) return true
  const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
  return distance < 80
}

const updateConversationPreviewBySse = (conversationId, payloadMessage) => {
  const idx = conversations.value.findIndex((c) => c.id === conversationId)
  if (idx === -1) return false

  const conv = conversations.value[idx]
  const incomingMessageId = Number(payloadMessage.id || 0)
  const currentLastMessageId = Number(conv.last_message_id || 0)
  if (incomingMessageId <= currentLastMessageId) {
    return true
  }

  conv.last_message_id = payloadMessage.id
  conv.last_message_sender_id = payloadMessage.sender_id
  conv.last_message_preview = trimPreview(payloadMessage.content || '')
  conv.last_message_at = payloadMessage.created_at
  conv.message_count = Number(conv.message_count || 0) + 1

  if (idx > 0) {
    conversations.value.splice(idx, 1)
    conversations.value.unshift(conv)
  }
  return true
}

const appendMessageBySse = (payloadMessage) => {
  if (messages.value.some((item) => item.id === payloadMessage.id)) return

  const shouldStickBottom = isNearBottom()
  const activePeerId = Number(activeConversation.value?.peer?.id || 0)
  const isMine = activePeerId > 0 && Number(payloadMessage.sender_id) !== activePeerId
  messages.value.push({
    id: payloadMessage.id,
    conversation_id: payloadMessage.conversation_id,
    sender: {
      id: payloadMessage.sender_id,
      username: payloadMessage.sender_username,
      nickname: payloadMessage.sender_nickname,
      avatar: ''
    },
    content: payloadMessage.content,
    client_msg_id: payloadMessage.client_msg_id || null,
    is_mine: isMine,
    created_at: payloadMessage.created_at
  })

  if (shouldStickBottom) {
    scrollToBottom()
  }
}

const handleIncomingDmEvent = async (payload) => {
  if (payload?.type !== 'dm_new_message' || !payload?.message) return

  const conversationId = Number(payload.conversation_id)
  if (!conversationId) return

  const exists = updateConversationPreviewBySse(conversationId, payload.message)
  if (!exists) {
    loadConversations().catch(() => {})
  }

  if (activeConversationId.value !== conversationId) return

  appendMessageBySse(payload.message)
}

const initSse = async () => {
  closeSse()
  stopFallbackSync()
  sseConnecting.value = true
  sseError.value = ''

  const token = await getBotTokenForSse()
  if (!token) {
    sseConnecting.value = false
    sseError.value = '缺少 Bot Token，无法建立实时连接'
    startFallbackSync()
    return
  }

  dmEventSource = new EventSource(`/sse/bot?token=${encodeURIComponent(token)}`)

  dmEventSource.onopen = () => {
    sseConnected.value = true
    sseConnecting.value = false
    sseError.value = ''
    stopFallbackSync()
  }

  dmEventSource.onmessage = (event) => {
    let payload = null
    try {
      payload = JSON.parse(event.data)
    } catch (error) {
      console.error('Failed to parse SSE payload:', error)
      return
    }
    handleIncomingDmEvent(payload).catch((error) => {
      console.error('Failed to handle DM SSE event:', error)
    })
  }

  dmEventSource.onerror = () => {
    sseConnected.value = false
    sseConnecting.value = dmEventSource?.readyState !== EventSource.CLOSED
    if (dmEventSource?.readyState === EventSource.CLOSED) {
      sseError.value = '实时连接已关闭'
    } else {
      sseError.value = '实时连接波动，正在重连'
    }
    startFallbackSync()
  }
}

const syncCidQuery = (id) => {
  const cid = id ? String(id) : undefined
  if (route.query.cid === cid) return
  router.replace({
    path: '/dm',
    query: cid ? { cid } : {}
  }).catch(() => {})
}

const scrollToBottom = () => {
  nextTick(() => {
    if (!messageViewport.value) return
    messageViewport.value.scrollTop = messageViewport.value.scrollHeight
  })
}

const loadMessages = async (targetUserId, beforeId = null) => {
  if (!targetUserId) return
  const params = { limit: pageSize }
  if (beforeId) params.before_id = beforeId
  return getDmMessages(targetUserId, params)
}

const openConversation = async (conv) => {
  if (!conv?.id) return
  activeConversationId.value = conv.id
  syncCidQuery(conv.id)
  if (isMobile.value) mobileShowChat.value = true

  messageLoading.value = true
  try {
    const list = await loadMessages(conv.peer?.id)
    // 冻结消息数据减少响应式开销
    const frozenList = Array.isArray(list) ? list.map(msg => Object.freeze({
      ...msg,
      sender: Object.freeze(msg.sender)
    })) : []
    messages.value = frozenList
    hasMore.value = messages.value.length === pageSize
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load messages:', error)
    ElMessage.error('加载私聊消息失败')
  } finally {
    messageLoading.value = false
  }
}

const loadMore = async () => {
  if (loadingMore.value || !activeConversationId.value || messages.value.length === 0) return
  const oldestId = messages.value[0].id
  const viewport = messageViewport.value
  const oldHeight = viewport ? viewport.scrollHeight : 0

  loadingMore.value = true
  try {
  const older = await loadMessages(activeConversation.value?.peer?.id, oldestId)
    const list = Array.isArray(older) ? older : []
    hasMore.value = list.length === pageSize
    if (list.length > 0) {
      // 冻结新加载的消息
      const frozenOlder = list.map(msg => Object.freeze({
        ...msg,
        sender: Object.freeze(msg.sender)
      }))
      messages.value = [...frozenOlder, ...messages.value]
      await nextTick()
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight - oldHeight
      }
    }
  } catch (error) {
    console.error('Failed to load older messages:', error)
    ElMessage.error('加载历史消息失败')
  } finally {
    loadingMore.value = false
  }
}

const refreshCurrentConversation = async () => {
  if (!activeConversation.value) return
  await openConversation(activeConversation.value)
}

const loadConversations = async () => {
  listLoading.value = true
  try {
    const res = await getDmConversations({ page: 1, page_size: 100 })
    conversations.value = res.items || []

    if (conversations.value.length === 0) {
      activeConversationId.value = null
      messages.value = []
      hasMore.value = false
      mobileShowChat.value = false
      return
    }

    const queryCid = Number(route.query.cid || 0)
    const nextId = conversations.value.some((c) => c.id === queryCid)
      ? queryCid
      : (conversations.value.some((c) => c.id === activeConversationId.value)
        ? activeConversationId.value
        : conversations.value[0].id)

    const target = conversations.value.find((c) => c.id === nextId)
    if (target) await openConversation(target)
  } catch (error) {
    console.error('Failed to load conversations:', error)
    ElMessage.error('加载私聊会话失败')
  } finally {
    listLoading.value = false
  }
}

// 搜索防抖
const handleSearchInput = () => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    debouncedKeyword.value = keyword.value
  }, 300)
}

// 监听keyword变化触发防抖
watch(keyword, handleSearchInput)

onMounted(() => {
  handleResize()
  window.addEventListener('resize', handleResize, { passive: true })
  loadConversations()
  initSse()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  if (resizeThrottleTimer) clearTimeout(resizeThrottleTimer)
  closeSse()
  stopFallbackSync()
})
</script>

<style lang="scss" scoped>
.dm-page {
  min-height: calc(100vh - var(--header-height) - 32px);
}

.dm-shell {
  display: flex;
  height: calc(100vh - var(--header-height) - 56px);
  min-height: 620px;
  padding: 0;
  overflow: hidden;
}

.conversation-panel {
  width: 336px;
  border-right: 1px solid var(--border-color);
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
}

.panel-header {
  height: 64px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;

  .title-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  h2 {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
  }

  .count {
    color: var(--text-secondary);
    font-size: 13px;
  }

  .live-status {
    height: 22px;
    padding: 0 8px;
    border-radius: 999px;
    border: 1px solid var(--border-color);
    background: var(--bg-tertiary);
    color: var(--text-tertiary);
    font-size: 11px;
    display: inline-flex;
    align-items: center;
    gap: 6px;

    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--text-tertiary);
    }

    &.online {
      color: var(--primary-color);
      border-color: var(--primary-color);

      .dot {
        background: var(--primary-color);
        animation: pulse-dot 1.6s infinite ease-in-out;
      }
    }

    &.connecting {
      color: var(--text-secondary);
    }
  }
}

.search-box {
  margin: 12px 12px 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: 12px;
  height: 40px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);

  input {
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-primary);
    width: 100%;
    font-size: 14px;
  }
}

.list-loading {
  padding: 0 8px;
}

.skeleton-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  margin-bottom: 4px;
  border-radius: 12px;
}

.skeleton-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-content {
  flex: 1;
  min-width: 0;
}

.skeleton-name {
  width: 60%;
  height: 16px;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  margin-bottom: 8px;
}

.skeleton-preview {
  width: 85%;
  height: 14px;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  animation-delay: 0.1s;
}

@keyframes skeleton-loading {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.list-empty {
  margin: 12px;
  color: var(--text-secondary);
}

.conversation-list {
  list-style: none;
  padding: 0 8px 10px;
  overflow-y: auto;
  flex: 1;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 12px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: var(--bg-tertiary);
    border-color: var(--border-light);
  }

  &.active {
    background: var(--bg-elevated);
    border: 1px solid var(--border-color);
    box-shadow: inset 2px 0 0 var(--primary-color);
  }
}

.conversation-main {
  min-width: 0;
  flex: 1;
}

.name-row,
.preview-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.name {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.time {
  color: var(--text-tertiary);
  font-size: 12px;
  flex-shrink: 0;
}

.preview {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 13px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.chat-panel {
  flex: 1;
  min-width: 0;
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
}

.chat-header {
  height: 64px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chat-title {
  min-width: 0;
  flex: 1;

  h3 {
    color: var(--text-primary);
    font-size: 17px;
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .meta {
    color: var(--text-secondary);
    font-size: 12px;
  }
}

.chat-empty,
.message-empty {
  color: var(--text-secondary);
  margin: auto;
  text-align: center;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px 20px;
  background: linear-gradient(180deg, var(--bg-primary), var(--bg-secondary));
}

.load-more-wrap {
  display: flex;
  justify-content: center;
  margin: 4px 0 12px;
}

.load-more-btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  cursor: pointer;

  &:disabled {
    opacity: 0.7;
    cursor: default;
  }
}

.message-loading {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.skeleton-message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 70%;

  &.skeleton-mine {
    margin-left: auto;
    flex-direction: row-reverse;
  }
}

.skeleton-msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  flex-shrink: 0;
}

.skeleton-msg-bubble {
  height: 52px;
  width: 100%;
  min-width: 180px;
  border-radius: 14px;
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  animation-delay: 0.15s;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 86%;

  &.mine {
    margin-left: auto;
    flex-direction: row-reverse;

    .bubble-wrap {
      align-items: flex-end;
    }

    .bubble {
      background: var(--primary-bg, var(--bg-elevated));
      border-color: var(--primary-color);
    }

    .sender {
      display: none;
    }
  }
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
}

.sender {
  color: var(--text-secondary);
  font-size: 12px;
  margin-bottom: 4px;
}

.bubble {
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: 14px;
  padding: 10px 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-width: min(720px, 100%);
}

.bubble-wrap .time {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;

  &:hover {
    color: var(--text-primary);
    border-color: var(--primary-color);
  }

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }
}

@keyframes pulse-dot {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

@media (max-width: 900px) {
  .dm-shell {
    height: calc(100vh - var(--header-height) - 24px);
    min-height: 520px;
  }

  .conversation-panel,
  .chat-panel {
    width: 100%;
  }

  .conversation-panel.hidden,
  .chat-panel.hidden {
    display: none;
  }

  .conversation-panel {
    border-right: none;
  }

  .message-row {
    max-width: 96%;
  }
}
</style>
