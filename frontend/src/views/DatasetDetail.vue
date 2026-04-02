<template>
  <div class="dataset-detail">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>{{ dataset?.name || '数据集详情' }}</span>
          <el-button @click="$router.push('/datasets')">返回</el-button>
        </div>
      </template>

      <el-descriptions :column="3" border>
        <el-descriptions-item label="名称">{{ dataset?.name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ dataset?.description }}</el-descriptions-item>
        <el-descriptions-item label="记录数">{{ dataset?.total_records }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="hover" style="margin-top: 16px">
      <template #header>
        <span>QA记录</span>
      </template>

      <el-table :data="qaRecords" v-loading="loading" stripe max-height="500">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答" min-width="200" show-overflow-tooltip />
        <el-table-column prop="contexts" label="引用" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.contexts?.length" size="small">
              {{ row.contexts.length }}条
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ground_truth" label="标准答案" width="150" show-overflow-tooltip />
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @change="fetchQARecords"
        style="margin-top: 16px"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getDataset, getQARecords } from '@/api'
import type { Dataset, QARecord } from '@/types'

const route = useRoute()
const datasetId = Number(route.params.id)

const dataset = ref<Dataset | null>(null)
const qaRecords = ref<QARecord[]>([])
const loading = ref(false)
const page = ref(1)
const size = ref(20)
const total = ref(0)

const fetchDataset = async () => {
  dataset.value = await getDataset(datasetId)
}

const fetchQARecords = async () => {
  loading.value = true
  try {
    const res = await getQARecords(datasetId, { page: page.value, size: size.value })
    qaRecords.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchDataset()
  fetchQARecords()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>