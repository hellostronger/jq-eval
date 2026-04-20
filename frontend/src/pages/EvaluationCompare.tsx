import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Tabs, Row, Col, Statistic, Button, Space, message } from 'antd'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { compareEvaluations } from '@/api'

interface EvalInfo {
  id: string
  name: string
  metrics: string[]
  summary: Record<string, any>
}

interface ComparisonItem {
  qa_record_id: string
  question: string
  ground_truth?: string
  scores: Record<string, Record<string, { score: number; error?: string }>>
}

interface CompareResult {
  evaluations: EvalInfo[]
  comparison: ComparisonItem[]
  summary: Record<string, Record<string, any>>
}

const EvaluationCompare: React.FC = () => {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [data, setData] = useState<CompareResult | null>(null)
  const [loading, setLoading] = useState(false)

  const ids = searchParams.get('ids')?.split(',').filter(Boolean) || []

  const fetchCompareData = async () => {
    if (ids.length < 2) {
      message.error('至少需要选择2个评估任务进行对比')
      return
    }
    setLoading(true)
    try {
      const result = await compareEvaluations(ids)
      setData(result)
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCompareData()
  }, [ids.join(',')])

  // 获取所有评估名称
  const evalNames = data?.evaluations.map(e => e.name) || []

  // 获取所有指标
  const allMetrics = data?.evaluations.flatMap(e => e.metrics) || []
  const uniqueMetrics = [...new Set(allMetrics)]

  // 构建对比表格列
  const columns = [
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
    ...evalNames.map(name => ({
      title: name,
      key: name,
      children: uniqueMetrics.map(metric => ({
        title: metric,
        key: `${name}-${metric}`,
        width: 80,
        render: (record: ComparisonItem) => {
          const scoreData = record.scores?.[name]?.[metric]
          if (!scoreData) return <Tag color="default">无</Tag>
          if (scoreData.error) return <Tag color="error">错误</Tag>
          const score = scoreData.score
          // 根据分数高低显示颜色
          const color = score >= 0.8 ? '#52c41a' : score >= 0.6 ? '#1890ff' : score >= 0.4 ? '#faad14' : '#ff4d4f'
          return <span style={{ color }}>{typeof score === 'number' ? score.toFixed(4) : score}</span>
        },
      })),
    })),
  ]

  // 构建汇总对比图表
  const barOption = {
    tooltip: { trigger: 'axis' },
    legend: { data: evalNames },
    xAxis: {
      type: 'category',
      data: uniqueMetrics,
    },
    yAxis: { type: 'value', max: 1 },
    series: evalNames.map(name => ({
      name,
      type: 'bar',
      data: uniqueMetrics.map(metric => {
        const summary = data?.summary?.[name]
        const metricStats = summary?.metrics?.[metric]
        return metricStats?.mean ?? 0
      }),
    })),
  }

  // 构建雷达图
  const radarOption = {
    tooltip: {},
    legend: { data: evalNames },
    radar: {
      indicator: uniqueMetrics.map(m => ({ name: m, max: 1 })),
    },
    series: [{
      type: 'radar',
      data: evalNames.map(name => ({
        name,
        value: uniqueMetrics.map(metric => {
          const summary = data?.summary?.[name]
          const metricStats = summary?.metrics?.[metric]
          return metricStats?.mean ?? 0
        }),
      })),
    }],
  }

  const tabItems = [
    {
      key: 'summary',
      label: '汇总对比',
      children: (
        <>
          <Row gutter={16}>
            {data?.evaluations.map(evalInfo => (
              <Col span={Math.floor(24 / data.evaluations.length)} key={evalInfo.id}>
                <Card>
                  <Statistic
                    title={`${evalInfo.name} 综合得分`}
                    value={evalInfo.summary?.overall_score || 0}
                    precision={4}
                    suffix="/ 1.0"
                  />
                </Card>
              </Col>
            ))}
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={12}>
              <Card title="指标均值对比（柱状图）">
                <ReactECharts option={barOption} style={{ height: 300 }} />
              </Card>
            </Col>
            <Col span={12}>
              <Card title="指标均值对比（雷达图）">
                <ReactECharts option={radarOption} style={{ height: 300 }} />
              </Card>
            </Col>
          </Row>
        </>
      ),
    },
    {
      key: 'detail',
      label: '详细对比',
      children: (
        <Table
          dataSource={data?.comparison || []}
          columns={columns}
          rowKey="qa_record_id"
          loading={loading}
          scroll={{ x: 'max-content' }}
          bordered
        />
      ),
    },
  ]

  return (
    <Card
      title="评估结果对比"
      extra={
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/evaluations')}>
            返回评估列表
          </Button>
        </Space>
      }
    >
      {data && (
        <>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space>
              <span>对比评估任务：</span>
              {data.evaluations.map(e => (
                <Tag key={e.id} color="blue">{e.name}</Tag>
              ))}
            </Space>
          </Card>
          <Tabs items={tabItems} />
        </>
      )}
    </Card>
  )
}

export default EvaluationCompare