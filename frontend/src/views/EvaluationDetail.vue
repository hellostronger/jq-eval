<template>
  <div class="evaluation-detail">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>{{ evaluation?.name || '评估详情' }}</span>
          <el-button @click="$router.push('/evaluations')">返回</el-button>
        </div>
      </template>

      <el-descriptions :column="4" border>
        <el-descriptions-item label="名称">{{ evaluation?.name }}</el-descriptions-item>
        <el-descriptions-item label="数据集">{{ getDatasetName(evaluation?.dataset_id) }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(evaluation?.status)">
            {{ getStatusLabel(evaluation?.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(evaluation?.created_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 指标汇总 -->
    <el-card shadow="hover" style="margin-top: 16px" v-if="summary">
      <template #header>
        <span>指标汇总</span>
      </template>

      <el-row :gutter="16">
        <el-col :span="24">
          <div ref="summaryChartRef" style="height: 300px"></div>
        </el-col>
      </el-row>

      <el-table :data="metricSummaryTable" stripe style="margin-top: 16px">
        <el-table-column prop="name" label="指标" />
        <el-table-column prop="mean" label="平均值" width="100">
          <template #default="{ row }">
            {{ row.mean.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="std" label="标准差" width="100">
          <template #default="{ row }">
            {{ row.std.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="min" label="最小值" width="100">
          <template #default="{ row }">
            {{ row.min.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="max" label="最大值" width="100">
          <template #default="{ row }">
            {{ row.max.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="median" label="中位数" width="100">
          <template #default="{ row }">
            {{ row.median.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="count" label="有效数量" width="100" />
      </el-table>
    </el-card>

    <!-- 评估结果 -->
    <el-card shadow="hover" style="margin-top: 16px">
      <template #header>
        <span>评估结果详情</span>
      </template>

      <el-table :data="results" v-loading="resultsLoading" stripe max-height="400">
        <el-table-column prop="qa_record_id" label="QA ID" width="80" />
        <el-table-column label="指标得分" min-width="400">
          <template #default="{ row }">
            <div v-for="(score, metric) in row.metric_scores" :key="metric" style="display: inline-block; margin-right: 8px">
              <el-tag :type="score.error ? 'danger' : 'success'" size="small">
                {{ metric }}: {{ score.error ? '失败' : score.score.toFixed(3) }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { getEvaluation, getEvaluationResults, getEvaluationSummary, getDatasets } from '@/api'
import type { Evaluation, Dataset } from '@/types'

const route = useRoute()
const evalId = Number(route.params.id)

const evaluation = ref<Evaluation | null>(null)
const datasets = ref<Dataset[]>([])
const results = ref<any[]>([])
const summary = ref<any>(null)
const resultsLoading = ref(false)
const summaryChartRef = ref<HTMLElement>()

const formatDate = (date?: string) => date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-'

const statusLabels: Record<string, string> = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
}

const getStatusLabel = (status?: string) => status ? statusLabels[status] || status : '-'

const getStatusType = (status?: string) => {
  if (!status) return 'info'
  const types: Record<string, string> = {
    completed: 'success',
    running: 'warning',
    pending: 'info',
    failed: 'danger',
  }
  return types[status] || 'info'
}

const getDatasetName = (id?: number) => {
  if (!id) return '-'
  const ds = datasets.value.find(d => d.id === id)
  return ds?.name || id
}

const metricSummaryTable = computed(() => {
  if (!summary?.value?.metrics_summary) return []
  return Object.entries(summary.value.metrics_summary).map(([name, data]) => ({
    name,
    ...data as any
  }))
})

const fetchEvaluation = async () => {
  evaluation.value = await getEvaluation(evalId)
}

const fetchResults = async () => {
  if (evaluation.value?.status !== 'completed') return
  resultsLoading.value = true
  try {
    results.value = await getEvaluationResults(evalId)
  } finally {
    resultsLoading.value = false
  }
}

const fetchSummary = async () => {
  if (evaluation.value?.status !== 'completed') return
  try {
    summary.value = await getEvaluationSummary(evalId)
    initChart()
  } catch (e) {
    // 无汇总数据
  }
}

const fetchDatasets = async () => {
  datasets.value = await getDatasets()
}

const initChart = () => {
  if (!summaryChartRef.value || !summary.value?.metrics_summary) return
  const chart = echarts.init(summaryChartRef.value)
  const data = Object.entries(summary.value.metrics_summary).map(([name, val]) => ({
    name,
    value: (val as any).mean
  }))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data.map(d => d.name) },
    yAxis: { type: 'value', min: 0, max: 1 },
    series: [{
      type: 'bar',
      data: data.map(d => d.value),
      itemStyle: { color: '#1890ff' }
    }]
  })
}

onMounted(async () => {
  await fetchDatasets()
  await fetchEvaluation()
  await fetchResults()
  await fetchSummary()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>