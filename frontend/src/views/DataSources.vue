<template>
  <div class="data-sources-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>数据源管理</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新增数据源
          </el-button>
        </div>
      </template>

      <el-table :data="dataSources" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="system_type" label="类型">
          <template #default="{ row }">
            <el-tag>{{ getSystemLabel(row.system_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="120">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="testConnection(row)">
              测试连接
            </el-button>
            <el-button type="success" size="small" @click="createSync(row)">
              同步数据
            </el-button>
            <el-button size="small" @click="viewSchema(row)">
              Schema
            </el-button>
            <el-button type="danger" size="small" @click="deleteDataSource(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建数据源对话框 -->
    <el-dialog v-model="dialogVisible" title="新增数据源" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="数据源名称" />
        </el-form-item>
        <el-form-item label="系统类型">
          <el-select v-model="form.system_type" @change="onSystemTypeChange">
            <el-option label="Dify (PostgreSQL)" value="dify" />
            <el-option label="FastGPT (MongoDB)" value="fastgpt" />
            <el-option label="n8n (PostgreSQL)" value="n8n" />
            <el-option label="自定义数据库" value="custom" />
          </el-select>
        </el-form-item>

        <!-- PostgreSQL配置 -->
        <template v-if="form.system_type === 'dify' || form.system_type === 'n8n' || form.system_type === 'custom'">
          <el-form-item label="Host">
            <el-input v-model="form.connection_config.host" placeholder="数据库地址" />
          </el-form-item>
          <el-form-item label="Port">
            <el-input-number v-model="form.connection_config.port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="Database">
            <el-input v-model="form.connection_config.database" placeholder="数据库名称" />
          </el-form-item>
          <el-form-item label="Username">
            <el-input v-model="form.connection_config.username" placeholder="用户名" />
          </el-form-item>
          <el-form-item label="Password">
            <el-input v-model="form.connection_config.password" type="password" show-password placeholder="密码" />
          </el-form-item>
        </template>

        <!-- MongoDB配置 -->
        <template v-if="form.system_type === 'fastgpt'">
          <el-form-item label="URI">
            <el-input v-model="form.connection_config.uri" placeholder="MongoDB URI" />
          </el-form-item>
          <el-form-item label="Database">
            <el-input v-model="form.connection_config.database" placeholder="数据库名称" />
          </el-form-item>
        </template>

        <el-form-item label="RAG系统">
          <el-select v-model="form.rag_system_id" clearable placeholder="关联RAG系统">
            <el-option v-for="r in ragSystems" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDataSource" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 同步数据对话框 -->
    <el-dialog v-model="syncDialogVisible" title="数据同步" width="400px">
      <el-form :model="syncForm" label-width="100px">
        <el-form-item label="同步类型">
          <el-checkbox-group v-model="syncForm.target_types">
            <el-checkbox label="chunks">分片数据</el-checkbox>
            <el-checkbox label="qa_records">QA记录</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="增量同步">
          <el-switch v-model="syncForm.incremental" />
        </el-form-item>
        <el-form-item label="批次大小">
          <el-input-number v-model="syncForm.batch_size" :min="50" :max="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="syncDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="startSync" :loading="syncing">开始同步</el-button>
      </template>
    </el-dialog>

    <!-- Schema对话框 -->
    <el-dialog v-model="schemaDialogVisible" title="数据库Schema" width="700px">
      <el-table :data="schemaData" stripe>
        <el-table-column prop="table_name" label="表名" />
        <el-table-column prop="row_count" label="记录数" width="100" />
        <el-table-column prop="columns" label="字段">
          <template #default="{ row }">
            <el-tag v-for="col in row.columns.slice(0, 5)" :key="col.name" size="small" style="margin: 2px">
              {{ col.name }} ({{ col.type }})
            </el-tag>
            <span v-if="row.columns.length > 5">...</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { getDataSources, createDataSource, testDataSourceConnection, getDataSourceSchema, createSyncTask, getRAGSystems } from '@/api'
import { request } from '@/api/request'
import type { DataSource, RAGSystem } from '@/types'

const dataSources = ref<DataSource[]>([])
const ragSystems = ref<RAGSystem[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const syncDialogVisible = ref(false)
const syncing = ref(false)
const schemaDialogVisible = ref(false)
const schemaData = ref<any[]>([])
const syncTarget = ref<DataSource | null>(null)

const form = ref({
  name: '',
  system_type: 'dify',
  connection_config: {
    host: '',
    port: 5432,
    database: '',
    username: '',
    password: '',
    uri: '',
  } as Record<string, any>,
  rag_system_id: null as number | null,
})

const syncForm = ref({
  target_types: ['chunks', 'qa_records'],
  incremental: false,
  batch_size: 100,
})

const formatDate = (date: string) => dayjs(date).format('YYYY-MM-DD')

const systemLabels: Record<string, string> = {
  dify: 'Dify',
  fastgpt: 'FastGPT',
  n8n: 'n8n',
  custom: '自定义',
}

const getSystemLabel = (type: string) => systemLabels[type] || type

const fetchDataSources = async () => {
  loading.value = true
  try {
    dataSources.value = await getDataSources()
  } finally {
    loading.value = false
  }
}

const fetchRAGSystems = async () => {
  ragSystems.value = await getRAGSystems()
}

const showCreateDialog = () => {
  form.value = {
    name: '',
    system_type: 'dify',
    connection_config: { host: '', port: 5432, database: '', username: '', password: '', uri: '' },
    rag_system_id: null,
  }
  dialogVisible.value = true
}

const onSystemTypeChange = (type: string) => {
  form.value.connection_config = { host: '', port: 5432, database: '', username: '', password: '', uri: '' }
}

const saveDataSource = async () => {
  saving.value = true
  try {
    await createDataSource(form.value)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    fetchDataSources()
  } finally {
    saving.value = false
  }
}

const testConnection = async (ds: DataSource) => {
  try {
    const result = await testDataSourceConnection(ds.id)
    if (result.success) {
      ElMessage.success('连接成功')
    } else {
      ElMessage.error(result.error || '连接失败')
    }
  } catch (e) {
    // 错误已在拦截器处理
  }
}

const createSync = (ds: DataSource) => {
  syncTarget.value = ds
  syncForm.value = { target_types: ['chunks', 'qa_records'], incremental: false, batch_size: 100 }
  syncDialogVisible.value = true
}

const startSync = async () => {
  if (!syncTarget.value) return
  syncing.value = true
  try {
    await createSyncTask(syncTarget.value.id, syncForm.value)
    ElMessage.success('同步任务已创建')
    syncDialogVisible.value = false
  } finally {
    syncing.value = false
  }
}

const viewSchema = async (ds: DataSource) => {
  try {
    schemaData.value = await getDataSourceSchema(ds.id)
    schemaDialogVisible.value = true
  } catch (e) {
    // 错误已在拦截器处理
  }
}

const deleteDataSource = async (ds: DataSource) => {
  await ElMessageBox.confirm('确定删除此数据源?', '提示', { type: 'warning' })
  await request.delete(`/data-sources/${ds.id}`)
  ElMessage.success('删除成功')
  fetchDataSources()
}

onMounted(() => {
  fetchDataSources()
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