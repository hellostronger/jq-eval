import React, { useEffect, useState } from 'react'
import { Card, Descriptions, Table, Tag, Tabs, Row, Col, Statistic, Button, message, Space, Modal, Switch } from 'antd'
import { useParams } from 'react-router-dom'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import { getEvaluation, getEvaluationResults, retryEvaluationWithOption } from '@/api'
import type { Evaluation } from '@/types'

interface EvalResult {
  id: string
  qa_record_id: string
  question: string
  answer?: string
  ground_truth?: string
  metric_scores: Record<string, { score: number; error?: string }>
  details?: Record<string, any>
  created_at?: string
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
  const [retrying, setRetrying] = useState(false)
  const [retryModalVisible, setRetryModalVisible] = useState(false)
  const [reuseInvocation, setReuseInvocation] = useState(true)

  const fetchEvaluation = async () => {
    if (!id) return
    try {
      const data = await getEvaluation(id)
      setEvaluation(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchResults = async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await getEvaluationResults(id)
      // 后端返回 { results: [...], summary: ... }，提取 results 数组和 summary
      setResults(data?.results || [])
      setSummary(data?.summary || null)
    } finally {
      setLoading(false)
    }
  }

  const handleRetry = async () => {
    if (!id || !evaluation) return
    setRetryModalVisible(true)
    setReuseInvocation(evaluation.reuse_invocation ?? true)
  }

  const confirmRetry = async () => {
    if (!id) return
    setRetrying(true)
    try {
      await retryEvaluationWithOption(id, reuseInvocation)
      message.success('评估任务已重新启动')
      setRetryModalVisible(false)
      // 刷新评估信息
      await fetchEvaluation()
      setResults([])
      setSummary(null)
    } catch (e) {
      message.error('重试失败')
    } finally {
      setRetrying(false)
    }
  }

  useEffect(() => {
    fetchEvaluation()
    fetchResults()
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
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      width: 200,
      ellipsis: true,
      render: (text: string) => <span title={text}>{text}</span>,
    },
    {
      title: '参考答案',
      dataIndex: 'ground_truth',
      key: 'ground_truth',
      width: 150,
      ellipsis: true,
      render: (text?: string) => text ? <span title={text}>{text}</span> : '-',
    },
    ...((evaluation?.metrics || []).map(metric => ({
      title: metric,
      key: metric,
      width: 100,
      render: (record: EvalResult) => {
        const score = record.metric_scores?.[metric]
        if (!score) return <Tag color="default">无</Tag>
        if (score.error) return <Tag color="error">错误</Tag>
        return <span>{typeof score.score === 'number' ? score.score.toFixed(4) : score.score}</span>
      },
    }))),
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 100,
      render: (date?: string) => date ? dayjs(date).format('MM-DD HH:mm') : '-',
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
          {summary && summary.metrics && (
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
    <Card
      title={evaluation?.name || '评估详情'}
      extra={
        evaluation?.status === 'failed' && (
          <Space>
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={retrying}
              onClick={handleRetry}
            >
              重试
            </Button>
          </Space>
        )
      }
    >
      <Descriptions bordered column={4} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="状态">
          <Tag color={getStatusType(evaluation?.status || '')}>{evaluation?.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="数据集ID">{evaluation?.dataset_id}</Descriptions.Item>
        <Descriptions.Item label="RAG系统ID">{evaluation?.rag_system_id || '-'}</Descriptions.Item>
        <Descriptions.Item label="LLM模型ID">{evaluation?.llm_model_id}</Descriptions.Item>
        <Descriptions.Item label="调用批次ID">{evaluation?.invocation_batch_id || '-'}</Descriptions.Item>
        <Descriptions.Item label="复用调用结果">
          <Tag color={evaluation?.reuse_invocation ? 'green' : 'orange'}>
            {evaluation?.reuse_invocation ? '是' : '否'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="批次大小">{evaluation?.batch_size}</Descriptions.Item>
        <Descriptions.Item label="评估指标">
          {evaluation?.metrics?.map(m => <Tag key={m}>{m}</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label="开始时间">
          {evaluation?.started_at ? dayjs(evaluation.started_at).format('YYYY-MM-DD HH:mm') : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="完成时间">
          {evaluation?.completed_at ? dayjs(evaluation.completed_at).format('YYYY-MM-DD HH:mm') : '-'}
        </Descriptions.Item>
      </Descriptions>

      {evaluation?.status === 'completed' && <Tabs items={tabItems} />}

      <Modal
        title="重试评估任务"
        open={retryModalVisible}
        onCancel={() => setRetryModalVisible(false)}
        onOk={confirmRetry}
        confirmLoading={retrying}
      >
        <div style={{ marginBottom: 16 }}>
          <p>请选择重试时的调用结果处理方式：</p>
          <Space>
            <span>复用存量调用结果：</span>
            <Switch checked={reuseInvocation} onChange={setReuseInvocation} />
          </Space>
          <p style={{ marginTop: 8, color: '#666' }}>
            {reuseInvocation
              ? '开启后将使用已有的调用结果进行评估，仅重新计算指标得分。'
              : '关闭后将重新调用RAG系统获取新的答案和上下文，然后再进行评估。'}
          </p>
        </div>
      </Modal>
    </Card>
  )
}

export default EvaluationDetail