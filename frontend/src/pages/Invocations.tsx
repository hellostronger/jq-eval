import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, InputNumber, Select, message, Space, Progress, Popconfirm, Tooltip } from 'antd'
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined, ReloadOutlined, FileSearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { formatTime } from '@/utils/format'
import { usePollingWhenRunning } from '@/hooks/usePollingWhenRunning'
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

  // 有批次运行中/排队中时自动轮询刷新进度，全部结束后停止
  usePollingWhenRunning(
    batches.some((b) => b.status === 'running' || b.status === 'pending'),
    fetchData,
    5000,
  )

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

  // 派发后立刻刷新会读回旧状态（Celery 尚未把批次置为 running），
  // 轮询条件不成立，进度永远停在原地。本地先乐观标记，真实状态交给轮询回填。
  const markRunning = (batchId: string) =>
    setBatches((prev) => prev.map((b) => (b.id === batchId ? { ...b, status: 'running' } : b)))

  const handleRunBatch = async (batch: InvocationBatch) => {
    try {
      await runInvocationBatch(batch.id)
      message.success('调用批次已启动')
      markRunning(batch.id)
    } catch (e) {
      // 错误已在拦截器处理
      fetchData()
    }
  }

  const handleRetryBatch = async (batch: InvocationBatch) => {
    try {
      const res = await retryInvocationBatch(batch.id)
      message.success(`重试任务已启动，将重试 ${res.retry_count || batch.failed_count} 条失败记录`)
      markRunning(batch.id)
    } catch (e) {
      // 错误已在拦截器处理
      fetchData()
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
      // 派发时就置 running，worker 真正领取才写 started_at。solo 队列一次只跑一个任务，
      // 后建的批次会在 running 上停几十分钟——不区分开，界面看着像卡死，其实还在排队。
      render: (status: string, record: InvocationBatch) => {
        if (status === 'running' && !record.started_at) {
          return (
            <Tooltip title="已派发，正在队列里等 worker 领取（worker 单并发，前面还有任务在跑）">
              <Tag color="default">排队中</Tag>
            </Tooltip>
          )
        }
        return <Tag color={getStatusType(status)}>{status}</Tag>
      },
    },
    {
      title: '进度',
      key: 'progress',
      render: (record: InvocationBatch) => {
        if (record.status === 'pending') return '-'
        const percent = record.total_count > 0
          ? Math.round((record.completed_count + record.failed_count) / record.total_count * 100)
          : 0
        // 分母是取样条数而不是数据集大小，得标出来，否则"40/40 完成"会被读成整库跑完
        const scoped = (record.qa_limit ?? null) !== null || (record.qa_offset ?? null) !== null
        return (
          <Space>
            <Progress percent={percent} size="small" style={{ width: 100 }} />
            <span>{record.completed_count}/{record.total_count}</span>
            {record.failed_count > 0 && <Tag color="error">{record.failed_count} 失败</Tag>}
            {scoped && (
              <Tooltip title={`本批只跑取样范围：起点 ${record.qa_offset ?? 0}，条数 ${record.qa_limit ?? '到结尾'}`}>
                <Tag color="warning">取样</Tag>
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => formatTime(date),
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
          {/* 取样范围：大语料（几千题、单题几分钟）先跑一小段验证链路，
              不必为此复制一个小数据集——副本一多，各批次的评估口径就对不上了 */}
          <Form.Item
            name="qa_limit"
            label="取样条数"
            tooltip="按题目创建顺序只跑前 N 条。留空＝跑整个数据集（原有行为）。"
          >
            <InputNumber min={1} precision={0} placeholder="留空＝整个数据集" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="qa_offset"
            label="取样起点"
            tooltip="跳过前 M 条，配合取样条数分页试点：跑第 41–80 题就是起点 40、条数 40。"
          >
            <InputNumber min={0} precision={0} placeholder="0（从头开始）" style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Invocations