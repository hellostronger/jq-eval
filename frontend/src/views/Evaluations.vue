<template>
  <div class="evaluations-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>评估任务</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新建评估
          </el-button>
        </div>
      </template>

      <el-table :data="evaluations" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="dataset_id" label="数据集" width="120">
          <template #default="{ row }">
            {{ getDatasetName(row.dataset_id) }}
          </template>
        </el-table-column>
        <el-table-column prop="metrics" label="指标" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="m in row.metrics" :key="m" size="small" style="margin-right: 4px">
              {{ m }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="120">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'pending'"
              type="success"
              size="small"
              @click="startEval(row)"
            >
              启动
            </el-button>
            <el-button
              v-if="row.status === 'completed'"
              type="primary"
              size="small"
              @click="viewResults(row)"
            >
              查看结果
            </el-button>
            <el-button type="danger" size="small" @click="deleteEval(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建评估对话框 -->
    <el-dialog v-model="dialogVisible" title="新建评估任务" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="评估任务名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="任务描述" />
        </el-form-item>
        <el-form-item label="数据集">
          <el-select v-model="form.dataset_id" placeholder="选择数据集">
            <el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="RAG系统">
          <el-select v-model="form.rag_system_id" clearable placeholder="选择RAG系统（可选）">
            <el-option v-for="r in ragSystems" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="LLM模型">
          <el-select v-model="form.llm_model_id" placeholder="选择LLM模型">
            <el-option v-for="m in llmModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Embedding模型">
          <el-select v-model="form.embedding_model_id" clearable placeholder="选择Embedding模型">
            <el-option v-for="m in embeddingModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="评估指标">
          <el-checkbox-group v-model="form.metrics">
            <el-checkbox v-for="m in metrics" :key="m.name" :label="m.name">
              {{ m.display_name }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="批次大小">
          <el-input-number v-model="form.batch_size" :min="1" :max="100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEvaluation" :loading="saving">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { getEvaluations, createEvaluation, startEvaluation, getDatasets, getRAGSystems, getMetrics } from '@/api'
import { getModels } from '@/api/models'
import { request } from '@/api/request'
import type { Evaluation, Dataset, RAGSystem, ModelConfig, MetricDefinition } from '@/types'

const router = useRouter()
const evaluations = ref<Evaluation[]>([])
const datasets = ref<Dataset[]>([])
const ragSystems = ref<RAGSystem[]>([])
const llmModels = ref<ModelConfig[]>([])
const embeddingModels = ref<ModelConfig[]>([])
const metrics = ref<MetricDefinition[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)

const form = ref({
  name: '',
  description: '',
  dataset_id: null as number | null,
  rag_system_id: null as number | null,
  llm_model_id: null as number | null,
  embedding_model_id: null as number | null,
  metrics: [] as string[],
  batch_size: 10,
})

const formatDate = (date: string) => dayjs(date).format('YYYY-MM-DD')

const statusLabels: Record<string, string> = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
}

const getStatusLabel = (status: string) => statusLabels[status] || status

const getStatusType = (status: string) => {
  const types: Record<string, string> = {
    completed: 'success',
    running: 'warning',
    pending: 'info',
    failed: 'danger',
  }
  return types[status] || 'info'
}

const getDatasetName = (id: number) => {
  const ds = datasets.value.find(d => d.id === id)
  return ds?.name || id
}

const fetchData = async () => {
  loading.value = true
  try {
    evaluations.value = await getEvaluations()
  } finally {
    loading.value = false
  }
}

const fetchReferenceData = async () => {
  datasets.value = await getDatasets()
  ragSystems.value = await getRAGSystems()
  llmModels.value = await getModels('llm')
  embeddingModels.value = await getModels('embedding')
  metrics.value = await getMetrics()
}

const showCreateDialog = () => {
  form.value = {
    name: '',
    description: '',
    dataset_id: null,
    rag_system_id: null,
    llm_model_id: null,
    embedding_model_id: null,
    metrics: [],
    batch_size: 10,
  }
  dialogVisible.value = true
}

const saveEvaluation = async () => {
  if (!form.value.dataset_id || !form.value.llm_model_id || form.value.metrics.length === 0) {
    ElMessage.warning('请填写必要信息')
    return
  }
  saving.value = true
  try {
    await createEvaluation(form.value)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    fetchData()
  } finally {
    saving.value = false
  }
}

const startEval = async (eval: Evaluation) => {
  try {
    await startEvaluation(eval.id)
    ElMessage.success('评估任务已启动')
    fetchData()
  } catch (e) {
    // 错误已在拦截器处理
  }
}

const viewResults = (eval: Evaluation) => {
  router.push(`/evaluations/${eval.id}`)
}

const deleteEval = async (eval: Evaluation) => {
  await ElMessageBox.confirm('确定删除此评估任务?', '提示', { type: 'warning' })
  await request.delete(`/evaluations/${eval.id}`)
  ElMessage.success('删除成功')
  fetchData()
}

onMounted(() => {
  fetchData()
  fetchReferenceData()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>