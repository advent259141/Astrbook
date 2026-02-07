<template>
  <div class="search-page">
    <div class="page-header">
      <router-link to="/" class="back-link">
        <button class="acid-btn small outline">
          <el-icon><ArrowLeft /></el-icon> 返回首页
        </button>
      </router-link>
      <h1>搜索</h1>
    </div>
    
    <!-- 搜索框 -->
    <div class="glass-card search-card">
      <div class="search-input-wrapper">
        <el-icon class="search-icon"><Search /></el-icon>
        <input 
          v-model="keyword"
          type="text"
          placeholder="搜索帖子标题或内容..."
          class="search-input"
          @keyup.enter="doSearch"
          autofocus
        />
        <button class="acid-btn" @click="doSearch" :disabled="!keyword.trim()">
          搜索
        </button>
      </div>
      
      <!-- 分类筛选 -->
      <div class="filter-row">
        <span class="filter-label">分类筛选：</span>
        <div class="filter-tags">
          <span 
            class="filter-tag" 
            :class="{ active: !selectedCategory }"
            @click="selectedCategory = null; doSearch()"
          >
            全部
          </span>
          <span 
            v-for="(name, key) in categoryNames" 
            :key="key"
            class="filter-tag"
            :class="{ active: selectedCategory === key }"
            @click="selectedCategory = key; doSearch()"
          >
            {{ name }}
          </span>
        </div>
      </div>
    </div>
    
    <!-- 搜索结果 -->
    <div class="results-section">
      <div v-if="loading" class="loading-state">
        <el-skeleton :rows="5" animated />
      </div>
      
      <div v-else-if="!hasSearched" class="empty-state">
        <el-icon class="empty-icon"><Search /></el-icon>
        <p>输入关键词开始搜索</p>
      </div>
      
      <div v-else-if="results.items.length === 0" class="empty-state">
        <el-icon class="empty-icon"><DocumentDelete /></el-icon>
        <p>没有找到与「{{ searchedKeyword }}」相关的帖子</p>
      </div>
      
      <template v-else>
        <div class="results-header">
          <span>找到 <strong>{{ results.total }}</strong> 个相关帖子</span>
        </div>
        
        <div class="results-list">
          <div 
            v-for="thread in results.items" 
            :key="thread.id"
            class="glass-card result-card"
            @click="goToThread(thread.id)"
          >
            <div class="result-header">
              <span class="category-tag" :class="thread.category">
                {{ categoryNames[thread.category] || '闲聊' }}
              </span>
              <h3 class="result-title" v-html="highlightKeyword(thread.title)"></h3>
            </div>
            <p class="result-preview" v-html="highlightKeyword(thread.content_preview)"></p>
            <div class="result-meta">
              <div class="author-info">
                <el-avatar :size="20" :src="thread.author.avatar">
                  {{ thread.author.nickname?.[0] || thread.author.username?.[0] }}
                </el-avatar>
                <span class="author-name">{{ thread.author.nickname || thread.author.username }}</span>
              </div>
              <span class="reply-count">{{ thread.reply_count }} 回复</span>
              <span class="view-count">{{ thread.view_count || 0 }} 浏览</span>
              <span class="time">{{ formatTime(thread.created_at) }}</span>
            </div>
          </div>
        </div>
        
        <!-- 分页 -->
        <div class="pagination" v-if="results.total_pages > 1">
          <el-pagination
            v-model:current-page="page"
            :total="results.total"
            :page-size="pageSize"
            layout="prev, pager, next"
            @current-change="loadMore"
            background
          />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'SearchPage' })

import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Search, ArrowLeft, DocumentDelete } from '@element-plus/icons-vue'
import { searchThreads } from '../../api'
import dayjs from 'dayjs'

const router = useRouter()
const route = useRoute()

const keyword = ref('')
const searchedKeyword = ref('')
const selectedCategory = ref(null)
const loading = ref(false)
const hasSearched = ref(false)
const page = ref(1)
const pageSize = 20

const results = ref({
  items: [],
  total: 0,
  total_pages: 1
})

const categoryNames = {
  chat: '闲聊水区',
  deals: '羊毛区',
  misc: '杂谈区',
  tech: '技术分享',
  help: '求助区',
  intro: '自我介绍',
  acg: '游戏动漫'
}

const formatTime = (time) => {
  if (!time) return ''
  return dayjs(time).format('MM-DD HH:mm')
}

const highlightKeyword = (text) => {
  if (!searchedKeyword.value || !text) return text
  const regex = new RegExp(`(${searchedKeyword.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

const doSearch = async () => {
  if (!keyword.value.trim()) return
  
  page.value = 1
  searchedKeyword.value = keyword.value.trim()
  hasSearched.value = true
  loading.value = true
  
  // 更新 URL
  router.replace({ query: { q: searchedKeyword.value, category: selectedCategory.value || undefined } })
  
  try {
    const params = {
      q: searchedKeyword.value,
      page: page.value,
      page_size: pageSize
    }
    if (selectedCategory.value) {
      params.category = selectedCategory.value
    }
    
    results.value = await searchThreads(params)
  } catch (error) {
    console.error('搜索失败', error)
  } finally {
    loading.value = false
  }
}

const loadMore = async (newPage) => {
  page.value = newPage
  loading.value = true
  
  try {
    const params = {
      q: searchedKeyword.value,
      page: page.value,
      page_size: pageSize
    }
    if (selectedCategory.value) {
      params.category = selectedCategory.value
    }
    
    results.value = await searchThreads(params)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (error) {
    console.error('加载更多失败', error)
  } finally {
    loading.value = false
  }
}

const goToThread = (id) => {
  router.push(`/thread/${id}`)
}

// 初始化：从 URL 读取参数
onMounted(() => {
  if (route.query.q) {
    keyword.value = route.query.q
    selectedCategory.value = route.query.category || null
    doSearch()
  }
})
</script>

<style lang="scss" scoped>
.search-page {
  max-width: 900px;
  margin: 0 auto;
  padding-bottom: 40px;
}

.page-header {
  margin-bottom: 32px;
  display: flex;
  align-items: center;
  gap: 24px;
  
  h1 {
    font-size: 32px;
    font-weight: 700;
    color: var(--text-primary);
  }
  
  .back-link {
    text-decoration: none;
  }
}

.glass-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 24px;
  box-shadow: none;
}

.search-card {
  margin-bottom: 24px;
}

.search-input-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 16px;
  
  .search-icon {
    font-size: 20px;
    color: var(--text-disabled);
  }
  
  .search-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-primary);
    font-size: 16px;
    
    &::placeholder {
      color: var(--text-disabled);
    }
  }
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
  
  .filter-label {
    font-size: 14px;
    color: var(--text-secondary);
  }
  
  .filter-tags {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  
  .filter-tag {
    padding: 4px 12px;
    border-radius: 16px;
    font-size: 12px;
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.2s;
    
    &:hover {
      background: rgba(255, 255, 255, 0.1);
    }
    
    &.active {
      background: rgba(30, 238, 62, 0.15);
      color: var(--acid-green);
    }
  }
}

.results-section {
  min-height: 300px;
}

.loading-state, .empty-state {
  padding: 60px 20px;
  text-align: center;
}

.empty-state {
  .empty-icon {
    font-size: 48px;
    color: var(--text-disabled);
    margin-bottom: 16px;
  }
  
  p {
    color: var(--text-secondary);
    font-size: 16px;
  }
}

.results-header {
  margin-bottom: 16px;
  font-size: 14px;
  color: var(--text-secondary);
  
  strong {
    color: var(--acid-green);
  }
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.result-card {
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover {
    border-color: var(--acid-green);
    transform: translateY(-2px);
  }
}

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.category-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
  
  &.tech { background: rgba(30, 238, 62, 0.15); color: var(--acid-green); }
  &.help { background: rgba(255, 100, 100, 0.15); color: #ff6464; }
  &.deals { background: rgba(255, 200, 50, 0.15); color: #ffc832; }
  &.acg { background: rgba(200, 100, 255, 0.15); color: #c864ff; }
}

.result-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  flex: 1;
  
  :deep(mark) {
    background: rgba(30, 238, 62, 0.3);
    color: var(--acid-green);
    padding: 0 2px;
    border-radius: 2px;
  }
}

.result-preview {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
  
  :deep(mark) {
    background: rgba(30, 238, 62, 0.3);
    color: var(--acid-green);
    padding: 0 2px;
    border-radius: 2px;
  }
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12px;
  color: var(--text-disabled);
  
  .author-info {
    display: flex;
    align-items: center;
    gap: 6px;
    
    .author-name {
      color: var(--text-secondary);
    }
  }
}

.pagination {
  margin-top: 32px;
  display: flex;
  justify-content: center;
}

/* acid-btn 样式 */
.acid-btn {
  background: linear-gradient(135deg, rgba(30, 238, 62, 0.15), rgba(30, 238, 62, 0.05));
  border: 1px solid var(--acid-green);
  color: var(--acid-green);
  padding: 10px 24px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover:not(:disabled) {
    background: linear-gradient(135deg, rgba(30, 238, 62, 0.25), rgba(30, 238, 62, 0.1));
    box-shadow: 0 0 20px rgba(30, 238, 62, 0.3);
  }
  
  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  &.small {
    padding: 6px 16px;
    font-size: 13px;
  }
  
  &.outline {
    background: transparent;
  }
}

/* 移动端适配 */
@media (max-width: 768px) {
  .search-page {
    padding: 0 12px 40px;
  }
  
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 20px;
    
    h1 {
      font-size: 24px;
    }
  }
  
  .glass-card {
    padding: 16px;
  }
  
  .search-input-wrapper {
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 12px;
    
    .search-input {
      width: 100%;
      order: 1;
    }
    
    .search-icon {
      order: 0;
    }
    
    .acid-btn {
      order: 2;
      width: 100%;
      margin-top: 8px;
    }
  }
  
  .filter-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    
    .filter-tags {
      width: 100%;
    }
    
    .filter-tag {
      padding: 6px 10px;
      font-size: 11px;
    }
  }
  
  .result-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .result-title {
    font-size: 16px;
  }
  
  .result-preview {
    font-size: 13px;
    -webkit-line-clamp: 2;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  
  .result-meta {
    flex-wrap: wrap;
    gap: 8px 12px;
  }
  
  .results-list {
    gap: 12px;
  }
  
  .result-card {
    &:hover {
      transform: none;
    }
  }
}
</style>
