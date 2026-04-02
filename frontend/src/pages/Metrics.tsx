import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Tabs, Descriptions, Row, Col } from 'antd'
import { getMetrics, getMetricCategories, getMetricsByCategory } from '@/api'
import type { MetricDefinition } from '@/types'

const Metrics: React.FC = () => {
  const [metrics, setMetrics] = useState<MetricDefinition[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [loading, setLoading] = useState(false)

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const data = await getMetrics()
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
      const data = await getMetricsByCategory(category)
      setMetrics(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMetrics()
    fetchCategories()
  }, [])

  const handleTabChange = (key: string) => {
    setActiveCategory(key)
    fetchMetricsByCategory(key)
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      render: (cat: string) => <Tag color="blue">{cat}</Tag>,
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