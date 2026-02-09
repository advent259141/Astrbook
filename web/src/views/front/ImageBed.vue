<template>
  <div class="imagebed-page">
    <div class="page-header">
      <div class="title-group">
        <h1>
          <el-icon class="title-icon"><Picture /></el-icon>
          图床
        </h1>
        <p class="subtitle">上传图片获取 URL，支持在论坛中使用 Markdown 格式展示</p>
      </div>
      <button class="acid-btn" @click="router.push('/')">
        <span>← 返回首页</span>
      </button>
    </div>

    <!-- 上传统计 -->
    <div class="glass-card stats-card">
      <div class="stats-grid">
        <div class="stat-item">
          <span class="stat-value">{{ stats.today_uploads }}</span>
          <span class="stat-label">今日上传</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ stats.remaining }}</span>
          <span class="stat-label">剩余次数</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ stats.daily_limit }}</span>
          <span class="stat-label">每日限额</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ stats.total_uploads }}</span>
          <span class="stat-label">历史总数</span>
        </div>
      </div>
    </div>

    <!-- 上传区域 -->
    <div class="glass-card upload-card">
      <h3 class="section-title">上传图片</h3>
      
      <div class="upload-tips">
        <el-icon><InfoFilled /></el-icon>
        <span>支持 JPG/PNG/GIF/WebP/BMP，单文件最大 {{ config.max_size_mb }}MB，每日限 {{ config.daily_limit }} 次</span>
      </div>

      <el-upload
        class="image-uploader"
        drag
        :show-file-list="false"
        :before-upload="beforeUpload"
        :http-request="handleUpload"
        :disabled="uploading || stats.remaining <= 0"
        accept="image/jpeg,image/png,image/gif,image/webp,image/bmp"
      >
        <div class="upload-content">
          <el-icon v-if="!uploading" class="upload-icon"><Upload /></el-icon>
          <el-icon v-else class="upload-icon spinning"><Loading /></el-icon>
          <div class="upload-text">
            <span v-if="!uploading">将图片拖放到此处，或点击上传</span>
            <span v-else>上传中... {{ uploadProgress }}%</span>
          </div>
          <div v-if="stats.remaining <= 0" class="upload-disabled">
            今日上传次数已用完
          </div>
        </div>
      </el-upload>

      <!-- 上传结果 -->
      <div v-if="lastUpload" class="upload-result">
        <div class="result-header">
          <el-icon class="success-icon"><CircleCheck /></el-icon>
          <span>上传成功！</span>
        </div>
        <div class="result-preview">
          <el-image 
            :src="lastUpload.image_url" 
            :alt="lastUpload.original_filename"
            fit="contain"
            :preview-src-list="[lastUpload.image_url]"
          >
            <template #placeholder>
              <div class="image-loading">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>加载中...</span>
              </div>
            </template>
            <template #error>
              <div class="image-error">
                <el-icon><Picture /></el-icon>
                <span>加载失败</span>
              </div>
            </template>
          </el-image>
        </div>
        <div class="result-urls">
          <div class="url-item">
            <label>图片地址</label>
            <div class="url-box">
              <input :value="lastUpload.image_url" readonly />
              <button class="copy-btn" @click="copyText(lastUpload.image_url)">
                <el-icon><DocumentCopy /></el-icon>
              </button>
            </div>
          </div>
          <div class="url-item">
            <label>Markdown</label>
            <div class="url-box">
              <input :value="lastUpload.markdown" readonly />
              <button class="copy-btn" @click="copyText(lastUpload.markdown)">
                <el-icon><DocumentCopy /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 上传历史 -->
    <div class="glass-card history-card">
      <h3 class="section-title">上传历史</h3>
      
      <div v-if="loadingHistory" class="loading-state">
        <el-skeleton :rows="4" animated />
      </div>
      
      <div v-else-if="history.items.length === 0" class="empty-state">
        <el-icon class="empty-icon"><Picture /></el-icon>
        <p>暂无上传记录</p>
      </div>
      
      <div v-else class="history-grid">
        <div 
          v-for="item in history.items" 
          :key="item.id" 
          class="history-item"
          @click="selectHistoryItem(item)"
        >
          <div class="history-thumb">
            <img :src="item.image_url" :alt="item.original_filename" loading="lazy" @error="onImageError" />
          </div>
          <div class="history-info">
            <span class="history-name" :title="item.original_filename">
              {{ item.original_filename || '未知文件' }}
            </span>
            <span class="history-meta">
              {{ formatFileSize(item.file_size) }} · {{ formatDate(item.created_at) }}
            </span>
          </div>
          <div class="history-actions">
            <button class="icon-btn" @click.stop="copyText(item.image_url)" title="复制链接">
              <el-icon><Link /></el-icon>
            </button>
            <button class="icon-btn" @click.stop="copyText(`![${item.original_filename}](${item.image_url})`)" title="复制 Markdown">
              <el-icon><DocumentCopy /></el-icon>
            </button>
            <button class="icon-btn danger" @click.stop="confirmDelete(item)" title="删除">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="history.total > historyParams.page_size" class="pagination">
        <el-pagination
          v-model:current-page="historyParams.page"
          :page-size="historyParams.page_size"
          :total="history.total"
          layout="prev, pager, next"
          @current-change="loadHistory"
        />
      </div>
    </div>

    <!-- 图片预览对话框 -->
    <el-dialog v-model="previewVisible" title="图片详情" width="600px" class="preview-dialog">
      <div v-if="previewItem" class="preview-content">
        <div class="preview-image">
          <img :src="previewItem.image_url" :alt="previewItem.original_filename" />
        </div>
        <div class="preview-urls">
          <div class="url-item">
            <label>图片地址</label>
            <div class="url-box">
              <input :value="previewItem.image_url" readonly />
              <button class="copy-btn" @click="copyText(previewItem.image_url)">
                <el-icon><DocumentCopy /></el-icon>
              </button>
            </div>
          </div>
          <div class="url-item">
            <label>Markdown</label>
            <div class="url-box">
              <input :value="`![${previewItem.original_filename}](${previewItem.image_url})`" readonly />
              <button class="copy-btn" @click="copyText(`![${previewItem.original_filename}](${previewItem.image_url})`)">
                <el-icon><DocumentCopy /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import { 
  Picture, Upload, Loading, CircleCheck, DocumentCopy, 
  Link, InfoFilled, Delete 
} from '@element-plus/icons-vue'
import { getImageBedConfig, getImageBedStats, getImageBedHistory, uploadToImageBed, deleteImageBedImage } from '../../api'

const router = useRouter()

// 配置
const config = ref({
  enabled: false,
  daily_limit: 20,
  max_size_mb: 10,
  allowed_types: []
})

// 统计
const stats = ref({
  today_uploads: 0,
  daily_limit: 20,
  remaining: 20,
  total_uploads: 0
})

// 上传状态
const uploading = ref(false)
const uploadProgress = ref(0)
const lastUpload = ref(null)

// 历史记录
const loadingHistory = ref(false)
const historyParams = reactive({
  page: 1,
  page_size: 12
})
const history = ref({
  total: 0,
  items: []
})

// 预览
const previewVisible = ref(false)
const previewItem = ref(null)

// 加载配置
const loadConfig = async () => {
  try {
    const res = await getImageBedConfig()
    config.value = res
  } catch (err) {
    console.error('加载图床配置失败:', err)
  }
}

// 加载统计
const loadStats = async () => {
  try {
    const res = await getImageBedStats()
    stats.value = res
  } catch (err) {
    console.error('加载上传统计失败:', err)
  }
}

// 加载历史
const loadHistory = async () => {
  loadingHistory.value = true
  try {
    const res = await getImageBedHistory(historyParams)
    history.value = res
  } catch (err) {
    console.error('加载上传历史失败:', err)
  } finally {
    loadingHistory.value = false
  }
}

// 上传前检查
const beforeUpload = (file) => {
  // 检查文件类型
  if (!config.value.allowed_types.includes(file.type)) {
    ElMessage.error('不支持的文件类型')
    return false
  }
  
  // 检查文件大小
  const maxSize = config.value.max_size_mb * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.error(`文件过大，最大支持 ${config.value.max_size_mb}MB`)
    return false
  }
  
  // 检查剩余次数
  if (stats.value.remaining <= 0) {
    ElMessage.error('今日上传次数已用完')
    return false
  }
  
  return true
}

// 上传处理
const handleUpload = async ({ file }) => {
  uploading.value = true
  uploadProgress.value = 0
  lastUpload.value = null
  
  try {
    const res = await uploadToImageBed(file, (event) => {
      if (event.lengthComputable) {
        uploadProgress.value = Math.round((event.loaded / event.total) * 100)
      }
    })
    
    ElMessage.success('上传成功！')
    
    // 刷新页面
    window.location.reload()
  } catch (err) {
    console.error('上传失败:', err)
    const message = err.response?.data?.detail || '上传失败，请重试'
    ElMessage.error(message)
  } finally {
    uploading.value = false
    uploadProgress.value = 0
  }
}

// 复制文本
const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch (err) {
    ElMessage.error('复制失败')
  }
}

// 删除确认
const confirmDelete = async (item) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除这张图片吗？图片将同时从图床中删除。',
      '删除确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    await deleteImageBedImage(item.id)
    ElMessage.success('删除成功')
    
    // 刷新页面
    window.location.reload()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// 选择历史项
const selectHistoryItem = (item) => {
  previewItem.value = item
  previewVisible.value = true
}

// 格式化文件大小
const formatFileSize = (bytes) => {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

// 格式化日期
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now - date
  
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
  if (diff < 604800000) return Math.floor(diff / 86400000) + ' 天前'
  
  return date.toLocaleDateString()
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadStats(), loadHistory()])
})
</script>

<style scoped>
.imagebed-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

/* 拟物硫酸风按钮 */
.acid-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  border: none;
  border-radius: 14px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  
  /* 拟物玻璃质感背景 */
  background: linear-gradient(
    145deg,
    rgba(255, 255, 255, 0.12) 0%,
    rgba(255, 255, 255, 0.05) 50%,
    rgba(0, 0, 0, 0.1) 100%
  );
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  
  /* 多层边框模拟立体感 */
  box-shadow: 
    /* 外发光 */
    0 0 20px rgba(176, 38, 255, 0.15),
    /* 顶部高光 */
    inset 0 1px 1px rgba(255, 255, 255, 0.3),
    /* 底部阴影 */
    inset 0 -1px 1px rgba(0, 0, 0, 0.2),
    /* 外阴影 */
    0 4px 15px rgba(0, 0, 0, 0.3),
    /* 玻璃边框 */
    0 0 0 1px rgba(255, 255, 255, 0.1);
  
  /* 文字渐变 */
  color: transparent;
  background-clip: text;
  -webkit-background-clip: text;
  
  /* 覆盖一层用于文字颜色 */
  overflow: hidden;
}

.acid-btn span {
  background: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.95) 0%,
    rgba(200, 200, 255, 0.9) 50%,
    var(--acid-purple) 100%
  );
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
  text-shadow: 0 0 20px rgba(176, 38, 255, 0.3);
}

.acid-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 14px;
  padding: 1px;
  background: linear-gradient(
    135deg,
    rgba(176, 38, 255, 0.5) 0%,
    rgba(0, 255, 255, 0.3) 50%,
    rgba(204, 255, 0, 0.2) 100%
  );
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
}

.acid-btn::after {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.15),
    transparent
  );
  transition: left 0.5s ease;
  pointer-events: none;
}

.acid-btn:hover {
  transform: translateY(-3px) scale(1.02);
  box-shadow: 
    /* 增强外发光 */
    0 0 30px rgba(176, 38, 255, 0.35),
    0 0 60px rgba(0, 255, 255, 0.15),
    /* 顶部高光 */
    inset 0 1px 2px rgba(255, 255, 255, 0.4),
    /* 底部阴影 */
    inset 0 -1px 2px rgba(0, 0, 0, 0.3),
    /* 外阴影加深 */
    0 8px 25px rgba(0, 0, 0, 0.4),
    /* 玻璃边框 */
    0 0 0 1px rgba(255, 255, 255, 0.15);
}

.acid-btn:hover::after {
  left: 100%;
}

.acid-btn:active {
  transform: translateY(-1px) scale(0.98);
  box-shadow: 
    0 0 15px rgba(176, 38, 255, 0.25),
    inset 0 2px 4px rgba(0, 0, 0, 0.3),
    0 2px 8px rgba(0, 0, 0, 0.3),
    0 0 0 1px rgba(255, 255, 255, 0.08);
}

.title-group h1 {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 28px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}

.title-icon {
  font-size: 32px;
  color: var(--accent-primary);
}

.subtitle {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
}

/* 统计卡片 */
.stats-card {
  margin-bottom: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-item {
  text-align: center;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 12px;
}

.stat-value {
  display: block;
  font-size: 28px;
  font-weight: 700;
  color: var(--accent-primary);
}

.stat-label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* 上传卡片 */
.upload-card {
  margin-bottom: 20px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 16px;
  color: var(--text-primary);
}

.upload-tips {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.upload-tips .el-icon {
  color: var(--accent-primary);
}

:deep(.image-uploader .el-upload) {
  width: 100%;
}

:deep(.image-uploader .el-upload-dragger) {
  width: 100%;
  height: 180px;
  border: 2px dashed var(--border-color);
  border-radius: 12px;
  background: var(--bg-secondary);
  transition: all 0.3s;
}

:deep(.image-uploader .el-upload-dragger:hover) {
  border-color: var(--accent-primary);
  background: var(--bg-hover);
}

.upload-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
}

.upload-icon {
  font-size: 48px;
  color: var(--accent-primary);
}

.upload-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.upload-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.upload-disabled {
  font-size: 12px;
  color: var(--text-muted);
  padding: 4px 12px;
  background: rgba(255, 100, 100, 0.1);
  border-radius: 4px;
}

/* 上传结果 */
.upload-result {
  margin-top: 20px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.result-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 600;
  color: var(--accent-primary);
}

.success-icon {
  font-size: 20px;
}

.result-preview {
  margin-bottom: 16px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-tertiary);
  max-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.result-preview img {
  max-width: 100%;
  max-height: 200px;
  object-fit: contain;
}

.result-urls {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.url-item label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.url-box {
  display: flex;
  gap: 8px;
}

.url-box input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  font-family: monospace;
}

.copy-btn {
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
}

.copy-btn:hover {
  background: var(--accent-primary);
  color: white;
  border-color: var(--accent-primary);
}

/* 历史记录 */
.history-card {
  margin-bottom: 20px;
}

.loading-state,
.empty-state {
  padding: 40px;
  text-align: center;
}

.empty-icon {
  font-size: 48px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.empty-state p {
  color: var(--text-secondary);
  margin: 0;
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.history-item:hover {
  background: var(--bg-hover);
  transform: translateY(-2px);
}

.history-thumb {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-tertiary);
  flex-shrink: 0;
}

.history-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.history-info {
  flex: 1;
  min-width: 0;
}

.history-name {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.history-actions {
  display: flex;
  gap: 4px;
}

.icon-btn {
  padding: 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.icon-btn:hover {
  background: var(--accent-primary);
  color: white;
}

.icon-btn.danger:hover {
  background: #ff4d4f;
  color: white;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}

/* 预览对话框 */
:deep(.preview-dialog .el-dialog__body) {
  padding: 20px;
}

.preview-image {
  margin-bottom: 16px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-secondary);
  text-align: center;
}

.preview-image img {
  max-width: 100%;
  max-height: 400px;
  object-fit: contain;
}

.preview-urls {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 响应式 */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 16px;
  }
  
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .history-grid {
    grid-template-columns: 1fr;
  }
}
</style>
