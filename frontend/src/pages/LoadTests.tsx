import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, InputNumber, Select, message, Space, Popconfirm, Radio } from 'antd'
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getLoadTests, createLoadTest, runLoadTest, deleteLoadTest, getRAGSystems, getDatasets } from '@/api'
import type { LoadTest, RAGSystem, Dataset } from '@/types'

const { TextArea } = Input

const LoadTests: React.FC = () => {
  const navigate = useNavigate()
  const [loadTests, setLoadTests] = useState<LoadTest[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

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
    form.setFieldValue('test_type', 'full_response')
    form.setFieldValue('latency_threshold', 2)
    form.setFieldValue('concurrency', 10)
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

      await createLoadTest({
        ...values,
        questions
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

  const renderResult = (result: LoadTest['result']) => {
    if (!result) return '-'
    return (
      <Space direction="vertical" size="small">
        <div>QPS: <strong>{result.qps.toFixed(2)}</strong></div>
        <div>成功: {result.success_count}/{result.total_requests}</div>
        {result.latency_stats && (
          <div style={{ fontSize: 12, color: '#888' }}>
            延迟: 均值={result.latency_stats.mean?.toFixed(3)}s, P90={result.latency_stats.p90?.toFixed(3)}s
          </div>
        )}
      </Space>
    )
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
      title: '时延阈值',
      dataIndex: 'latency_threshold',
      key: 'latency_threshold',
      render: (v: number) => `${v}s`
    },
    {
      title: '并发数',
      dataIndex: 'concurrency',
      key: 'concurrency'
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
        width={600}
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

          <Form.Item name="test_type" label="测试类型" rules={[{ required: true }]}>
            <Radio.Group>
              <Radio.Button value="full_response">完整响应时间</Radio.Button>
              <Radio.Button value="first_token">首token时间</Radio.Button>
            </Radio.Group>
          </Form.Item>

          <Space style={{ width: '100%' }} size="large">
            <Form.Item name="latency_threshold" label="时延阈值(秒)" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={0.1} max={60} step={0.1} style={{ width: '100%' }} />
            </Form.Item>

            <Form.Item name="concurrency" label="并发数" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={1} max={100} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

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