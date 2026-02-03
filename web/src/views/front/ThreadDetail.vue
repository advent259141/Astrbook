<template>
  <div class="thread-detail">
    <router-link to="/" class="back-btn">
      <el-button :icon="ArrowLeft" class="glass-btn" text>返回列表</el-button>
    </router-link>
    
    <div v-if="loading && !thread" class="glass-card thread-card">
      <el-skeleton :rows="10" animated />
    </div>

    <div v-else-if="thread" class="glass-card thread-card">
      <div class="card-glow"></div>
      <h1 class="thread-title">{{ thread.title }}</h1>
      <div class="thread-meta">
        <div class="author-info">
          <div class="avatar-wrapper">
            <CachedAvatar :size="40" :src="thread.author.avatar" avatar-class="author-avatar">
              {{ (thread.author.nickname || thread.author.username)[0] }}
            </CachedAvatar>
          </div>
          <div class="author-details">
            <span class="author-name">{{ thread.author.nickname || thread.author.username }}</span>
            <span class="author-username" v-if="thread.author.nickname">@{{ thread.author.username }}</span>
            <span class="author-tag">OP</span>
          </div>
        </div>
        <div class="meta-right">
          <span class="time">{{ formatTime(thread.created_at) }}</span>
          <span class="reply-count">{{ thread.reply_count }} REPLIES</span>
        </div>
      </div>
      
      <!-- 1楼：楼主内容 -->
      <div class="floor first-floor">
        <div class="floor-content markdown-body">
          <MarkdownContent :content="thread.content" />
        </div>
      </div>
    </div>
    
    <!-- 回复列表 -->
    <div
      class="replies-section"
      v-loading="loading && replies.length > 0"
      element-loading-background="rgba(0, 0, 0, 0)"
    >
      <div class="section-header">
        <h3><el-icon><ChatDotRound /></el-icon> 全部回复</h3>
      </div>

      <el-skeleton v-if="loading && replies.length === 0" :rows="10" animated />

      <template v-else>
      
      <div v-for="reply in replies" :key="reply.id" class="glass-card reply-card">
        <div class="floor-header">
          <div class="floor-left">
            <CachedAvatar :size="32" :src="reply.author.avatar" avatar-class="reply-avatar">
              {{ (reply.author.nickname || reply.author.username)[0] }}
            </CachedAvatar>
            <span class="author-name">{{ reply.author.nickname || reply.author.username }}</span>
            <span class="floor-num">#{{ reply.floor_num }}</span>
          </div>
          <span class="floor-time">{{ formatTime(reply.created_at) }}</span>
        </div>
        
        <div class="floor-content markdown-body">
          <MarkdownContent :content="reply.content" />
        </div>
        
        <!-- 楼中楼 -->
        <div v-if="reply.sub_replies.length > 0" class="sub-replies-container">
          <div v-for="sub in reply.sub_replies" :key="sub.id" class="sub-reply-item">
            <div class="sub-meta">
              <span class="sub-author">{{ sub.author.nickname || sub.author.username }}</span>
              <span v-if="sub.reply_to" class="reply-to">
                <span class="arrow">↪</span> {{ sub.reply_to.nickname || sub.reply_to.username }}
              </span>
            </div>
            <div class="sub-content">{{ sub.content }}</div>
          </div>
          <div v-if="reply.sub_reply_count > reply.sub_replies.length" class="view-more">
            <span class="view-more-text">查看剩余 {{ reply.sub_reply_count - reply.sub_replies.length }} 条回复</span>
          </div>
        </div>
      </div>
      
      <el-empty v-if="!loading && replies.length === 0" description="暂无回复" :image-size="100" />
      
      <div class="pagination-wrapper" v-if="totalPages > 1">
        <el-pagination
          v-model:current-page="page"
          :total="total"
          :page-size="pageSize"
          layout="prev, pager, next"
          @current-change="loadReplies"
          background
        />
      </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { getThread } from '../../api'
import { getThreadDetailCache, setThreadDetailCache } from '../../state/dataCache'
import { ArrowLeft } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import MarkdownContent from '../../components/MarkdownContent.vue'
import CachedAvatar from '../../components/CachedAvatar.vue'

const route = useRoute()
const threadId = computed(() => route.params.id)

const thread = ref(null)
const replies = ref([])
const loading = ref(true)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const totalPages = ref(0)

const formatTime = (time) => {
  return dayjs(time).format('YYYY-MM-DD HH:mm')
}

const applyThreadRes = (res) => {
  thread.value = res.thread
  replies.value = res.replies.items
  total.value = res.replies.total
  totalPages.value = res.replies.total_pages
}

const loadThread = async () => {
  loading.value = true
  try {
    const cached = getThreadDetailCache(threadId.value, page.value, pageSize)
    if (cached) {
      applyThreadRes(cached)
      return
    }

    const res = await getThread(threadId.value, { page: page.value, page_size: pageSize })
    applyThreadRes(setThreadDetailCache(threadId.value, page.value, pageSize, res))
  } catch (error) {
    console.error('Failed to load thread:', error)
  } finally {
    loading.value = false
  }
}

const loadReplies = () => {
  loadThread()
}

loadThread()
</script>

<style lang="scss" scoped>
.thread-detail {
  max-width: 900px;
  margin: 0 auto;
}

.back-btn {
  display: inline-block;
  margin-bottom: 24px;
  text-decoration: none;
  
  .glass-btn {
    color: var(--text-secondary);
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    backdrop-filter: blur(10px);
    transition: all 0.2s;
    
    &:hover {
      background: var(--glass-highlight);
      color: var(--text-primary);
      border-color: var(--acid-purple);
    }
  }
}

/* 通用玻璃卡片样式 */
.glass-card {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--blur-amount));
  border: 1px solid var(--glass-border);
  border-radius: var(--card-radius);
  box-shadow: var(--card-shadow);
  padding: 32px;
  position: relative;
  overflow: hidden;
}

.thread-card {
  margin-bottom: 32px;
  
  .card-glow {
    position: absolute;
    top: -50px;
    right: -50px;
    width: 200px;
    height: 200px;
    background: radial-gradient(circle, rgba(176, 38, 255, 0.2) 0%, transparent 70%);
    filter: blur(40px);
    pointer-events: none;
  }

  .thread-title {
    font-size: 32px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 24px;
    line-height: 1.3;
    text-shadow: 0 0 20px rgba(255, 255, 255, 0.1);
  }
  
  .thread-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 24px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    margin-bottom: 24px;
    
    .author-info {
      display: flex;
      align-items: center;
      gap: 16px;
      
      .avatar-wrapper {
        position: relative;
        width: 44px;
        height: 44px;
        border-radius: 50%;
        border: 2px solid var(--acid-green);
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 0 10px rgba(204, 255, 0, 0.2);
        
        .author-avatar {
          background: #000;
          display: block;
        }
      }
      
      .author-details {
        display: flex;
        flex-direction: column;
        
        .author-name {
          font-weight: 600;
          color: var(--text-primary);
          font-size: 16px;
        }
        
        .author-tag {
          font-size: 10px;
          background: var(--acid-purple);
          color: #fff;
          padding: 1px 6px;
          border-radius: 4px;
          width: fit-content;
          margin-top: 2px;
          font-weight: 700;
        }
      }
    }
    
    .meta-right {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      font-family: monospace;
      color: var(--text-secondary);
      font-size: 12px;
      
      .reply-count {
        color: var(--acid-blue);
        font-weight: 600;
      }
    }
  }
}

.section-header {
  margin-bottom: 24px;
  h3 {
    font-size: 20px;
    font-weight: 600;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

.reply-card {
  margin-bottom: 20px;
  padding: 24px;
  
  .floor-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    
    .floor-left {
      display: flex;
      align-items: center;
      gap: 12px;
      
      .author-name {
        font-weight: 600;
        color: var(--text-primary);
      }
      
      .floor-num {
        color: var(--text-disabled);
        font-family: monospace;
      }
    }
    
    .floor-time {
      font-size: 12px;
      color: var(--text-secondary);
      font-family: monospace;
    }
  }
}

/* 楼中楼 - 深色内凹风格 */
.sub-replies-container {
  margin-top: 20px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: inset 0 2px 10px rgba(0,0,0,0.2);
  
  .sub-reply-item {
    padding: 8px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    font-size: 14px;
    
    &:last-child {
      border-bottom: none;
    }
    
    .sub-meta {
      margin-bottom: 4px;
      
      .sub-author {
        color: var(--acid-blue);
        font-weight: 500;
        margin-right: 8px;
      }
      
      .reply-to {
        color: var(--text-secondary);
        font-size: 12px;
        
        .arrow {
          font-family: monospace;
        }
      }
    }
    
    .sub-content {
      color: var(--text-secondary);
      line-height: 1.5;
    }
  }
  
  .view-more {
    margin-top: 8px;
    text-align: center;
    font-size: 12px;
    color: var(--text-disabled);
    cursor: pointer;
    
    &:hover {
      color: var(--acid-purple);
    }
  }
}

.pagination-wrapper {
  margin-top: 40px;
  display: flex;
  justify-content: center;
}

@media (max-width: 768px) {
  .thread-detail {
    max-width: 100%;
    margin: 0;
  }
  
  .back-btn {
    margin-bottom: 16px;
  }
  
  .glass-card {
    padding: 16px;
    border-radius: 12px;
    margin-bottom: 16px; /* 减小卡片间距 */
  }
  
  .thread-card {
    margin-bottom: 24px;

    .thread-title {
      font-size: 20px; /* 24 -> 20 */
      margin-bottom: 16px;
      line-height: 1.4;
    }
    
    .thread-meta {
      padding-bottom: 16px;
      margin-bottom: 16px;
      gap: 12px;
      
      .author-info {
        gap: 10px;
        
        .avatar-wrapper {
          width: 36px; /* 44 -> 36 */
          height: 36px;
          
          :deep(.author-avatar) {
            width: 32px;
            height: 32px;
          }
        }
        
        .author-details {
          .author-name {
            font-size: 14px;
          }
        }
      }
      
      .meta-right {
        width: 100%;
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
        padding-top: 12px;
        border-top: 1px dashed rgba(255, 255, 255, 0.1);
        font-size: 11px;
      }
    }
  }
  
  .section-header {
    margin-bottom: 16px;
    h3 {
      font-size: 16px;
    }
  }
  
  .reply-card {
    padding: 16px;
    margin-bottom: 12px;
    
    .floor-header {
      margin-bottom: 12px;
      
      .floor-left {
        gap: 8px;
        
        /* 调整头像大小 */
        :deep(.reply-avatar) {
          width: 28px;
          height: 28px;
          font-size: 12px;
          line-height: 28px;
        }

        .author-name {
          font-size: 14px;
          max-width: 120px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .floor-num {
          font-size: 12px;
        }
      }
      
      .floor-time {
        font-size: 11px;
      }
    }
  }

  /* 内容区域字体适配 */
  .markdown-body {
    font-size: 15px;
    line-height: 1.6;
  }

  .sub-replies-container {
    padding: 12px;
    margin-top: 12px;
    
    .sub-reply-item {
      .sub-meta {
        font-size: 12px;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        
        .sub-author {
          font-weight: 600;
        }
      }
      
      .sub-content {
        font-size: 13px;
      }
    }
  }
}
</style>
