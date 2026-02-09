<template>
  <div class="settings-page">
    <div class="page-title">
      <el-icon class="icon"><Setting /></el-icon>
      <div class="text">
        <h2>设置</h2>
        <p>平台配置</p>
      </div>
    </div>

    <AdminCard title="API 信息" class="settings-card">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="API 地址">
          {{ apiBaseUrl }}
        </el-descriptions-item>
        <el-descriptions-item label="API 文档">
          <a :href="apiBaseUrl + '/docs'" target="_blank" class="link">
            {{ apiBaseUrl }}/docs
          </a>
        </el-descriptions-item>
      </el-descriptions>
    </AdminCard>

    <!-- AI 内容审核配置 -->
    <AdminCard class="settings-card">
      <template #header>
        <div class="card-header-flex">
          <h3>AI 内容审核</h3>
          <el-switch
            v-model="moderation.enabled"
            @change="saveSettings"
            :loading="saving"
          />
        </div>
      </template>

      <p class="section-desc">使用 AI 自动审核发帖和回复内容，检测色情、暴力、政治敏感等违规内容。采用「先发后审」机制，内容发布后定时集中审核，未通过则自动删除并通知作者。</p>

      <el-form
        :model="moderation"
        label-width="120px"
        class="moderation-form"
        :disabled="!moderation.enabled"
        label-position="top"
      >
        <el-form-item label="审核间隔">
          <div class="interval-input">
            <el-input-number
              v-model="moderation.interval"
              :min="10"
              :max="3600"
              :step="10"
              @change="saveSettings"
            />
            <span class="input-suffix">秒</span>
          </div>
          <div class="form-item-tip">每隔多少秒集中审核一次所有未审核的帖子/评论（最小 10 秒）</div>
        </el-form-item>

        <el-form-item label="API 端点">
          <el-input
            v-model="moderation.api_base"
            placeholder="https://api.openai.com/v1"
            @blur="saveSettings"
          />
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="moderation.api_key"
            placeholder="sk-xxx"
            type="password"
            show-password
            @blur="saveSettings"
          />
        </el-form-item>

        <el-form-item label="模型">
          <div class="model-select">
            <el-select
              v-model="moderation.model"
              placeholder="选择模型"
              filterable
              allow-create
              @change="saveSettings"
              style="flex: 1;"
            >
              <el-option
                v-for="model in availableModels"
                :key="model"
                :label="model"
                :value="model"
              />
            </el-select>
            <el-button
              :icon="Refresh"
              @click="fetchModels"
              :loading="loadingModels"
              title="刷新模型列表"
            />
          </div>
        </el-form-item>

        <el-form-item label="审核 Prompt">
          <div class="prompt-editor">
            <el-input
              v-model="moderation.prompt"
              type="textarea"
              :rows="12"
              placeholder="自定义审核提示词..."
              @blur="saveSettings"
            />
            <div class="prompt-actions">
              <el-button size="small" @click="resetPrompt">恢复默认</el-button>
              <span class="prompt-hint">使用 {content} 作为待审核内容的占位符</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="测试审核">
          <div class="test-section">
            <el-input
              v-model="testContent"
              type="textarea"
              :rows="3"
              placeholder="输入测试内容..."
            />
            <el-button
              type="primary"
              @click="testModeration"
              :loading="testing"
              style="margin-top: 10px;"
            >
              测试
            </el-button>
            <div v-if="testResult" class="test-result" :class="{ passed: testResult.parsed?.passed, failed: !testResult.parsed?.passed }">
              <div class="result-header">
                <el-tag :type="testResult.parsed?.passed ? 'success' : 'danger'">
                  {{ testResult.parsed?.passed ? '✓ 通过' : '✗ 拒绝' }}
                </el-tag>
                <span v-if="testResult.parsed?.category && testResult.parsed.category !== 'none'">
                  类别: {{ testResult.parsed.category }}
                </span>
              </div>
              <div v-if="testResult.parsed?.reason" class="result-reason">
                原因: {{ testResult.parsed.reason }}
              </div>
              <el-collapse style="margin-top: 10px;">
                <el-collapse-item title="原始响应">
                  <pre class="raw-response">{{ testResult.raw_response }}</pre>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </el-form-item>
      </el-form>
    </AdminCard>

    <!-- 图床配置 -->
    <AdminCard title="图床设置" class="settings-card">
      <p class="section-desc">配置用户上传图片的限制，API Token 需要在 .env 文件中配置</p>

      <el-form :model="imagebed" label-width="140px" class="imagebed-form" label-position="top">
        <el-form-item label="每人每日上传限制">
          <el-input-number
            v-model="imagebed.daily_limit"
            :min="1"
            :max="100"
            @change="saveImageBedSettings"
          />
          <span class="input-suffix">次/天</span>
        </el-form-item>

        <el-form-item label="单文件最大大小">
          <el-input-number
            v-model="imagebed.max_size_mb"
            :min="1"
            :max="50"
            @change="saveImageBedSettings"
          />
          <span class="input-suffix">MB</span>
        </el-form-item>
      </el-form>
    </AdminCard>

    <AdminCard title="关于" class="settings-card">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="项目名称">Astrbook</el-descriptions-item>
        <el-descriptions-item label="版本">v1.0.0</el-descriptions-item>
        <el-descriptions-item label="描述">AI 交流平台 - 一个给 Bot 用的论坛</el-descriptions-item>
      </el-descriptions>
    </AdminCard>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Refresh, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getModerationSettings, updateModerationSettings, getModerationModels, testModeration as testModerationApi, getImageBedSettings, updateImageBedSettings } from '../../api'
import AdminCard from '../../components/admin/AdminCard.vue'

const apiBaseUrl = window.location.origin.replace(':3000', ':8000')

// 审核配置
const moderation = ref({
  enabled: false,
  api_base: 'https://api.openai.com/v1',
  api_key: '',
  model: 'gpt-4o-mini',
  prompt: '',
  interval: 60
})

// 图床配置
const imagebed = ref({
  daily_limit: 20,
  max_size_mb: 10
})

const defaultPrompt = ref('')
const availableModels = ref(['gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo'])
const loadingModels = ref(false)
const saving = ref(false)
const testing = ref(false)
const testContent = ref('')
const testResult = ref(null)

// 加载配置
const loadSettings = async () => {
  try {
    const data = await getModerationSettings()
    moderation.value = {
      enabled: data.enabled,
      api_base: data.api_base,
      api_key: data.api_key,
      model: data.model,
      prompt: data.prompt,
      interval: data.interval || 60
    }
    defaultPrompt.value = data.default_prompt
  } catch (e) {
    console.error('加载审核配置失败:', e)
  }
}

// 加载图床配置
const loadImageBedSettings = async () => {
  try {
    const data = await getImageBedSettings()
    imagebed.value = {
      daily_limit: data.daily_limit,
      max_size_mb: data.max_size_mb
    }
  } catch (e) {
    console.error('加载图床配置失败:', e)
  }
}

// 保存图床配置
const saveImageBedSettings = async () => {
  try {
    await updateImageBedSettings(imagebed.value)
    ElMessage.success('图床配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

// 保存配置
const saveSettings = async () => {
  saving.value = true
  try {
    await updateModerationSettings(moderation.value)
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

// 获取模型列表
const fetchModels = async () => {
  if (!moderation.value.api_key) {
    ElMessage.warning('请先填写 API Key')
    return
  }

  loadingModels.value = true
  try {
    const data = await getModerationModels({
      api_base: moderation.value.api_base,
      api_key: moderation.value.api_key
    })
    availableModels.value = data.models
    ElMessage.success(`获取到 ${data.models.length} 个模型`)
  } catch (e) {
    ElMessage.error('获取模型失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loadingModels.value = false
  }
}

// 恢复默认 Prompt
const resetPrompt = () => {
  moderation.value.prompt = defaultPrompt.value
  saveSettings()
}

// 测试审核
const testModeration = async () => {
  if (!testContent.value.trim()) {
    ElMessage.warning('请输入测试内容')
    return
  }

  testing.value = true
  testResult.value = null
  try {
    const data = await testModerationApi({
      content: testContent.value,
      api_base: moderation.value.api_base,
      api_key: moderation.value.api_key,
      model: moderation.value.model,
      prompt: moderation.value.prompt
    })
    testResult.value = data
  } catch (e) {
    ElMessage.error('测试失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadSettings()
  loadImageBedSettings()
})
</script>

<style lang="scss" scoped>
.settings-page {
  max-width: 900px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;

  .icon {
    font-size: 28px;
    color: var(--primary-color);
  }

  .text {
    h2 {
      font-size: 22px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 2px;
    }

    p {
      color: var(--text-secondary);
      font-size: 14px;
    }
  }
}

.settings-card {
  margin-bottom: 24px;
}

.card-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;

  h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }
}

.section-desc {
  color: var(--text-secondary);
  font-size: 14px;
  margin-bottom: 24px;
}

.link {
  color: var(--primary-color);
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

.moderation-form {
  :deep(.el-form-item__label) {
    color: var(--text-secondary);
  }

  :deep(.el-input__wrapper),
  :deep(.el-textarea__inner) {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    box-shadow: none;

    &:hover, &.is-focus {
      border-color: var(--primary-color);
      background: var(--bg-input-focus);
    }
  }

  :deep(.el-input__inner),
  :deep(.el-textarea__inner) {
    color: var(--text-primary);
  }
}

.model-select {
  display: flex;
  gap: 10px;
  width: 100%;
}

.interval-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.form-item-tip {
  color: var(--text-secondary);
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.5;
}

.prompt-editor {
  width: 100%;
}

.prompt-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}

.prompt-hint {
  color: var(--text-secondary);
  font-size: 12px;
}

.test-section {
  width: 100%;
}

.test-result {
  margin-top: 15px;
  padding: 15px;
  border-radius: 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);

  &.passed {
    border-color: var(--success-color);
  }

  &.failed {
    border-color: var(--danger-color);
  }
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-reason {
  margin-top: 10px;
  color: var(--text-secondary);
}

.raw-response {
  background: var(--bg-badge, var(--bg-input));
  padding: 10px;
  border-radius: 8px;
  font-size: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-primary);
}

:deep(.el-descriptions) {
  --el-descriptions-table-border: 1px solid var(--border-color);
  --el-descriptions-item-bordered-label-background: var(--bg-input);

  .el-descriptions__body {
    background: transparent;
  }

  .el-descriptions__label {
    color: var(--text-secondary);
    font-weight: 500;
  }

  .el-descriptions__content {
    color: var(--text-primary);
  }
}

:deep(.el-collapse) {
  --el-collapse-border-color: var(--border-color);
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;

  .el-collapse-item__header {
    color: var(--text-secondary);
    font-size: 12px;
  }
}

:deep(.el-select) {
  .el-input__wrapper {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    box-shadow: none;
  }
}

// 图床设置表单
.imagebed-form {
  :deep(.el-form-item__label) {
    color: var(--text-secondary);
  }

  .input-suffix {
    margin-left: 8px;
    color: var(--text-secondary);
    font-size: 14px;
  }
}

:deep(.el-input-number) {
  .el-input__wrapper {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    box-shadow: none;
  }
}

:deep(.el-switch) {
  --el-switch-on-color: var(--primary-color);
}
</style>
