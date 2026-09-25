import React, { useEffect, useState } from 'react'
import { Card, Descriptions, Table, Tag, Tabs, Row, Col, Statistic, Button, message, Space, Modal, Switch, Alert } from 'antd'
import { useParams } from 'react-router-dom'
import { ReloadOutlined, StopOutlined } from '@ant-design/icons'
import { formatShortTime, formatTime } from '@/utils/format'
import ReactECharts from 'echarts-for-react'
import { getEvaluation, getEvaluationResults, getEvaluationAnalysis, retryEvaluationWithOption, cancelEvaluation } from '@/api'
import type { EvaluationAnalysis } from '@/api'
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
  metrics: Record<string, { mean: number; std: number; min: number; max: number; count?: number; failed_count?: number }>
  // 计算失败的指标及其原因（去重后的样本）。此前这些失败被静默丢弃，
  // 指标会直接从汇总里消失，用户看不出是系统出了问题还是没配这个指标。
  metric_errors?: Record<string, string[]>
}

const EvaluationDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null)
  const [results, setResults] = useState<EvalResult[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [analysis, setAnalysis] = useState<EvaluationAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [resultPage, setResultPage] = useState(1)
  const [resultPageSize, setResultPageSize] = useState(50)
  const [retrying, setRetrying] = useState(false)
  const [cancelling, setCancelling] = useState(false)
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

  // 服务端分页：不传参后端 limit 封顶 100，>100 条时旧实现第 3 页起永远空白
  const fetchResults = async (page = 1, pageSize = 50) => {
    if (!id) return
    setLoading(true)
    try {
      const data = await getEvaluationResults(id, { skip: (page - 1) * pageSize, limit: pageSize })
      // 后端返回 { results: [...], total, summary }，提取 results 数组和 summary
      setResults(data?.results || [])
      setTotal(data?.total || data?.results?.length || 0)
      setSummary(data?.summary || null)
      // 有结果时拉取根因分析（无结果后端返 400，静默忽略）
      if (data?.results?.length) {
        try {
          const res = await getEvaluationAnalysis(id)
          setAnalysis(res?.analysis || null)
        } catch {
          setAnalysis(null)
        }
      }
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setLoading(false)
    }
  }

  const handleRetry = async () => {
    if (!id || !evaluation) return
    setRetryModalVisible(true)
    setReuseInvocation(evaluation.reuse_invocation ?? true)
  }

  const handleCancel = async () => {
    if (!id) return
    setCancelling(true)
    try {
      const res = await cancelEvaluation(id)
      message.success(res?.message || '取消请求已提交')
      // 协作式取消：worker 在批次边界停止后状态才变 cancelled，稍后轮询刷新
      setTimeout(() => fetchEvaluation(), 3000)
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setCancelling(false)
    }
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
      setAnalysis(null)
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
      cancelled: 'warning',
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
      render: (date?: string) => formatShortTime(date),
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
                      {stats.failed_count ? (
                        <Statistic
                          title="计算失败"
                          value={stats.failed_count}
                          valueStyle={{ color: '#cf1322' }}
                        />
                      ) : null}
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>
          )}
          {summary && summary.metric_errors && Object.keys(summary.metric_errors).length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 16 }}
              message="部分指标未能计算完成"
              description={
                <div>
                  {Object.entries(summary.metric_errors).map(([metric, errs]) => (
                    <div key={metric} style={{ marginTop: 4 }}>
                      <strong>{metric}</strong>：{errs.join('；')}
                    </div>
                  ))}
                  <div style={{ marginTop: 8, color: '#666' }}>
                    这些指标的有效分数已从统计中剔除，报告里的均值仅基于成功计算的记录。
                  </div>
                </div>
              }
            />
          )}
        </>
      ),
    },
    {
      key: 'analysis',
      label: '根因分析',
      children: analysis ? (
        <>
          <Card title="根因定位" style={{ marginBottom: 16 }}>
            <Space direction="vertical">
              <span>
                瓶颈环节：
                <Tag color={analysis.root_cause.stage === 'none' ? 'green' : 'volcano'}>
                  {{ retrieval: '检索', generation: '生成', knowledge: '知识覆盖', none: '无明显瓶颈' }[analysis.root_cause.stage] || analysis.root_cause.stage}
                </Tag>
                置信度：
                <Tag color={{ high: 'red', medium: 'orange' }[analysis.root_cause.confidence] || 'default'}>
                  {{ high: '高', medium: '中', low: '低' }[analysis.root_cause.confidence] || analysis.root_cause.confidence}
                </Tag>
              </span>
              <span>
                阶段均值：
                <Tag>检索 {analysis.retrieval_analysis.average ?? '-'}</Tag>
                <Tag>生成 {analysis.generation_analysis.average ?? '-'}</Tag>
              </span>
              {analysis.weak_metrics.length > 0 && (
                <span>
                  未达标指标：
                  {analysis.weak_metrics.map(m => <Tag key={m} color="error">{m}</Tag>)}
                </span>
              )}
            </Space>
          </Card>
          <Card title="调参建议">
            <ol style={{ margin: 0, paddingLeft: 20 }}>
              {analysis.recommendations.map((r, i) => <li key={i}>{r}</li>)}
            </ol>
          </Card>
        </>
      ) : (
        <Card>暂无分析结果（评估完成后自动加载）</Card>
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
          pagination={{
            current: resultPage,
            pageSize: resultPageSize,
            total,
            showSizeChanger: true,
          }}
          onChange={(pag) => {
            // 服务端分页：翻页时按 skip/limit 重新拉取
            const p = pag.current || 1
            const s = pag.pageSize || 50
            setResultPage(p)
            setResultPageSize(s)
            fetchResults(p, s)
          }}
          scroll={{ x: 'max-content' }}
        />
      ),
    },
  ]

  return (
    <Card
      title={evaluation?.name || '评估详情'}
      extra={
        <Space>
          {evaluation?.status === 'running' && (
            <Button
              danger
              icon={<StopOutlined />}
              loading={cancelling}
              onClick={handleCancel}
            >
              取消
            </Button>
          )}
          {(evaluation?.status === 'failed' || evaluation?.status === 'cancelled') && (
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={retrying}
              onClick={handleRetry}
            >
              重试
            </Button>
          )}
        </Space>
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
          {formatTime(evaluation?.started_at)}
        </Descriptions.Item>
        <Descriptions.Item label="完成时间">
          {formatTime(evaluation?.completed_at)}
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