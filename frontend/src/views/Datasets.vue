<template>
  <div class="datasets-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>数据集管理</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新增数据集
          </el-button>
        </div>
      </template>

      <el-table :data="datasets" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="total_records" label="记录数" width="100" />
        <el-table-column prop="created_at" label="创建时间" width="120">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="viewDataset(row)">
              查看
            </el-button>
            <el-button size="small" @click="uploadData(row)">
              导入
            </el-button>
            <el-button type="danger" size="small" @click="deleteDataset(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建数据集对话框 -->
    <el-dialog v-model="dialogVisible" title="新增数据集" width="400px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="数据集名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="数据集描述" />
        </el-form-item>
        <el-form-item label="RAG系统">
          <el-select v-model="form.rag_system_id" clearable placeholder="关联RAG系统">
            <el-option v-for="r in ragSystems" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDataset" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 上传数据对话框 -->
    <el-dialog v-model="uploadDialogVisible" title="导入数据" width="400px">
      <el-upload
        drag
        :auto-upload="false"
        :on-change="handleFileChange"
        accept=".csv,.json,.xlsx,.xls"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽文件到此处或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持 CSV、JSON、Excel 格式
          </div>
        </template>
      </el-upload>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitUpload" :loading="uploading" :disabled="!uploadFile">
          导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { getDatasets, createDataset, deleteDataset, uploadDatasetFile, getRAGSystems } from '@/api'
import type { Dataset, RAGSystem } from '@/types'

const router = useRouter()
const datasets = ref<Dataset[]>([])
const ragSystems = ref<RAGSystem[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const uploadFile = ref<File | null>(null)
const uploadTargetDataset = ref<Dataset | null>(null)

const form = ref({
  name: '',
  description: '',
  rag_system_id: null as number | null,
})

const formatDate = (date: string) => dayjs(date).format('YYYY-MM-DD')

const fetchDatasets = async () => {
  loading.value = true
  try {
    datasets.value = await getDatasets()
  } finally {
    loading.value = false
  }
}

const fetchRAGSystems = async () => {
  ragSystems.value = await getRAGSystems()
}

const showCreateDialog = () => {
  form.value = { name: '', description: '', rag_system_id: null }
  dialogVisible.value = true
}

const saveDataset = async () => {
  saving.value = true
  try {
    await createDataset(form.value)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    fetchDatasets()
  } finally {
    saving.value = false
  }
}

const viewDataset = (dataset: Dataset) => {
  router.push(`/datasets/${dataset.id}`)
}

const uploadData = (dataset: Dataset) => {
  uploadTargetDataset.value = dataset
  uploadFile.value = null
  uploadDialogVisible.value = true
}

const handleFileChange = (file: any) => {
  uploadFile.value = file.raw
}

const submitUpload = async () => {
  if (!uploadFile.value || !uploadTargetDataset.value) return
  uploading.value = true
  try {
    await uploadDatasetFile(uploadTargetDataset.value.id, uploadFile.value)
    ElMessage.success('导入成功')
    uploadDialogVisible.value = false
    fetchDatasets()
  } finally {
    uploading.value = false
  }
}

const deleteDataset = async (dataset: Dataset) => {
  await ElMessageBox.confirm('确定删除此数据集?', '提示', { type: 'warning' })
  await deleteDataset(dataset.id)
  ElMessage.success('删除成功')
  fetchDatasets()
}

onMounted(() => {
  fetchDatasets()
  fetchRAGSystems()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>