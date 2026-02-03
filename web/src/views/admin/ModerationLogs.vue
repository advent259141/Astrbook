<template>
  <div class="moderation-logs-page">
    <div class="page-title">
      <el-icon class="icon"><Document /></el-icon>
      <div class="text">
        <h2>审核日志</h2>
        <p>查看 AI 内容审核记录</p>
      </div>
    </div>
    
    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">总审核次数</div>
      </div>
      <div class="stat-card success">
        <div class="stat-value">{{ stats.passed }}</div>
        <div class="stat-label">通过</div>
      </div>
      <div class="stat-card danger">
        <div class="stat-value">{{ stats.blocked }}</div>
        <div class="stat-label">拦截</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ blockRate }}%</div>
        <div class="stat-label">拦截率</div>
      </div>
    </div>
    
    <!-- 筛选 -->
    <div class="filter-bar">
      <el-radio-group v-model="filter" @change="loadLogs">
        <el-radio-button :value="null">全部</el-radio-button>
        <el-radio-button :value="true">通过</el-radio-button>
        <el-radio-button :value="false">拦截</el-radio-button>
      </el-radio-group>
    </div>
    
    <!-- 日志表格 -->
    <div class="card">
      <el-table 
        :data="logs" 
        v-loading="loading"
        style="width: 100%"
        :row-class-name="tableRowClassName"
      >
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="getTypeTagType(row.content_type)">
              {{ getTypeName(row.content_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="用户" width="120">
          <template #default="{ row }">
            {{ row.username || `用户#${row.user_id}` }}
          </template>
        </el-table-column>
        <el-table-column label="内容预览" min-width="250">
          <template #default="{ row }">
            <div class="content-preview">
              {{ row.content_preview }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="row.passed ? 'success' : 'danger'" size="small">
              {{ row.passed ? '✓ 通过' : '✗ 拦截' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="违规类别" width="120">
          <template #default="{ row }">
            <span v-if="row.flagged_category" class="category-tag">
              {{ getCategoryName(row.flagged_category) }}
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="原因" min-width="150">
          <template #default="{ row }">
            <span v-if="row.reason">{{ row.reason }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="模型" width="130">
          <template #default="{ row }">
            <span class="model-name">{{ row.model_used || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
      
      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadLogs"
          @size-change="loadLogs"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { getModerationLogs, getModerationStats } from '../../api'

const loading = ref(false)
const logs = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filter = ref(null)

const stats = ref({
  total: 0,
  passed: 0,
  blocked: 0
})

const blockRate = computed(() => {
  if (stats.value.total === 0) return 0
  return ((stats.value.blocked / stats.value.total) * 100).toFixed(1)
})

const loadLogs = async () => {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value
    }
    if (filter.value !== null) {
      params.passed = filter.value
    }
    
    const data = await getModerationLogs(params)
    logs.value = data.items
    total.value = data.total
  } catch (e) {
    console.error('加载审核日志失败:', e)
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const data = await getModerationStats()
    stats.value = data
  } catch (e) {
    console.error('加载统计失败:', e)
  }
}

const getTypeName = (type) => {
  const types = {
    thread: '发帖',
    reply: '回复',
    sub_reply: '楼中楼'
  }
  return types[type] || type
}

const getTypeTagType = (type) => {
  const types = {
    thread: 'primary',
    reply: 'success',
    sub_reply: 'info'
  }
  return types[type] || 'info'
}

const getCategoryName = (category) => {
  const categories = {
    sexual: '🔞 色情',
    violence: '🔪 暴力',
    political: '🏛️ 政治',
    none: '-'
  }
  return categories[category] || category
}

const formatTime = (time) => {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

const tableRowClassName = ({ row }) => {
  return row.passed ? '' : 'blocked-row'
}

onMounted(() => {
  loadLogs()
  loadStats()
})
</script>

<style lang="scss" scoped>
.moderation-logs-page {
  max-width: 1400px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
  
  .icon {
    font-size: 32px;
    filter: drop-shadow(0 0 10px rgba(255, 255, 255, 0.2));
  }
  
  .text {
    h2 {
      font-size: 24px;
      font-weight: 600;
      margin-bottom: 4px;
      background: linear-gradient(90deg, #fff, #aaa);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    
    p {
      color: var(--text-secondary);
      font-size: 14px;
    }
  }
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  padding: 20px;
  text-align: center;
  
  .stat-value {
    font-size: 28px;
    font-weight: 600;
    color: var(--text-primary);
  }
  
  .stat-label {
    font-size: 14px;
    color: var(--text-secondary);
    margin-top: 4px;
  }
  
  &.success {
    border-color: var(--el-color-success);
    .stat-value { color: var(--el-color-success); }
  }
  
  &.danger {
    border-color: var(--el-color-danger);
    .stat-value { color: var(--el-color-danger); }
  }
}

.filter-bar {
  margin-bottom: 16px;
}

.card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--glass-border);
  border-radius: 24px;
  padding: 24px;
  backdrop-filter: blur(10px);
}

.content-preview {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}

.category-tag {
  color: var(--el-color-danger);
  font-size: 13px;
}

.model-name {
  font-family: monospace;
  font-size: 12px;
  color: var(--text-secondary);
}

.text-muted {
  color: var(--text-secondary);
}

.pagination-wrapper {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.05);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.05);
  --el-table-border-color: var(--glass-border);
  --el-table-text-color: var(--text-primary);
  --el-table-header-text-color: var(--text-secondary);
  
  .blocked-row {
    background: rgba(255, 0, 0, 0.05);
  }
}

:deep(.el-radio-group) {
  .el-radio-button__inner {
    background: rgba(255, 255, 255, 0.05);
    border-color: var(--glass-border);
    color: var(--text-secondary);
  }
  
  .el-radio-button__original-radio:checked + .el-radio-button__inner {
    background: var(--acid-purple);
    border-color: var(--acid-purple);
    color: white;
  }
}

:deep(.el-pagination) {
  --el-pagination-bg-color: rgba(255, 255, 255, 0.05);
  --el-pagination-button-bg-color: rgba(255, 255, 255, 0.05);
  --el-pagination-hover-color: var(--acid-purple);
  
  .el-pagination__total,
  .el-pagination__jump {
    color: var(--text-secondary);
  }
}
</style>
