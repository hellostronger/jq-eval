import React, { useEffect, useState } from 'react'
import { Card, Descriptions, Table, Tag, Tabs, Row, Col, Statistic, Progress } from 'antd'
import { useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import { getEvaluation, getEvaluationResults, getEvaluationSummary } from '@/api'
import type { Evaluation } from '@/types'

interface EvalResult {
  id: number
  evaluation_id: number
  qa_record_id: number
  metric_scores: Record<string, { score: number; error?: string }>
  created_at: string
}

interface Summary {
  overall_score: number
  metrics: Record<string, { mean: number; std: number; min: number; max: number }>
}

const EvaluationDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null)
  const [results, setResults] = useState<EvalResult[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchEvaluation = async () => {
    if (!id) return
    try {
      const data = await getEvaluation(Number(id))
      setEvaluation(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchResults = async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await getEvaluationResults(Number(id))
      setResults(data)
    } finally {
      setLoading(false)
    }
  }

  const fetchSummary = async () => {
    if (!id) return
    try {
      const data = await getEvaluationSummary(Number(id))
      setSummary(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  useEffect(() => {
    fetchEvaluation()
    fetchResults()
    fetchSummary()
  }, [id])

  const getStatusType = (status: string) => {
    const types: Record<string, 'success' | 'warning' | 'processing' | 'error' | 'default'> = {
      completed: 'success',
      running: 'processing',
      pending: 'default',
      failed: 'error',
    }
    return types[status] || 'default'
  }

  const metricsColumns = [
    { title: 'QA记录ID', dataIndex: 'qa_record_id', key: 'qa_record_id', width: 80 },
    ...((evaluation?.metrics || []).map(metric => ({
      title: metric,
      key: metric,
      render: (record: EvalResult) => {
        const score = record.metric_scores[metric]
        if (!score) return <Tag color="default">无</Tag>
        if (score.error) return <Tag color="error">错误</Tag>
        return <span>{score.score.toFixed(4)}</span>
      },
    }))),
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 100,
      render: (date: string) => dayjs(date).format('MM-DD HH:mm'),
    },
  ]

  const barOption = {
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: Object.keys(summary?.metrics || {}),
    },
    yAxis: { type: 'value', max: 1 },
    series: [
      {
        type: 'bar',
        data: Object.entries(summary?.metrics || {}).map(([_, v]) => ({
          value: v.mean,
          itemStyle: { color: '#1890ff' },
        })),
      },
    ],
  }

  const tabItems = [
    {
      key: 'summary',
      label: '评估摘要',
      children: (
        <>
          <Row gutter={16}>
            <Col span={8}>
              <Card>
                <Statistic
                  title="综合得分"
                  value={summary?.overall_score || 0}
                  precision={4}
                  suffix="/ 1.0"
                />
              </Card>
            </Col>
            <Col span={16}>
              <Card title="指标得分分布">
                <ReactECharts option={barOption} style={{ height: 200 }} />
              </Card>
            </Col>
          </Row>
          {summary && (
            <Card title="详细统计" style={{ marginTop: 16 }}>
              <Row gutter={16}>
                {Object.entries(summary.metrics).map(([metric, stats]) => (
                  <Col span={6} key={metric}>
                    <Card size="small" title={metric}>
                      <Statistic title="平均值" value={stats.mean} precision={4} />
                      <Statistic title="标准差" value={stats.std} precision={4} />
                      <Statistic title="最小值" value={stats.min} precision={4} />
                      <Statistic title="最大值" value={stats.max} precision={4} />
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>
          )}
        </>
      ),
    },
    {
      key: 'results',
      label: '详细结果',
      children: (
        <Table
          dataSource={results}
          columns={metricsColumns}
          rowKey="id"
          loading={loading}
          scroll={{ x: 'max-content' }}
        />
      ),
    },
  ]

  return (
    <Card title={evaluation?.name || '评估详情'}>
      <Descriptions bordered column={4} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="状态">
          <Tag color={getStatusType(evaluation?.status || '')}>{evaluation?.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="数据集ID">{evaluation?.dataset_id}</Descriptions.Item>
        <Descriptions.Item label="RAG系统ID">{evaluation?.rag_system_id || '-'}</Descriptions.Item>
        <Descriptions.Item label="LLM模型ID">{evaluation?.llm_model_id}</Descriptions.Item>
        <Descriptions.Item label="评估指标">
          {evaluation?.metrics?.map(m => <Tag key={m}>{m}</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label="批次大小">{evaluation?.batch_size}</Descriptions.Item>
        <Descriptions.Item label="开始时间">
          {evaluation?.started_at ? dayjs(evaluation.started_at).format('YYYY-MM-DD HH:mm') : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="完成时间">
          {evaluation?.completed_at ? dayjs(evaluation.completed_at).format('YYYY-MM-DD HH:mm') : '-'}
        </Descriptions.Item>
      </Descriptions>

      {evaluation?.status === 'completed' && <Tabs items={tabItems} />}
    </Card>
  )
}

export default EvaluationDetail