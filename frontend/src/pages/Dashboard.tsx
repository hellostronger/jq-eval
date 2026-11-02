import React, { useEffect, useState } from 'react'
import { Button, Card, Table, Tag } from 'antd'
import {
  ApiOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  LineChartOutlined,
  PlusOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { AxiosError } from 'axios'
import { useNavigate } from 'react-router-dom'
import { formatShortTime } from '@/utils/format'
import { getSystemStats, getHealth, getEvaluations } from '@/api'
import type { HealthStatus } from '@/api'
import type { SystemStats, Evaluation } from '@/types'

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  running: '运行中',
  pending: '待执行',
  failed: '失败',
  cancelled: '已取消',
}

const Dashboard: React.FC = () => {
  const navigate = useNavigate()
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
    let cancelled = false
    const fetchData = async () => {
      const [statsData, healthData, evals] = await Promise.allSettled([
        getSystemStats(),
        getHealth(),
        getEvaluations({ limit: 5 }),
      ])
      if (cancelled) return
      if (statsData.status === 'fulfilled') setStats(statsData.value)
      if (healthData.status === 'fulfilled') {
        setHealth(healthData.value.services || {})
      } else {
        const err = healthData.reason as AxiosError<HealthStatus>
        setHealth(err?.response?.data?.services || {})
      }
      if (evals.status === 'fulfilled') setRecentEvals(evals.value.slice(0, 5))
    }
    fetchData()
    return () => { cancelled = true }
  }, [])

  const pieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 个任务' },
    title: {
      text: String(stats.evaluations.total),
      subtext: '全部任务',
      left: 'center',
      top: '34%',
      textStyle: { fontSize: 30, fontWeight: 700, color: '#242522' },
      subtextStyle: { fontSize: 12, color: '#9b9a92', lineHeight: 24 },
    },
    series: [
      {
        type: 'pie',
        center: ['50%', '50%'],
        radius: ['62%', '82%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: '#ffffff', borderWidth: 4, borderRadius: 6 },
        data: [
          { value: stats.evaluations.completed, name: '已完成', itemStyle: { color: '#42826a' } },
          { value: stats.evaluations.running, name: '运行中', itemStyle: { color: '#c36342' } },
          { value: stats.evaluations.pending, name: '待执行', itemStyle: { color: '#b6812c' } },
          { value: stats.evaluations.failed, name: '失败', itemStyle: { color: '#bc5a57' } },
        ],
      },
    ],
  }

  const evalColumns = [
    {
      title: '评估任务',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <span className="table-primary-text">{name}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const types: Record<string, 'success' | 'warning' | 'processing' | 'error' | 'default'> = {
          completed: 'success', running: 'processing', pending: 'default', failed: 'error', cancelled: 'warning',
        }
        return <Tag color={types[status] || 'default'}>{STATUS_LABELS[status] || status}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date: string) => formatShortTime(date),
    },
    {
      title: '',
      key: 'action',
      width: 64,
      render: (_: unknown, record: Evaluation) => (
        <Button type="text" aria-label="查看评估详情" icon={<ArrowRightOutlined />} onClick={() => navigate(`/evaluations/${record.id}`)} />
      ),
    },
  ]

  const statCards = [
    { label: '数据集', value: stats.total_datasets, unit: '个数据集', icon: <FolderOpenOutlined />, tone: 'violet' },
    { label: 'QA 样本', value: stats.total_qa_records, unit: '条问答样本', icon: <FileTextOutlined />, tone: 'blue' },
    { label: '评估任务', value: stats.evaluations.total, unit: `${stats.evaluations.running} 个正在运行`, icon: <LineChartOutlined />, tone: 'amber' },
    { label: 'RAG 系统', value: stats.total_rag_systems, unit: '个已接入系统', icon: <ApiOutlined />, tone: 'green' },
  ]

  const healthServices = [
    { key: 'database', name: 'PostgreSQL', description: '业务数据与评估结果' },
    { key: 'redis', name: 'Redis', description: '任务队列与缓存' },
    { key: 'milvus', name: 'Milvus', description: '向量索引与检索' },
    { key: 'minio', name: 'MinIO', description: '文件与对象存储' },
  ]

  const statusItems = [
    { key: 'completed', value: stats.evaluations.completed, color: '#42826a' },
    { key: 'running', value: stats.evaluations.running, color: '#c36342' },
    { key: 'pending', value: stats.evaluations.pending, color: '#b6812c' },
    { key: 'failed', value: stats.evaluations.failed, color: '#bc5a57' },
  ]

  return (
    <div className="dashboard-page">
      <section className="dashboard-hero">
        <div className="hero-orb hero-orb-one" />
        <div className="hero-orb hero-orb-two" />
        <div className="hero-copy">
          <div className="hero-kicker"><span />EVALUATION OVERVIEW</div>
          <h2>让每一次模型迭代<br /><em>都有据可依。</em></h2>
          <p>从数据集、系统调用到指标评估，在一个工作区完成完整的质量闭环。</p>
          <div className="hero-actions">
            <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => navigate('/evaluations')}>开始新评估</Button>
            <Button size="large" onClick={() => navigate('/datasets')}>管理数据集<ArrowRightOutlined /></Button>
          </div>
        </div>
        <div className="hero-summary">
          <div className="hero-summary-label"><span>当前评估规模</span><i>LIVE</i></div>
          <strong>{stats.evaluations.total}</strong>
          <span className="hero-summary-unit">累计评估任务</span>
          <div className="hero-summary-grid">
            <div><span>已完成</span><b>{stats.evaluations.completed}</b></div>
            <div><span>运行中</span><b>{stats.evaluations.running}</b></div>
          </div>
        </div>
      </section>

      <section className="dashboard-stats">
        {statCards.map(item => (
          <div className="stat-card" key={item.label}>
            <div className={`stat-icon stat-icon-${item.tone}`}>{item.icon}</div>
            <div className="stat-content">
              <span className="stat-label">{item.label}</span>
              <div className="stat-value">{item.value}</div>
              <span className="stat-unit">{item.unit}</span>
            </div>
          </div>
        ))}
      </section>

      <section className="dashboard-insights">
        <Card className="evaluation-chart-card" title="评估任务分布" extra={<span className="card-caption">实时任务概况</span>}>
          <div className="evaluation-chart-content">
            <ReactECharts option={pieOption} style={{ height: 238, minWidth: 260 }} />
            <div className="evaluation-legend">
              {statusItems.map(item => (
                <div className="evaluation-legend-row" key={item.key}>
                  <span className="legend-name"><i style={{ background: item.color }} />{STATUS_LABELS[item.key]}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <div className="dashboard-side-stack">
          <Card title="系统健康" extra={<span className="health-live"><i />实时状态</span>}>
            <div className="health-list">
              {healthServices.map(service => {
                const status = health[service.key]?.status
                const healthy = status === 'healthy'
                return (
                  <div className="health-row" key={service.key}>
                    <div className={`health-icon ${healthy ? 'healthy' : status ? 'unhealthy' : 'checking'}`}>
                      {healthy ? <CheckCircleOutlined /> : <ApiOutlined />}
                    </div>
                    <div className="health-copy"><strong>{service.name}</strong><span>{service.description}</span></div>
                    <span className={`health-status ${healthy ? 'healthy' : status ? 'unhealthy' : 'checking'}`}>
                      {healthy ? '正常' : status ? '异常' : '检测中'}
                    </span>
                  </div>
                )
              })}
            </div>
          </Card>

          <Card title="模型资源" extra={<Button type="link" onClick={() => navigate('/models')}>管理模型</Button>}>
            <div className="model-resource-list">
              {[
                { label: 'LLM', value: stats.models.llm, tone: 'violet' },
                { label: 'Embedding', value: stats.models.embedding, tone: 'blue' },
                { label: 'Reranker', value: stats.models.reranker, tone: 'green' },
              ].map(model => (
                <div className="model-resource" key={model.label}>
                  <div className={`model-resource-icon stat-icon-${model.tone}`}><RobotOutlined /></div>
                  <span>{model.label}</span>
                  <strong>{model.value}</strong>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </section>

      <Card
        className="recent-evaluations-card"
        title="最近评估"
        extra={<Button type="link" onClick={() => navigate('/evaluations')}>查看全部<ArrowRightOutlined /></Button>}
      >
        <Table
          dataSource={recentEvals}
          columns={evalColumns}
          rowKey="id"
          pagination={false}
          locale={{ emptyText: '还没有评估任务，从「开始新评估」创建第一个任务' }}
        />
      </Card>
    </div>
  )
}

export default Dashboard
