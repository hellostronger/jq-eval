<template>
  <div class="models-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>模型配置</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新增配置
          </el-button>
        </div>
      </template>

      <el-tabs v-model="activeTab" @tab-change="fetchModels">
        <el-tab-pane label="LLM" name="llm" />
        <el-tab-pane label="Embedding" name="embedding" />
        <el-tab-pane label="Reranker" name="reranker" />
      </el-tabs>

      <el-table :data="models" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="provider" label="提供商" />
        <el-table-column prop="model_name" label="模型名称" />
        <el-table-column prop="api_base" label="API地址" />
        <el-table-column prop="is_default" label="默认" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" type="success" size="small">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="temperature" label="Temperature" width="100">
          <template #default="{ row }">
            {{ row.temperature || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="120">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="testModel(row)">
              测试
            </el-button>
            <el-button size="small" @click="editModel(row)">
              编辑
            </el-button>
            <el-button type="danger" size="small" @click="deleteModel(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingModel ? '编辑模型配置' : '新增模型配置'"
      width="500px"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="模型配置名称" />
        </el-form-item>
        <el-form-item label="模型类型">
          <el-select v-model="form.model_type" disabled>
            <el-option label="LLM" value="llm" />
            <el-option label="Embedding" value="embedding" />
            <el-option label="Reranker" value="reranker" />
          </el-select>
        </el-form-item>
        <el-form-item label="提供商">
          <el-select v-model="form.provider" @change="onProviderChange">
            <el-option label="OpenAI" value="openai" />
            <el-option label="Azure OpenAI" value="azure" />
            <el-option label="智谱AI" value="zhipuai" />
            <el-option label="百度千帆" value="baidu" />
            <el-option label="阿里云百炼" value="aliyun" />
            <el-option label="火山引擎" value="volcengine" />
            <el-option label="本地部署" value="local" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="form.model_name" placeholder="如 gpt-4, text-embedding-ada-002" />
        </el-form-item>
        <el-form-item label="API地址">
          <el-input v-model="form.api_base" placeholder="API Base URL" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="API Key" />
        </el-form-item>
        <el-form-item v-if="form.model_type === 'llm'" label="Temperature">
          <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item v-if="form.model_type === 'llm'" label="Max Tokens">
          <el-input-number v-model="form.max_tokens" :min="100" :max="32000" />
        </el-form-item>
        <el-form-item v-if="form.model_type === 'embedding'" label="向量维度">
          <el-input-number v-model="form.dimension" :min="256" :max="4096" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveModel" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { getModels, createModel, updateModel, deleteModel as delModel, testModel as testModelApi } from '@/api/models'
import type { ModelConfig, ModelType } from '@/types'

const activeTab = ref<ModelType>('llm')
const models = ref<ModelConfig[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingModel = ref<ModelConfig | null>(null)
const saving = ref(false)

const form = ref({
  name: '',
  model_type: 'llm' as ModelType,
  provider: 'openai',
  model_name: '',
  api_base: '',
  api_key: '',
  temperature: 0.7,
  max_tokens: 2048,
  dimension: 1536,
  is_default: false,
})

const formatDate = (date: string) => dayjs(date).format('YYYY-MM-DD')

const fetchModels = async () => {
  loading.value = true
  try {
    models.value = await getModels(activeTab.value)
  } finally {
    loading.value = false
  }
}

const showCreateDialog = () => {
  editingModel.value = null
  form.value = {
    name: '',
    model_type: activeTab.value,
    provider: 'openai',
    model_name: '',
    api_base: '',
    api_key: '',
    temperature: 0.7,
    max_tokens: 2048,
    dimension: 1536,
    is_default: false,
  }
  dialogVisible.value = true
}

const editModel = (model: ModelConfig) => {
  editingModel.value = model
  form.value = {
    name: model.name,
    model_type: model.model_type,
    provider: model.provider,
    model_name: model.model_name,
    api_base: model.api_base,
    api_key: model.api_key,
    temperature: model.temperature || 0.7,
    max_tokens: model.max_tokens || 2048,
    dimension: model.dimension || 1536,
    is_default: model.is_default,
  }
  dialogVisible.value = true
}

const onProviderChange = (provider: string) => {
  const presets: Record<string, { api_base: string }> = {
    openai: { api_base: 'https://api.openai.com/v1' },
    azure: { api_base: '' },
    zhipuai: { api_base: 'https://open.bigmodel.cn/api/paas/v4' },
    baidu: { api_base: '' },
    aliyun: { api_base: '' },
    volcengine: { api_base: '' },
    local: { api_base: 'http://localhost:8000/v1' },
  }
  if (presets[provider]) {
    form.value.api_base = presets[provider].api_base
  }
}

const saveModel = async () => {
  saving.value = true
  try {
    if (editingModel.value) {
      await updateModel(editingModel.value.id, form.value)
      ElMessage.success('更新成功')
    } else {
      await createModel(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchModels()
  } finally {
    saving.value = false
  }
}

const testModel = async (model: ModelConfig) => {
  try {
    const result = await testModelApi(model.id)
    if (result.success) {
      ElMessage.success('测试成功')
    } else {
      ElMessage.error(result.error || '测试失败')
    }
  } catch (e) {
    // 错误已在拦截器处理
  }
}

const deleteModel = async (model: ModelConfig) => {
  await ElMessageBox.confirm('确定删除此模型配置?', '提示', { type: 'warning' })
  await delModel(model.id)
  ElMessage.success('删除成功')
  fetchModels()
}

onMounted(() => {
  fetchModels()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>