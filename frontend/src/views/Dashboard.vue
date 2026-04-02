<template>
  <div class="dashboard">
    <el-row :gutter="16">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon" color="#1890ff"><FolderOpened /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ stats.total_datasets || 0 }}</div>
              <div class="stat-label">数据集</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon" color="#52c41a"><Document /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ stats.total_qa_records || 0 }}</div>
              <div class="stat-label">QA记录</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon" color="#722ed1"><DataAnalysis /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ stats.evaluations?.total || 0 }}</div>
              <div class="stat-label">评估任务</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon" color="#fa8c16"><Connection /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ stats.total_rag_systems || 0 }}</div>
              <div class="stat-label">RAG系统</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <span>模型统计</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="8">
              <div class="model-stat">
                <div class="value">{{ stats.models?.llm || 0 }}</div>
                <div class="label">LLM</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="model-stat">
                <div class="value">{{ stats.models?.embedding || 0 }}</div>
                <div class="label">Embedding</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="model-stat">
                <div class="value">{{ stats.models?.reranker || 0 }}</div>
                <div class="label">Reranker</div>
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <span>评估任务状态</span>
          </template>
          <div ref="evalChartRef" style="height: 200px"></div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <span>最近评估</span>
          </template>
          <el-table :data="recentEvals" size="small">
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="status" label="状态">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="100">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <span>系统健康状态</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="4">
              <div class="health-item">
                <el-tag :type="health.database?.status === 'healthy' ? 'success' : 'danger'">
                  PostgreSQL
                </el-tag>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="health-item">
                <el-tag :type="health.redis?.status === 'healthy' ? 'success' : 'danger'">
                  Redis
                </el-tag>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="health-item">
                <el-tag :type="health.milvus?.status === 'healthy' ? 'success' : 'danger'">
                  Milvus
                </el-tag>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="health-item">
                <el-tag :type="health.minio?.status === 'healthy' ? 'success' : 'danger'">
                  MinIO
                </el-tag>
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { request } from '@/api/request'
import type { SystemStats, Evaluation } from '@/types'

const stats = ref<SystemStats>({
  total_datasets: 0,
  total_qa_records: 0,
  evaluations: { total: 0, completed: 0, running: 0, pending: 0, failed: 0 },
  total_rag_systems: 0,
  models: { llm: 0, embedding: 0, reranker: 0 }
})
const recentEvals = ref<Evaluation[]>([])
const health = ref<Record<string, any>>({})
const evalChartRef = ref<HTMLElement>()

const formatDate = (date: string) => dayjs(date).format('MM-DD HH:mm')

const getStatusType = (status: string) => {
  const types: Record<string, string> = {
    completed: 'success',
    running: 'warning',
    pending: 'info',
    failed: 'danger'
  }
  return types[status] || 'info'
}

const fetchStats = async () => {
  try {
    const res = await request.get<any>('/evaluations/daily-stats')
    stats.value = res
  } catch (e) {
    // 使用默认值
  }
}

const fetchRecentEvals = async () => {
  try {
    const res = await request.get<Evaluation[]>('/evaluations')
    recentEvals.value = res.slice(0, 5)
  } catch (e) {
    // 使用默认值
  }
}

const fetchHealth = async () => {
  try {
    const res = await request.get<any>('/health')
    health.value = res.components || {}
  } catch (e) {
    // 使用默认值
  }
}

const initChart = () => {
  if (!evalChartRef.value) return
  const chart = echarts.init(evalChartRef.value)
  const evalStats = stats.value.evaluations
  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: [
        { value: evalStats.completed, name: '已完成', itemStyle: { color: '#52c41a' } },
        { value: evalStats.running, name: '运行中', itemStyle: { color: '#fa8c16' } },
        { value: evalStats.pending, name: '待执行', itemStyle: { color: '#1890ff' } },
        { value: evalStats.failed, name: '失败', itemStyle: { color: '#f5222d' } },
      ]
    }]
  })
}

onMounted(async () => {
  await Promise.all([fetchStats(), fetchRecentEvals(), fetchHealth()])
  initChart()
})
</script>

<style scoped>
.dashboard {
  height: 100%;
}

.stat-card {
  height: 100px;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  font-size: 40px;
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #333;
}

.stat-label {
  font-size: 14px;
  color: #666;
}

.model-stat {
  text-align: center;
  padding: 16px 0;
}

.model-stat .value {
  font-size: 24px;
  font-weight: bold;
  color: #1890ff;
}

.model-stat .label {
  font-size: 14px;
  color: #666;
  margin-top: 4px;
}

.health-item {
  text-align: center;
}
</style>