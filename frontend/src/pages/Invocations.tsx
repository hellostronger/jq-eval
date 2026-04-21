import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space, Progress, Popconfirm } from 'antd'
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined, ReloadOutlined, FileSearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getInvocationBatches, createInvocationBatch, runInvocationBatch, retryInvocationBatch, deleteInvocationBatch, getDatasets, getRAGSystems } from '@/api'
import type { InvocationBatch, Dataset, RAGSystem } from '@/types'

const Invocations: React.FC = () => {
  const navigate = useNavigate()
  const [batches, setBatches] = useState<InvocationBatch[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [batchData, datasetData, ragData] = await Promise.all([
        getInvocationBatches().catch(() => []),
        getDatasets().catch(() => []),
        getRAGSystems().catch(() => []),
      ])
      setBatches(batchData)
      setDatasets(datasetData)
      setRAGSystems(ragData)
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

  const handleRetryBatch = async (batch: InvocationBatch) => {
    try {
      const res = await retryInvocationBatch(batch.id)
      message.success(`重试任务已启动，将重试 ${res.retry_count || batch.failed_count} 条失败记录`)
      fetchData()
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
          <Button
            type="link"
            size="small"
            icon={<FileSearchOutlined />}
            onClick={() => navigate(`/invocations/${record.id}`)}
          >
            详情
          </Button>
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
          {(record.status === 'completed' || record.status === 'failed') && record.failed_count > 0 && (
            <Popconfirm
              title="重试失败记录"
              description={`确定重试 ${record.failed_count} 条失败记录？`}
              onConfirm={() => handleRetryBatch(record)}
            >
              <Button
                type="link"
                size="small"
                icon={<ReloadOutlined />}
              >
                重试
              </Button>
            </Popconfirm>
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
              showSearch
              optionFilterProp="label"
              getPopupContainer={(triggerNode) => triggerNode.parentElement || document.body}
              options={datasets.map(d => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item name="rag_system_id" label="RAG系统" rules={[{ required: true }]}>
            <Select
              placeholder="选择RAG系统"
              showSearch
              optionFilterProp="label"
              getPopupContainer={(triggerNode) => triggerNode.parentElement || document.body}
              options={ragSystems.map(r => ({ value: r.id, label: r.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Invocations