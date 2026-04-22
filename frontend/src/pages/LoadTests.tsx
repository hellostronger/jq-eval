import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, InputNumber, Select, message, Space, Popconfirm, Radio, Divider, Typography } from 'antd'
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getLoadTests, createLoadTest, runLoadTest, deleteLoadTest, getRAGSystems, getDatasets } from '@/api'
import type { LoadTest, RAGSystem, Dataset, LoadTestQpsLimitResult, LoadTestLatencyDistResult } from '@/types'

const { TextArea } = Input
const { Text } = Typography

const LoadTests: React.FC = () => {
  const navigate = useNavigate()
  const [loadTests, setLoadTests] = useState<LoadTest[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [testMode, setTestMode] = useState<'qps_limit' | 'latency_dist'>('qps_limit')

  const fetchData = async () => {
    setLoading(true)
    try {
      const [testData, ragData, datasetData] = await Promise.all([
        getLoadTests().catch(() => []),
        getRAGSystems().catch(() => []),
        getDatasets().catch(() => [])
      ])
      setLoadTests(testData)
      setRAGSystems(ragData)
      setDatasets(datasetData)
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
    setModalVisible(true)
  }

  const saveLoadTest = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      // 处理questions：将文本转换为数组
      let questions: string[] | undefined
      if (values.questions) {
        questions = values.questions.split('\n').map((q: string) => q.trim()).filter((q: string) => q)
        if (questions.length === 0) questions = undefined
      }

      // 处理concurrency_levels：将文本转换为数组
      let concurrency_levels: number[] | undefined
      if (values.test_mode === 'latency_dist' && values.concurrency_levels) {
        concurrency_levels = values.concurrency_levels.split(',').map((v: string) => parseInt(v.trim())).filter((v: number) => v > 0)
        if (concurrency_levels.length === 0) concurrency_levels = undefined
      }

      await createLoadTest({
        ...values,
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

  const renderQpsLimitResult = (result: LoadTestQpsLimitResult) => (
    <Space direction="vertical" size="small">
      <div>最大QPS: <Text strong style={{ color: '#52c41a' }}>{result.max_qps.toFixed(2)}</Text></div>
      <div>对应并发: {result.max_concurrency}</div>
      <div style={{ fontSize: 12, color: '#888' }}>
        阈值: {result.latency_threshold}s, 共{result.step_results?.length || 0}步测试
      </div>
    </Space>
  )

  const renderLatencyDistResult = (result: LoadTestLatencyDistResult) => (
    <Space direction="vertical" size="small">
      <div>测试级别: {result.levels?.length || 0}个并发级别</div>
      {result.levels && result.levels.length > 0 && (
        <div style={{ fontSize: 12, color: '#888' }}>
          最高QPS: {Math.max(...result.levels.map(l => l.qps)).toFixed(2)}
        </div>
      )}
    </Space>
  )

  const renderResult = (result: LoadTest['result']) => {
    if (!result) return '-'
    if (result.test_mode === 'qps_limit') {
      return renderQpsLimitResult(result as LoadTestQpsLimitResult)
    } else {
      return renderLatencyDistResult(result as LoadTestLatencyDistResult)
    }
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
      title: 'RAG系统',
      dataIndex: 'rag_system_id',
      key: 'rag_system_id',
      render: (id: string) => ragSystems.find(r => r.id === id)?.name || id
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
      render: (_: unknown, record: LoadTest) => renderResult(record.result)
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
            <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => handleRun(record)}>
              重新测试
            </Button>
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

          <Form.Item name="rag_system_id" label="RAG系统" rules={[{ required: true }]}>
            <Select
              placeholder="选择RAG系统"
              showSearch
              optionFilterProp="label"
              options={ragSystems.map(r => ({ value: r.id, label: r.name }))}
            />
          </Form.Item>

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