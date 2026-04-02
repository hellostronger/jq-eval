<template>
  <div class="metrics-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>指标市场</span>
        </div>
      </template>

      <el-tabs v-model="activeCategory" @tab-change="filterMetrics">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane v-for="cat in categories" :key="cat" :label="cat" :name="cat" />
      </el-tabs>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="6" v-for="metric in filteredMetrics" :key="metric.id">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-header">
              <h3>{{ metric.display_name }}</h3>
              <el-tag :type="getFrameworkType(metric.framework)" size="small">
                {{ metric.framework }}
              </el-tag>
            </div>
            <p class="metric-desc">{{ metric.description }}</p>
            <div class="metric-tags">
              <el-tag v-if="metric.requires_llm" size="small" type="warning">需LLM</el-tag>
              <el-tag v-if="metric.requires_embedding" size="small" type="warning">需Embedding</el-tag>
              <el-tag v-if="metric.requires_ground_truth" size="small" type="info">需标准答案</el-tag>
              <el-tag v-if="metric.requires_contexts" size="small" type="info">需引用</el-tag>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <!-- 指标详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="指标详情" width="500px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="名称">{{ selectedMetric?.display_name }}</el-descriptions-item>
        <el-descriptions-item label="标识">{{ selectedMetric?.name }}</el-descriptions-item>
        <el-descriptions-item label="框架">{{ selectedMetric?.framework }}</el-descriptions-item>
        <el-descriptions-item label="类别">{{ selectedMetric?.category }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ selectedMetric?.description }}</el-descriptions-item>
        <el-descriptions-item label="依赖LLM">{{ selectedMetric?.requires_llm ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="依赖Embedding">{{ selectedMetric?.requires_embedding ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="需要标准答案">{{ selectedMetric?.requires_ground_truth ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="需要引用">{{ selectedMetric?.requires_contexts ? '是' : '否' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getMetrics, getMetricCategories } from '@/api'
import type { MetricDefinition } from '@/types'

const metrics = ref<MetricDefinition[]>([])
const categories = ref<string[]>([])
const activeCategory = ref('all')
const detailDialogVisible = ref(false)
const selectedMetric = ref<MetricDefinition | null>(null)

const filteredMetrics = computed(() => {
  if (activeCategory.value === 'all') return metrics.value
  return metrics.value.filter(m => m.category === activeCategory.value)
})

const frameworkTypes: Record<string, string> = {
  ragas: 'success',
  evalscope: 'primary',
}

const getFrameworkType = (framework: string) => frameworkTypes[framework] || 'info'

const fetchMetrics = async () => {
  metrics.value = await getMetrics()
}

const fetchCategories = async () => {
  categories.value = await getMetricCategories()
}

const filterMetrics = () => {
  // 已通过computed自动处理
}

const showMetricDetail = (metric: MetricDefinition) => {
  selectedMetric.value = metric
  detailDialogVisible.value = true
}

onMounted(() => {
  fetchMetrics()
  fetchCategories()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.metric-card {
  height: 180px;
  cursor: pointer;
}

.metric-card:hover {
  border-color: #1890ff;
}

.metric-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.metric-header h3 {
  margin: 0;
  font-size: 16px;
}

.metric-desc {
  color: #666;
  font-size: 13px;
  margin: 8px 0;
  line-height: 1.5;
}

.metric-tags {
  margin-top: 8px;
}

.metric-tags .el-tag {
  margin-right: 4px;
}
</style>