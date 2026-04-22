import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Button, Tag, Space, Progress, message, Popconfirm, Modal, Input, Pagination, Spin } from 'antd'
import { ReloadOutlined, PlayCircleOutlined, ArrowLeftOutlined, EyeOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getInvocationBatch,
  getInvocationResults,
  getInvocationStats,
  retryInvocationBatch,
  retrySingleResult,
  getDatasets,
  getRAGSystems,
} from '@/api'
import type { InvocationBatch, InvocationResult, Dataset, RAGSystem } from '@/types'

const InvocationDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [batch, setBatch] = useState<InvocationBatch | null>(null)
  const [results, setResults] = useState<InvocationResult[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [selectedResult, setSelectedResult] = useState<InvocationResult | null>(null)

  const fetchData = async () => {
    if (!id) return
    setLoading(true)
    try {
      const [batchData, resultsData, datasetData, ragData] = await Promise.all([
        getInvocationBatch(id),
        getInvocationResults(id, { skip: (page - 1) * pageSize, limit: pageSize, status: statusFilter }),
        getDatasets(),
        getRAGSystems(),
      ])
      setBatch(batchData)
      setResults(resultsData)
      setDatasets(datasetData)
      setRagSystems(ragData)
      setTotal(batchData.total_count)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [id, page, pageSize, statusFilter])

  const handleRetryAllFailed = async () => {
    if (!id) return
    try {
      const res = await retryInvocationBatch(id)
      message.success(`重试任务已启动，将重试 ${res.retry_count} 条失败记录`)
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const handleRetrySelected = async () => {
    if (!id || selectedRowKeys.length === 0) return
    try {
      const res = await retryInvocationBatch(id, selectedRowKeys as string[])
      message.success(`重试任务已启动，将重试 ${selectedRowKeys.length} 条记录`)
      setSelectedRowKeys([])
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const handleRetrySingle = async (resultId: string) => {
    if (!id) return
    try {
      await retrySingleResult(id, resultId)
      message.success('重试任务已启动')
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const handleViewDetail = (result: InvocationResult) => {
    setSelectedResult(result)
    setDetailModalVisible(true)
  }

  const getStatusType = (status: string) => {
    const types: Record<string, 'success' | 'warning' | 'processing' | 'error' | 'default'> = {
      success: 'success',
      pending: 'warning',
      failed: 'error',
    }
    return types[status] || 'default'
  }

  const datasetName = datasets.find(d => d.id === batch?.dataset_id)?.name || batch?.dataset_id || ''
  const ragSystemName = ragSystems.find(r => r.id === batch?.rag_system_id)?.name || batch?.rag_system_id || ''

  const columns = [
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      ellipsis: true,
      width: 250,
    },
    {
      title: '标准答案',
      dataIndex: 'ground_truth',
      key: 'ground_truth',
      ellipsis: true,
      width: 200,
      render: (truth?: string) => truth ? (truth.length > 50 ? truth.slice(0, 50) + '...' : truth) : '-',
    },
    {
      title: '答案',
      dataIndex: 'answer',
      key: 'answer',
      ellipsis: true,
      width: 300,
      render: (answer?: string) => answer ? (answer.length > 100 ? answer.slice(0, 100) + '...' : answer) : '-',
    },
    {
      title: '耗时(ms)',
      dataIndex: 'latency',
      key: 'latency',
      width: 100,
      render: (latency?: number) => latency ? Math.round(latency * 1000) : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
    },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      ellipsis: true,
      width: 200,
      render: (error?: string) => error || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: InvocationResult) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          {record.status === 'failed' && (
            <Button
              type="link"
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => handleRetrySingle(record.id)}
            >
              重试
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedKeys)
    },
  }

  if (!batch) {
    return <Spin />
  }

  return (
    <Card
      title={
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/invocations')}>
            返回
          </Button>
          <span>{batch.name}</span>
        </Space>
      }
      extra={
        <Space>
          {batch.failed_count > 0 && (
            <Popconfirm
              title="重试所有失败记录"
              description={`确定重试 ${batch.failed_count} 条失败记录？`}
              onConfirm={handleRetryAllFailed}
            >
              <Button icon={<ReloadOutlined />}>
                重试全部失败 ({batch.failed_count})
              </Button>
            </Popconfirm>
          )}
          {selectedRowKeys.length > 0 && (
            <Popconfirm
              title="重试选中记录"
              onConfirm={handleRetrySelected}
            >
              <Button type="primary" icon={<PlayCircleOutlined />}>
                重试选中 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
        </Space>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <Space size="large}>
          <span>数据集: <Tag color="blue">{datasetName}</Tag></span>
          <span>RAG系统: <Tag color="green">{ragSystemName}</Tag></span>
          <span>状态: <Tag color={getStatusType(batch.status)}>{batch.status}</Tag></span>
          <span>进度:
            <Progress
              percent={batch.total_count > 0 ? Math.round((batch.completed_count + batch.failed_count) / batch.total_count * 100) : 0}
              size="small"
              style={{ width: 100, marginLeft: 8 }}
            />
          </span>
          <span>完成: {batch.completed_count}/{batch.total_count}</span>
          {batch.failed_count > 0 && <span><Tag color="error">{batch.failed_count} 失败</Tag></span>}
          {batch.started_at && <span>开始: {dayjs(batch.started_at).format('YYYY-MM-DD HH:mm:ss')}</span>}
          {batch.completed_at && <span>完成: {dayjs(batch.completed_at).format('YYYY-MM-DD HH:mm:ss')}</span>}
        </Space>
      </div>

      <div style={{ marginBottom: 16 }}>
        <Space>
          <span>筛选状态:</span>
          <Tag
            color={statusFilter === undefined ? 'blue' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setStatusFilter(undefined)}
          >
            全部
          </Tag>
          <Tag
            color={statusFilter === 'success' ? 'green' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setStatusFilter('success')}
          >
            成功
          </Tag>
          <Tag
            color={statusFilter === 'failed' ? 'red' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setStatusFilter('failed')}
          >
            失败
          </Tag>
        </Space>
      </div>

      <Table
        dataSource={results}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={rowSelection}
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
        }}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="调用结果详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={800}
      >
        {selectedResult && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <strong>状态:</strong> <Tag color={getStatusType(selectedResult.status)}>{selectedResult.status}</Tag>
              {selectedResult.latency && <span style={{ marginLeft: 16 }}><strong>耗时:</strong> {Math.round(selectedResult.latency * 1000)} ms</span>}
            </div>
            <div style={{ marginBottom: 16 }}>
              <strong>问题:</strong>
              <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                {selectedResult.question}
              </div>
            </div>
            {selectedResult.ground_truth && (
              <div style={{ marginBottom: 16 }}>
                <strong>标准答案:</strong>
                <div style={{ padding: 8, background: '#e6f7ff', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.ground_truth}
                </div>
              </div>
            )}
            {selectedResult.answer && (
              <div style={{ marginBottom: 16 }}>
                <strong>答案:</strong>
                <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.answer}
                </div>
              </div>
            )}
            {selectedResult.contexts && selectedResult.contexts.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <strong>上下文 ({selectedResult.contexts.length} 条):</strong>
                {selectedResult.contexts.map((ctx, idx) => (
                  <div key={idx} style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                    {ctx}
                  </div>
                ))}
              </div>
            )}
            {selectedResult.error && (
              <div style={{ marginBottom: 16 }}>
                <strong>错误信息:</strong>
                <div style={{ padding: 8, background: '#fff2f0', borderRadius: 4, marginTop: 8, color: '#ff4d4f' }}>
                  {selectedResult.error}
                </div>
              </div>
            )}
            {selectedResult.status === 'failed' && (
              <Button type="primary" icon={<ReloadOutlined />} onClick={() => {
                handleRetrySingle(selectedResult.id)
                setDetailModalVisible(false)
              }}>
                重试此条
              </Button>
            )}
          </div>
        )}
      </Modal>
    </Card>
  )
}

export default InvocationDetail