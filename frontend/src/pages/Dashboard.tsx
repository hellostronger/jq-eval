import React, { useEffect, useState } from 'react'
import { Card, Row, Col, Tag, Table, Statistic } from 'antd'
import {
  FolderOpenOutlined,
  FileTextOutlined,
  LineChartOutlined,
  ApiOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { getSystemStats, getHealth, getEvaluations } from '@/api'
import type { SystemStats, Evaluation } from '@/types'

const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<SystemStats>({
    total_datasets: 0,
    total_qa_records: 0,
    evaluations: { total: 0, completed: 0, running: 0, pending: 0, failed: 0 },
    total_rag_systems: 0,
    models: { llm: 0, embedding: 0, reranker: 0 },
  })
  const [health, setHealth] = useState<Record<string, { status: string }>>({})
  const [recentEvals, setRecentEvals] = useState<Evaluation[]>([])

  useEffect(() => {
    const fetchData = async () => {
      try {
        const statsData = await getSystemStats()
        setStats(statsData)
      } catch (e) {
        // 使用默认值
      }

      try {
        const healthData = await getHealth()
        setHealth(healthData.components || {})
      } catch (e) {
        // 使用默认值
      }

      try {
        const evals = await getEvaluations()
        setRecentEvals(evals.slice(0, 5))
      } catch (e) {
        // 使用默认值
      }
    }
    fetchData()
  }, [])

  const getStatusType = (status: string) => {
    const types: Record<string, 'success' | 'warning' | 'info' | 'error'> = {
      completed: 'success',
      running: 'warning',
      pending: 'info',
      failed: 'error',
    }
    return types[status] || 'info'
  }

  const pieOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        data: [
          { value: stats.evaluations.completed, name: '已完成', itemStyle: { color: '#52c41a' } },
          { value: stats.evaluations.running, name: '运行中', itemStyle: { color: '#fa8c16' } },
          { value: stats.evaluations.pending, name: '待执行', itemStyle: { color: '#1890ff' } },
          { value: stats.evaluations.failed, name: '失败', itemStyle: { color: '#f5222d' } },
        ],
      },
    ],
  }

  const evalColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => dayjs(date).format('MM-DD HH:mm'),
    },
  ]

  return (
    <div>
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic
              title="数据集"
              value={stats.total_datasets}
              prefix={<FolderOpenOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="QA记录"
              value={stats.total_qa_records}
              prefix={<FileTextOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="评估任务"
              value={stats.evaluations.total}
              prefix={<LineChartOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="RAG系统"
              value={stats.total_rag_systems}
              prefix={<ApiOutlined style={{ color: '#fa8c16' }} />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={8}>
          <Card title="模型统计">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="LLM" value={stats.models.llm} valueStyle={{ color: '#1890ff' }} />
              </Col>
              <Col span={8}>
                <Statistic title="Embedding" value={stats.models.embedding} valueStyle={{ color: '#1890ff' }} />
              </Col>
              <Col span={8}>
                <Statistic title="Reranker" value={stats.models.reranker} valueStyle={{ color: '#1890ff' }} />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="评估任务状态">
            <ReactECharts option={pieOption} style={{ height: 200 }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="最近评估">
            <Table
              dataSource={recentEvals}
              columns={evalColumns}
              rowKey="id"
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="系统健康状态">
            <Row gutter={16}>
              <Col span={4}>
                <Tag color={health.database?.status === 'healthy' ? 'success' : 'error'}>
                  PostgreSQL
                </Tag>
              </Col>
              <Col span={4}>
                <Tag color={health.redis?.status === 'healthy' ? 'success' : 'error'}>
                  Redis
                </Tag>
              </Col>
              <Col span={4}>
                <Tag color={health.milvus?.status === 'healthy' ? 'success' : 'error'}>
                  Milvus
                </Tag>
              </Col>
              <Col span={4}>
                <Tag color={health.minio?.status === 'healthy' ? 'success' : 'error'}>
                  MinIO
                </Tag>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard