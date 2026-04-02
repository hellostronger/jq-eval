<template>
  <div class="rag-systems-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>RAG系统管理</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新增系统
          </el-button>
        </div>
      </template>

      <el-table :data="ragSystems" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="system_type" label="类型">
          <template #default="{ row }">
            <el-tag>{{ getSystemLabel(row.system_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="api_endpoint" label="API地址" />
        <el-table-column prop="is_active" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="120">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button type="success" size="small" @click="queryTest(row)">
              查询测试
            </el-button>
            <el-button type="primary" size="small" @click="testConnection(row)">
              连接测试
            </el-button>
            <el-button size="small" @click="editSystem(row)">
              编辑
            </el-button>
            <el-button type="danger" size="small" @click="deleteSystem(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingSystem ? '编辑RAG系统' : '新增RAG系统'"
      width="600px"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="系统名称" />
        </el-form-item>
        <el-form-item label="系统类型">
          <el-select v-model="form.system_type" @change="onSystemTypeChange">
            <el-option label="Dify" value="dify" />
            <el-option label="Coze" value="coze" />
            <el-option label="FastGPT" value="fastgpt" />
            <el-option label="n8n" value="n8n" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="API地址">
          <el-input v-model="form.api_endpoint" placeholder="API Endpoint URL" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="API Key" />
        </el-form-item>
        <el-form-item label="LLM模型">
          <el-select v-model="form.llm_model_id" clearable placeholder="选择LLM模型">
            <el-option v-for="m in llmModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Embedding模型">
          <el-select v-model="form.embedding_model_id" clearable placeholder="选择Embedding模型">
            <el-option v-for="m in embeddingModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Reranker模型">
          <el-select v-model="form.reranker_model_id" clearable placeholder="选择Reranker模型">
            <el-option v-for="m in rerankerModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <!-- 系统类型特定配置 -->
        <el-form-item v-if="form.system_type === 'dify'" label="应用ID">
          <el-input v-model="form.config.app_id" placeholder="Dify App ID" />
        </el-form-item>
        <el-form-item v-if="form.system_type === 'coze'" label="Bot ID">
          <el-input v-model="form.config.bot_id" placeholder="Coze Bot ID" />
        </el-form-item>
        <el-form-item v-if="form.system_type === 'fastgpt'" label="知识库ID">
          <el-input v-model="form.config.kb_id" placeholder="FastGPT Knowledge Base ID" />
        </el-form-item>
        <el-form-item v-if="form.system_type === 'n8n'" label="Workflow ID">
          <el-input v-model="form.config.workflow_id" placeholder="n8n Workflow ID" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSystem" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 查询测试对话框 -->
    <el-dialog v-model="queryDialogVisible" title="RAG查询测试" width="500px">
      <el-form label-width="80px">
        <el-form-item label="问题">
          <el-input v-model="queryQuestion" type="textarea" :rows="3" placeholder="输入问题进行查询测试" />
        </el-form-item>
      </el-form>
      <el-button type="primary" @click="executeQuery" :loading="querying">执行查询</el-button>
      <div v-if="queryResult" style="margin-top: 16px">
        <el-divider>查询结果</el-divider>
        <el-card>
          <div><strong>回答：</strong>{{ queryResult.answer }}</div>
          <div v-if="queryResult.contexts?.length">
            <strong>引用：</strong>
            <ul>
              <li v-for="(ctx, i) in queryResult.contexts" :key="i">{{ ctx }}</li>
            </ul>
          </div>
        </el-card>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { getRAGSystems, createRAGSystem, updateRAGSystem, deleteRAGSystem, testRAGSystem, queryRAGSystem } from '@/api'
import { getModels } from '@/api/models'
import type { RAGSystem, ModelConfig } from '@/types'

const ragSystems = ref<RAGSystem[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingSystem = ref<RAGSystem | null>(null)
const saving = ref(false)

const llmModels = ref<ModelConfig[]>([])
const embeddingModels = ref<ModelConfig[]>([])
const rerankerModels = ref<ModelConfig[]>([])

const queryDialogVisible = ref(false)
const queryQuestion = ref('')
const queryResult = ref<any>(null)
const querying = ref(false)
const queryingSystem = ref<RAGSystem | null>(null)

const form = ref({
  name: '',
  system_type: 'dify',
  api_endpoint: '',
  api_key: '',
  llm_model_id: null as number | null,
  embedding_model_id: null as number | null,
  reranker_model_id: null as number | null,
  is_active: true,
  config: {} as Record<string, any>,
})

const formatDate = (date: string) => dayjs(date).format('YYYY-MM-DD')

const systemLabels: Record<string, string> = {
  dify: 'Dify',
  coze: 'Coze',
  fastgpt: 'FastGPT',
  n8n: 'n8n',
  custom: '自定义',
}

const getSystemLabel = (type: string) => systemLabels[type] || type

const fetchSystems = async () => {
  loading.value = true
  try {
    ragSystems.value = await getRAGSystems()
  } finally {
    loading.value = false
  }
}

const fetchModels = async () => {
  llmModels.value = await getModels('llm')
  embeddingModels.value = await getModels('embedding')
  rerankerModels.value = await getModels('reranker')
}

const showCreateDialog = () => {
  editingSystem.value = null
  form.value = {
    name: '',
    system_type: 'dify',
    api_endpoint: '',
    api_key: '',
    llm_model_id: null,
    embedding_model_id: null,
    reranker_model_id: null,
    is_active: true,
    config: {},
  }
  dialogVisible.value = true
}

const editSystem = (system: RAGSystem) => {
  editingSystem.value = system
  form.value = {
    name: system.name,
    system_type: system.system_type,
    api_endpoint: system.api_endpoint,
    api_key: system.api_key,
    llm_model_id: system.llm_model_id,
    embedding_model_id: system.embedding_model_id,
    reranker_model_id: system.reranker_model_id,
    is_active: system.is_active,
    config: system.config || {},
  }
  dialogVisible.value = true
}

const onSystemTypeChange = (type: string) => {
  const presets: Record<string, { api_endpoint: string }> = {
    dify: { api_endpoint: '' },
    coze: { api_endpoint: 'https://api.coze.cn' },
    fastgpt: { api_endpoint: '' },
    n8n: { api_endpoint: '' },
    custom: { api_endpoint: '' },
  }
  if (presets[type]) {
    form.value.api_endpoint = presets[type].api_endpoint
  }
  form.value.config = {}
}

const saveSystem = async () => {
  saving.value = true
  try {
    if (editingSystem.value) {
      await updateRAGSystem(editingSystem.value.id, form.value)
      ElMessage.success('更新成功')
    } else {
      await createRAGSystem(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchSystems()
  } finally {
    saving.value = false
  }
}

const testConnection = async (system: RAGSystem) => {
  try {
    const result = await testRAGSystem(system.id)
    if (result.success) {
      ElMessage.success('连接成功')
    } else {
      ElMessage.error(result.error || '连接失败')
    }
  } catch (e) {
    // 错误已在拦截器处理
  }
}

const queryTest = (system: RAGSystem) => {
  queryingSystem.value = system
  queryQuestion.value = ''
  queryResult.value = null
  queryDialogVisible.value = true
}

const executeQuery = async () => {
  if (!queryQuestion.value || !queryingSystem.value) return
  querying.value = true
  try {
    queryResult.value = await queryRAGSystem(queryingSystem.value.id, queryQuestion.value)
  } finally {
    querying.value = false
  }
}

const deleteSystem = async (system: RAGSystem) => {
  await ElMessageBox.confirm('确定删除此RAG系统?', '提示', { type: 'warning' })
  await deleteRAGSystem(system.id)
  ElMessage.success('删除成功')
  fetchSystems()
}

onMounted(() => {
  fetchSystems()
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