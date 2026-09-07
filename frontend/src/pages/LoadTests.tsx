import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, InputNumber, Select, message, Space, Popconfirm, Radio, Divider, Typography, Alert, Statistic, Row, Col, Tooltip } from 'antd'
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined, ReloadOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getLoadTests, createLoadTest, runLoadTest, deleteLoadTest, getRAGSystems, getDatasets, getModels } from '@/api'
import type { LoadTest, RAGSystem, Dataset, LoadTestQpsLimitResult, LoadTestLatencyDistResult, LoadTestErrorSummary } from '@/types'

const { TextArea } = Input
const { Text } = Typography

const STOP_REASON_TEXT: Record<string, string> = {
  request_failed: '请求失败导致终止',
  latency_exceeded: '延迟超过阈值导致终止',
  max_concurrency_reached: '达到最大并发上限，全部达标',
}

const ERROR_CATEGORY_COLORS: Record<string, string> = {
  '请求超时': 'orange',
  '连接失败': 'red',
  '鉴权失败': 'magenta',
  '限流(429)': 'gold',
  '服务端错误(5xx)': 'volcano',
  '延迟超阈值': 'purple',
  '无首token输出': 'cyan',
  '空响应': 'default',
  '请求异常': 'error',
  '其他错误': 'default',
}

const LoadTests: React.FC = () => {
  const [loadTests, setLoadTests] = useState<LoadTest[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [llmModels, setLlmModels] = useState<Array<{ id: string; name: string }>>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [detailTest, setDetailTest] = useState<LoadTest | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [form] = Form.useForm()
  const [testMode, setTestMode] = useState<'qps_limit' | 'latency_dist'>('qps_limit')
  const [targetKind, setTargetKind] = useState<'rag' | 'llm'>('rag')

  const fetchData = async () => {
    setLoading(true)
    try {
      const [testData, ragData, datasetData, modelData] = await Promise.all([
        getLoadTests().catch(() => []),
        getRAGSystems().catch(() => []),
        getDatasets().catch(() => []),
        getModels('llm').catch(() => [])
      ])
      setLoadTests(testData)
      setRAGSystems(ragData)
      setDatasets(datasetData)
      setLlmModels(modelData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const showCreateDialog = () => {
    form.resetFields()
    form.setFieldValue('test_mode', 'qps_limit')
    form.setFieldValue('test_type', 'full_response')
    form.setFieldValue('latency_threshold', 2)
    form.setFieldValue('initial_concurrency', 10)
    form.setFieldValue('step', 10)
    form.setFieldValue('max_concurrency', 100)
    form.setFieldValue('concurrency_levels', '1,5,10,20,50,100')
    setTestMode('qps_limit')
    setTargetKind('rag')
    setModalVisible(true)
  }

  const saveLoadTest = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      // 压测对象二选一：未选中的目标字段不提交
      const { rag_system_id, target_model_id, ...rest } = values
      const target = targetKind === 'rag'
        ? { rag_system_id }
        : { target_model_id }

      // 处理questions：将文本转换为数组
      let questions: string[] | undefined
      if (rest.questions) {
        questions = rest.questions.split('\n').map((q: string) => q.trim()).filter((q: string) => q)
        if (questions && questions.length === 0) questions = undefined
      }

      // 处理concurrency_levels：将文本转换为数组
      let concurrency_levels: number[] | undefined
      if (rest.test_mode === 'latency_dist' && rest.concurrency_levels) {
        concurrency_levels = rest.concurrency_levels.split(',').map((v: string) => parseInt(v.trim())).filter((v: number) => v > 0)
        if (concurrency_levels && concurrency_levels.length === 0) concurrency_levels = undefined
      }

      await createLoadTest({
        ...rest,
        ...target,
        questions,
        concurrency_levels
      })
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
    } finally {
      setSaving(false)
    }
  }

  const handleRun = async (test: LoadTest) => {
    try {
      await runLoadTest(test.id)
      message.success('压测任务已启动')
      fetchData()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDelete = async (test: LoadTest) => {
    if (test.status === 'running') {
      message.warning('运行中的任务无法删除')
      return
    }
    try {
      await deleteLoadTest(test.id)
      message.success('删除成功')
      fetchData()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const getStatusType = (status: string) => {
    const types: Record<string, 'success' | 'warning' | 'processing' | 'error' | 'default'> = {
      completed: 'success',
      running: 'processing',
      pending: 'default',
      failed: 'error'
    }
    return types[status] || 'default'
  }

  const renderQpsLimitResult = (result: LoadTestQpsLimitResult) => {
    const failed = result.step_results?.filter(s => (s.failed_count || 0) > 0).length || 0
    return (
      <Space direction="vertical" size="small">
        <div>最大QPS: <Text strong style={{ color: '#52c41a' }}>{result.max_qps.toFixed(2)}</Text></div>
        <div>对应并发: {result.max_concurrency}</div>
        {result.stop_reason && (
          <div style={{ fontSize: 12, color: result.stop_reason === 'max_concurrency_reached' ? '#52c41a' : '#fa8c16' }}>
            {STOP_REASON_TEXT[result.stop_reason] || result.stop_reason}
            {result.stopped_at_concurrency ? ` (并发=${result.stopped_at_concurrency})` : ''}
          </div>
        )}
        {failed > 0 && (
          <Tag color="error" icon={<ExclamationCircleOutlined />}>{failed}个并发级别存在失败</Tag>
        )}
        <div style={{ fontSize: 12, color: '#888' }}>
          阈值: {result.latency_threshold}s, 共{result.step_results?.length || 0}步测试
        </div>
      </Space>
    )
  }

  const renderLatencyDistResult = (result: LoadTestLatencyDistResult) => {
    const failed = result.levels?.filter(l => (l.failed_count || 0) > 0).length || 0
    return (
      <Space direction="vertical" size="small">
        <div>测试级别: {result.levels?.length || 0}个并发级别</div>
        {result.levels && result.levels.length > 0 && (
          <div style={{ fontSize: 12, color: '#888' }}>
            最高QPS: {Math.max(...result.levels.map(l => l.qps)).toFixed(2)}
          </div>
        )}
        {failed > 0 && (
          <Tag color="error" icon={<ExclamationCircleOutlined />}>{failed}个并发级别存在失败</Tag>
        )}
      </Space>
    )
  }

  const renderResult = (result: LoadTest['result'], record?: LoadTest) => {
    if (record?.error) {
      return (
        <Tooltip title={record.error}>
          <Tag color="error" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {record.error.slice(0, 50)}
          </Tag>
        </Tooltip>
      )
    }
    if (!result) return '-'
    if (result.test_mode === 'qps_limit') {
      return renderQpsLimitResult(result as LoadTestQpsLimitResult)
    } else {
      return renderLatencyDistResult(result as LoadTestLatencyDistResult)
    }
  }

  // 错误分类统计渲染
  const renderErrorSummary = (summary: LoadTestErrorSummary) => {
    const cats = Object.entries(summary.error_categories || {})
    return (
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space wrap size={4}>
          {cats.map(([cat, count]) => (
            <Tag key={cat} color={ERROR_CATEGORY_COLORS[cat] || 'default'}>
              {cat}: {count}
            </Tag>
          ))}
        </Space>
        {summary.top_errors?.length > 0 && (
          <div>
            {summary.top_errors.slice(0, 5).map((e, i) => (
              <div key={i} style={{ fontSize: 12, color: '#cf1322', wordBreak: 'break-all' }}>
                • {e}
              </div>
            ))}
          </div>
        )}
      </Space>
    )
  }

  // 结果详情弹窗（含每个并发级别的失败详情）
  const showDetail = (test: LoadTest) => {
    setDetailTest(test)
    setDetailOpen(true)
  }

  const renderDetail = () => {
    const test = detailTest
    if (!test) return null
    const result = test.result
    const steps: Array<any> = result?.test_mode === 'qps_limit'
      ? (result as LoadTestQpsLimitResult).step_results || []
      : result?.test_mode === 'latency_dist'
        ? (result as LoadTestLatencyDistResult).levels || []
        : []

    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {test.status === 'failed' && (
          <Alert
            type="error"
            showIcon
            message="任务执行失败"
            description={<div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{test.error}</div>}
          />
        )}
        {test.status === 'completed' && result?.test_mode === 'qps_limit' && (
          <Row gutter={16}>
            <Col span={8}><Statistic title="最大QPS" value={(result as LoadTestQpsLimitResult).max_qps.toFixed(2)} /></Col>
            <Col span={8}><Statistic title="最大达标并发" value={(result as LoadTestQpsLimitResult).max_concurrency} /></Col>
            <Col span={8}>
              <Statistic
                title="终止原因"
                value={STOP_REASON_TEXT[(result as LoadTestQpsLimitResult).stop_reason || ''] || '-'}
                valueStyle={{ fontSize: 14 }}
              />
            </Col>
          </Row>
        )}
        {steps.length > 0 && (
          <Table
            size="small"
            rowKey={(r: any) => r.concurrency}
            dataSource={steps}
            pagination={false}
            expandable={{
              rowExpandable: (r: any) => !!r.error_summary && Object.keys(r.error_summary.error_categories || {}).length > 0,
              expandedRowRender: (r: any) => renderErrorSummary(r.error_summary),
            }}
            columns={[
              { title: '并发', dataIndex: 'concurrency', key: 'concurrency', width: 70 },
              { title: 'QPS', dataIndex: 'qps', key: 'qps', render: (v: number) => v.toFixed(2), width: 80 },
              {
                title: '成功率',
                key: 'success_rate',
                width: 100,
                render: (_: unknown, r: any) => {
                  const rate = r.success_rate ?? 1
                  return <span style={{ color: rate < 1 ? '#cf1322' : undefined }}>{(rate * 100).toFixed(0)}%</span>
                },
              },
              {
                title: '失败数',
                key: 'failed',
                width: 80,
                render: (_: unknown, r: any) => (r.failed_count || 0) > 0
                  ? <Tag color="error">{r.failed_count}</Tag>
                  : <span>0</span>,
              },
              {
                title: '最大延迟(s)',
                key: 'max_latency',
                width: 100,
                render: (_: unknown, r: any) => r.latency_stats ? r.latency_stats.max?.toFixed(2) : '-',
              },
              {
                title: 'P99(s)',
                key: 'p99',
                width: 80,
                render: (_: unknown, r: any) => r.latency_stats ? r.latency_stats.p99?.toFixed(2) : '-',
              },
              {
                title: '达标',
                dataIndex: 'meets_threshold',
                key: 'meets_threshold',
                width: 80,
                render: (v: boolean) => <Tag color={v ? 'success' : 'warning'}>{v ? '达标' : '未达标'}</Tag>,
              },
            ]}
          />
        )}
        {steps.length === 0 && test.status === 'completed' && (
          <Alert type="info" message="暂无分步结果数据" />
        )}
      </Space>
    )
  }

  const renderTestConfig = (record: LoadTest) => {
    if (record.test_mode === 'qps_limit') {
      return (
        <Space direction="vertical" size="small">
          <div>阈值: {record.latency_threshold}s</div>
          <div style={{ fontSize: 12, color: '#888' }}>
            {record.initial_concurrency}→{record.max_concurrency} (步长{record.step})
          </div>
        </Space>
      )
    } else {
      return (
        <Space direction="vertical" size="small">
          <div>级别: {(record.concurrency_levels || []).join(',')}</div>
          {record.latency_threshold && (
            <div style={{ fontSize: 12, color: '#888' }}>阈值: {record.latency_threshold}s</div>
          )}
        </Space>
      )
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '压测对象',
      key: 'target',
      render: (_: unknown, record: LoadTest) => {
        if (record.target_model_id) {
          const name = llmModels.find(m => m.id === record.target_model_id)?.name
          return <Tag color="geekblue">模型: {name || record.target_model_id.slice(0, 8)}</Tag>
        }
        const name = ragSystems.find(r => r.id === record.rag_system_id)?.name
        return <Tag color="purple">RAG: {name || record.rag_system_id?.slice(0, 8) || '-'}</Tag>
      }
    },
    {
      title: '测试模式',
      dataIndex: 'test_mode',
      key: 'test_mode',
      render: (mode: string) => (
        <Tag color={mode === 'qps_limit' ? 'purple' : 'cyan'}>
          {mode === 'qps_limit' ? 'QPS上限测试' : '响应时间分布'}
        </Tag>
      )
    },
    {
      title: '测试类型',
      dataIndex: 'test_type',
      key: 'test_type',
      render: (type: string) => (
        <Tag color={type === 'first_token' ? 'blue' : 'green'}>
          {type === 'first_token' ? '首token' : '完整响应'}
        </Tag>
      )
    },
    {
      title: '测试配置',
      key: 'config',
      render: (_: unknown, record: LoadTest) => renderTestConfig(record)
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>
    },
    {
      title: '结果',
      key: 'result',
      render: (_: unknown, record: LoadTest) => renderResult(record.result, record)
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm')
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: LoadTest) => (
        <Space>
          {record.status === 'pending' && (
            <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => handleRun(record)}>
              启动
            </Button>
          )}
          {record.status === 'running' && (
            <Tag color="processing">运行中</Tag>
          )}
          {(record.status === 'completed' || record.status === 'failed') && (
            <>
              <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => handleRun(record)}>
                重新测试
              </Button>
              <Button type="link" size="small" onClick={() => showDetail(record)}>
                详情
              </Button>
            </>
          )}
          {record.status !== 'running' && (
            <Popconfirm title="确定删除?" onConfirm={() => handleDelete(record)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      )
    }
  ]

  return (
    <Card
      title="性能压测"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新建压测
        </Button>
      }
    >
      <Table dataSource={loadTests} columns={columns} rowKey="id" loading={loading} />

      {/* 结果详情弹窗 */}
      <Modal
        title={`压测详情 - ${detailTest?.name || ''}`}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={920}
      >
        {renderDetail()}
      </Modal>

      <Modal
        title="新建压测任务"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveLoadTest}
        confirmLoading={saving}
        width={650}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="压测任务名称" />
          </Form.Item>

          <Form.Item label="压测对象" style={{ marginBottom: 8 }}>
            <Radio.Group value={targetKind} onChange={(e) => setTargetKind(e.target.value)}>
              <Radio.Button value="rag">RAG系统</Radio.Button>
              <Radio.Button value="llm">大模型直连</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {targetKind === 'rag' ? (
            <Form.Item name="rag_system_id" label="RAG系统" rules={[{ required: true, message: '请选择RAG系统' }]}>
              <Select
                placeholder="选择RAG系统"
                showSearch
                optionFilterProp="label"
                options={ragSystems.map(r => ({ value: r.id, label: r.name }))}
              />
            </Form.Item>
          ) : (
            <Form.Item
              name="target_model_id"
              label="大模型"
              rules={[{ required: true, message: '请选择大模型' }]}
              extra="直接对模型发压测请求（走直连LLM适配器），适合评估模型服务本身的吞吐与延迟"
            >
              <Select
                placeholder="选择 LLM 模型"
                showSearch
                optionFilterProp="label"
                options={llmModels.map(m => ({ value: m.id, label: m.name }))}
              />
            </Form.Item>
          )}

          <Form.Item name="test_mode" label="测试模式" rules={[{ required: true }]}>
            <Radio.Group onChange={(e) => setTestMode(e.target.value)}>
              <Radio.Button value="qps_limit">QPS上限测试</Radio.Button>
              <Radio.Button value="latency_dist">响应时间分布</Radio.Button>
            </Radio.Group>
          </Form.Item>

          <Form.Item name="test_type" label="测试类型" rules={[{ required: true }]}>
            <Radio.Group>
              <Radio.Button value="full_response">完整响应时间</Radio.Button>
              <Radio.Button value="first_token">首token时间</Radio.Button>
            </Radio.Group>
          </Form.Item>

          <Divider />

          {/* QPS上限测试参数 */}
          {testMode === 'qps_limit' && (
            <>
              <Form.Item
                name="latency_threshold"
                label="时延阈值(秒)"
                rules={[{ required: true, message: 'QPS上限测试需要设置时延阈值' }]}
              >
                <InputNumber min={0.1} max={60} step={0.1} style={{ width: '100%' }} />
              </Form.Item>

              <Space style={{ width: '100%' }} size="large">
                <Form.Item name="initial_concurrency" label="起始并发" style={{ flex: 1 }}>
                  <InputNumber min={1} max={500} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="step" label="递增步长" style={{ flex: 1 }}>
                  <InputNumber min={1} max={100} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="max_concurrency" label="最大并发" style={{ flex: 1 }}>
                  <InputNumber min={1} max={1000} style={{ width: '100%' }} />
                </Form.Item>
              </Space>
            </>
          )}

          {/* 响应时间分布测试参数 */}
          {testMode === 'latency_dist' && (
            <>
              <Form.Item
                name="concurrency_levels"
                label="并发级别"
                rules={[{ required: true, message: '请输入并发级别' }]}
                extra="多个并发级别用逗号分隔，如: 1,5,10,20,50,100"
              >
                <Input placeholder="1,5,10,20,50,100" />
              </Form.Item>

              <Form.Item
                name="latency_threshold"
                label="时延阈值(秒)"
                extra="可选，仅用于标记是否达标"
              >
                <InputNumber min={0.1} max={60} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          <Divider />

          <Form.Item name="dataset_id" label="测试数据来源(可选)">
            <Select
              placeholder="选择数据集"
              allowClear
              showSearch
              optionFilterProp="label"
              options={datasets.map(d => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>

          <Form.Item name="questions" label="或手动输入测试问题(每行一个)">
            <TextArea rows={4} placeholder="在此输入测试问题，每行一个" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default LoadTests