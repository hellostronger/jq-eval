import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space, Progress } from 'antd'
import { PlusOutlined, PlayCircleOutlined, EyeOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getInvocationBatches, createInvocationBatch, runInvocationBatch, getInvocationResults, deleteInvocationBatch, getDatasets, getRAGSystems } from '@/api'
import type { InvocationBatch, InvocationResult, Dataset, RAGSystem } from '@/types'

const Invocations: React.FC = () => {
  const [batches, setBatches] = useState<InvocationBatch[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [resultsModalVisible, setResultsModalVisible] = useState(false)
  const [results, setResults] = useState<InvocationResult[]>([])
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [batchData, datasetData, ragData] = await Promise.all([
        getInvocationBatches(),
        getDatasets(),
        getRAGSystems(),
      ])
      setBatches(batchData)
      setDatasets(datasetData)
      setRagSystems(ragData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const showCreateDialog = () => {
    form.resetFields()
    setModalVisible(true)
  }

  const saveBatch = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createInvocationBatch(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
    } finally {
      setSaving(false)
    }
  }

  const handleRunBatch = async (batch: InvocationBatch) => {
    try {
      await runInvocationBatch(batch.id)
      message.success('调用批次已启动')
      fetchData()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleViewResults = async (batch: InvocationBatch) => {
    try {
      const data = await getInvocationResults(batch.id, { limit: 100 })
      setResults(data)
      setResultsModalVisible(true)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDelete = async (batch: InvocationBatch) => {
    if (batch.status === 'running') {
      message.warning('运行中的批次无法删除')
      return
    }
    try {
      await deleteInvocationBatch(batch.id)
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
      failed: 'error',
    }
    return types[status] || 'default'
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '数据集',
      dataIndex: 'dataset_id',
      key: 'dataset_id',
      render: (id: string) => datasets.find(d => d.id === id)?.name || id,
    },
    {
      title: 'RAG系统',
      dataIndex: 'rag_system_id',
      key: 'rag_system_id',
      render: (id: string) => ragSystems.find(r => r.id === id)?.name || id,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
    },
    {
      title: '进度',
      key: 'progress',
      render: (record: InvocationBatch) => {
        if (record.status === 'pending') return '-'
        const percent = record.total_count > 0
          ? Math.round((record.completed_count + record.failed_count) / record.total_count * 100)
          : 0
        return (
          <Space>
            <Progress percent={percent} size="small" style={{ width: 100 }} />
            <span>{record.completed_count}/{record.total_count}</span>
            {record.failed_count > 0 && <Tag color="error">{record.failed_count} 失败</Tag>}
          </Space>
        )
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: InvocationBatch) => (
        <Space>
          {record.status === 'pending' && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleRunBatch(record)}
            >
              启动
            </Button>
          )}
          {record.status === 'completed' && (
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handleViewResults(record)}
            >
              查看结果
            </Button>
          )}
          <Button
            type="link"
            size="small"
            icon={<DeleteOutlined />}
            danger
            onClick={() => handleDelete(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const resultColumns = [
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      ellipsis: true,
      width: 200,
    },
    {
      title: '答案',
      dataIndex: 'answer',
      key: 'answer',
      ellipsis: true,
      width: 300,
    },
    {
      title: '耗时(ms)',
      dataIndex: 'latency',
      key: 'latency',
      render: (latency?: number) => latency ? Math.round(latency * 1000) : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
    },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      ellipsis: true,
      render: (error?: string) => error || '-',
    },
  ]

  return (
    <Card
      title="RAG调用批次"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新建调用批次
        </Button>
      }
    >
      <Table dataSource={batches} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title="新建调用批次"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveBatch}
        confirmLoading={saving}
        width={500}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="调用批次名称" />
          </Form.Item>
          <Form.Item name="dataset_id" label="数据集" rules={[{ required: true }]}>
            <Select
              placeholder="选择数据集"
              options={datasets.map(d => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item name="rag_system_id" label="RAG系统" rules={[{ required: true }]}>
            <Select
              placeholder="选择RAG系统"
              options={ragSystems.map(r => ({ value: r.id, label: r.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="调用结果"
        open={resultsModalVisible}
        onCancel={() => setResultsModalVisible(false)}
        footer={null}
        width={900}
      >
        <Table
          dataSource={results}
          columns={resultColumns}
          rowKey="id"
          scroll={{ x: 'max-content' }}
        />
      </Modal>
    </Card>
  )
}

export default Invocations