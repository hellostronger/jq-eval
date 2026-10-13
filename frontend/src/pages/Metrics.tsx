import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Tabs, Descriptions, Row, Col, Select, Space } from 'antd'
import { getMetrics, getMetricCategories, getMetricsByCategory } from '@/api'
import type { MetricDefinition, MetricScope } from '@/types'

// 指标市场收录两套体系：检索/生成评估（rag）与训练数据质量评估（training_data）
const SCOPE_OPTIONS = [
  { value: 'all', label: '全部指标' },
  { value: 'rag', label: 'RAG 评估指标' },
  { value: 'training_data', label: '训练数据指标' },
]

const Metrics: React.FC = () => {
  const [metrics, setMetrics] = useState<MetricDefinition[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('all')
  // 选中的作用域，null 表示不过滤（全部）
  const [scope, setScope] = useState<MetricScope | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const data = await getMetrics(scope ? { scope } : undefined)
      setMetrics(data)
    } finally {
      setLoading(false)
    }
  }

  const fetchCategories = async () => {
    try {
      const data = await getMetricCategories()
      setCategories(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchMetricsByCategory = async (category: string) => {
    if (category === 'all') {
      fetchMetrics()
      return
    }
    setLoading(true)
    try {
      const data = await getMetricsByCategory(category, scope || undefined)
      setMetrics(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCategories()
  }, [])

  // 作用域与分类是同一个查询的两个过滤条件，任一变化都要重新取数
  useEffect(() => {
    fetchMetricsByCategory(activeCategory)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCategory, scope])

  const handleTabChange = (key: string) => {
    setActiveCategory(key)
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '作用域',
      dataIndex: 'scope',
      key: 'scope',
      render: (s?: MetricScope) =>
        s === 'training_data' ? <Tag color="purple">训练数据</Tag> : <Tag>评估</Tag>,
    },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      render: (cat: string) => <Tag color="blue">{cat}</Tag>,
    },
    {
      title: '适用类型',
      dataIndex: 'data_types',
      key: 'data_types',
      render: (types?: string[] | null) =>
        types && types.length ? (
          <Space size={4} wrap>
            {types.map(t => (
              <Tag key={t} color="cyan">
                {t}
              </Tag>
            ))}
          </Space>
        ) : (
          <span style={{ color: '#999' }}>-</span>
        ),
    },
    {
      title: '阈值',
      key: 'threshold',
      render: (record: MetricDefinition) =>
        record.default_threshold != null ? (
          <span>
            {record.threshold_type} {record.default_threshold}
          </span>
        ) : (
          <span style={{ color: '#999' }}>-</span>
        ),
    },
    {
      title: '框架',
      dataIndex: 'framework',
      key: 'framework',
      render: (fw: string) => <Tag color="green">{fw}</Tag>,
    },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '依赖',
      key: 'requires',
      render: (record: MetricDefinition) => (
        <>
          {record.requires_llm && <Tag color="orange">LLM</Tag>}
          {record.requires_embedding && <Tag color="purple">Embedding</Tag>}
          {record.requires_ground_truth && <Tag color="cyan">Ground Truth</Tag>}
          {record.requires_contexts && <Tag color="magenta">Contexts</Tag>}
        </>
      ),
    },
  ]

  const tabItems = [
    { key: 'all', label: '全部' },
    ...categories.map(cat => ({ key: cat, label: cat })),
  ]

  return (
    <Card title="指标市场">
      <Space style={{ marginBottom: 12 }} wrap>
        <span>作用域</span>
        <Select
          size="small"
          style={{ width: 200 }}
          value={scope ?? 'all'}
          onChange={v => setScope(v === 'all' ? null : (v as MetricScope))}
          options={SCOPE_OPTIONS}
        />
      </Space>

      <Tabs items={tabItems} activeKey={activeCategory} onChange={handleTabChange} />

      <Table dataSource={metrics} columns={columns} rowKey="id" loading={loading} />

      <Card title="指标说明" style={{ marginTop: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Descriptions column={1} size="small" title="Ragas指标">
              <Descriptions.Item label="Faithfulness">答案对上下文的忠实度</Descriptions.Item>
              <Descriptions.Item label="Answer Relevance">答案与问题的相关性</Descriptions.Item>
              <Descriptions.Item label="Context Precision">上下文精确度</Descriptions.Item>
              <Descriptions.Item label="Context Recall">上下文召回率</Descriptions.Item>
            </Descriptions>
          </Col>
          <Col span={6}>
            <Descriptions column={1} size="small" title="EvalScope指标">
              <Descriptions.Item label="BLEU">机器翻译评估指标</Descriptions.Item>
              <Descriptions.Item label="ROUGE">文本摘要评估指标</Descriptions.Item>
              <Descriptions.Item label="BERTScore">语义相似度评估</Descriptions.Item>
            </Descriptions>
          </Col>
        </Row>
      </Card>
    </Card>
  )
}

export default Metrics