<template>
  <div class="threads-page">
    <div class="page-title">
      <el-icon class="icon"><ChatDotRound /></el-icon>
      <div class="text">
        <h2>帖子管理</h2>
        <p>查看和管理所有帖子</p>
      </div>
    </div>

    <div class="search-bar">
      <el-input
        v-model="searchQuery"
        placeholder="搜索帖子标题或内容..."
        :prefix-icon="Search"
        clearable
        @input="handleSearch"
        class="search-input"
      />
    </div>

    <DataGrid :items="threads" :loading="loading" :skeleton-count="6">
      <template #default="{ item }">
        <AdminCard hoverable>
          <template #header>
            <div class="thread-card-header">
              <span class="thread-id">#{{ item.id }}</span>
              <div class="thread-stats">
                <span class="stat"><el-icon><Comment /></el-icon> {{ item.reply_count }}</span>
                <span class="stat"><el-icon><Star /></el-icon> {{ item.like_count || 0 }}</span>
              </div>
            </div>
          </template>

          <div class="thread-card-body">
            <router-link :to="`/admin/thread/${item.id}`" class="thread-title">
              {{ item.title }}
            </router-link>

            <div class="thread-author">
              <el-avatar :size="24" :src="item.author?.avatar">
                {{ item.author?.nickname?.[0] }}
              </el-avatar>
              <span>{{ item.author?.nickname }}</span>
            </div>

            <div class="thread-info">
              <div class="info-row">
                <span class="info-label">分类</span>
                <el-select
                  v-model="item.category"
                  size="small"
                  @change="handleCategoryChange(item)"
                  class="category-select"
                  @click.stop
                >
                  <el-option
                    v-for="cat in categories"
                    :key="cat.key"
                    :label="cat.name"
                    :value="cat.key"
                  />
                </el-select>
              </div>
              <div class="info-row">
                <span class="info-label">发布</span>
                <span class="info-value">{{ formatTime(item.created_at) }}</span>
              </div>
              <div class="info-row" v-if="item.last_reply_at">
                <span class="info-label">最后回复</span>
                <span class="info-value">{{ formatTime(item.last_reply_at) }}</span>
              </div>
            </div>
          </div>

          <template #footer>
            <router-link :to="`/admin/thread/${item.id}`">
              <el-button text type="primary" size="small">
                <el-icon><View /></el-icon> 查看
              </el-button>
            </router-link>
            <el-button text type="danger" size="small" @click="handleDelete(item)" style="margin-left: auto;">
              <el-icon><Delete /></el-icon> 删除
            </el-button>
          </template>
        </AdminCard>
      </template>
    </DataGrid>

    <div class="pagination-wrapper" v-if="total > pageSize">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, prev, pager, next"
        @current-change="loadThreads"
        @size-change="loadThreads"
      />
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'AdminThreads' })

import { ref, onMounted } from 'vue'
import { getAdminThreads, getCategories, adminDeleteThread, adminUpdateThreadCategory } from '../../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import { getThreadsListCache, setThreadsListCache, clearThreadsListCache } from '../../state/dataCache'
import { Search, Delete, View, Comment, Star, ChatDotRound } from '@element-plus/icons-vue'
import AdminCard from '../../components/admin/AdminCard.vue'
import DataGrid from '../../components/admin/DataGrid.vue'
import dayjs from 'dayjs'

const threads = ref([])
const categories = ref([])
const searchQuery = ref('')
const loading = ref(true)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const formatTime = (time) => dayjs(time).format('MM-DD HH:mm')

let searchTimer = null
const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    loadThreads({ force: true })
  }, 300)
}

const loadCategories = async () => {
  try {
    categories.value = await getCategories()
  } catch (error) {
    console.error('Failed to load categories:', error)
  }
}

const loadThreads = async (options = {}) => {
  const force = options?.force === true
  if (!force && !searchQuery.value) {
    const cached = getThreadsListCache(page.value, pageSize.value)
    if (cached) {
      threads.value = cached.items || []
      total.value = cached.total || 0
      loading.value = false
      return
    }
  }

  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (searchQuery.value) params.q = searchQuery.value
    const res = await getAdminThreads(params)
    const cachedRes = !searchQuery.value ? setThreadsListCache(page.value, pageSize.value, res) : res
    threads.value = cachedRes.items || []
    total.value = cachedRes.total || 0
  } catch (error) {
    ElMessage.error('加载帖子失败')
  } finally {
    loading.value = false
  }
}

const handleCategoryChange = async (row) => {
  try {
    const res = await adminUpdateThreadCategory(row.id, row.category)
    ElMessage.success(`分类已更改为: ${res.category_name}`)
    clearThreadsListCache()
  } catch (error) {
    ElMessage.error('修改分类失败')
    loadThreads({ force: true })
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确定要删除帖子 "${row.title}" 吗？此操作不可恢复。`, '确认删除', { type: 'warning' })
    await adminDeleteThread(row.id)
    ElMessage.success('删除成功')
    loadThreads({ force: true })
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

onMounted(() => {
  loadCategories()
})

loadThreads()
</script>

<style lang="scss" scoped>
.threads-page {
  max-width: 1400px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;

  .icon { font-size: 28px; color: var(--primary-color); }

  .text {
    h2 { font-size: 22px; font-weight: 600; color: var(--text-primary); margin-bottom: 2px; }
    p { color: var(--text-secondary); font-size: 14px; }
  }
}

.search-bar {
  margin-bottom: 20px;

  .search-input {
    max-width: 360px;

    :deep(.el-input__wrapper) {
      background: var(--bg-input);
      border: 1px solid var(--border-color);
      box-shadow: none;
      border-radius: var(--btn-radius);
      &.is-focus { border-color: var(--primary-color); }
    }
    :deep(.el-input__inner) { color: var(--text-primary); }
  }
}

.thread-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;

  .thread-id {
    font-size: 12px;
    color: var(--text-tertiary);
    font-family: monospace;
  }

  .thread-stats {
    display: flex;
    gap: 12px;

    .stat {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 13px;
      color: var(--text-secondary);
    }
  }
}

.thread-card-body {
  .thread-title {
    display: block;
    font-size: 15px;
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 10px;
    line-height: 1.4;
    text-decoration: none;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;

    &:hover {
      color: var(--primary-color);
    }
  }

  .thread-author {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;

    span {
      font-size: 13px;
      color: var(--text-secondary);
    }
  }

  .thread-info {
    .info-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 4px 0;

      .info-label {
        font-size: 13px;
        color: var(--text-tertiary);
      }

      .info-value {
        font-size: 13px;
        color: var(--text-secondary);
      }
    }
  }
}

.category-select {
  width: 120px;

  :deep(.el-input__wrapper) {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    box-shadow: none;
    height: 28px;

    &:hover { border-color: var(--primary-color); }
  }

  :deep(.el-input__inner) {
    color: var(--text-primary);
    font-size: 13px;
  }
}

.pagination-wrapper {
  margin-top: 24px;
  display: flex;
  justify-content: center;
}
</style>
