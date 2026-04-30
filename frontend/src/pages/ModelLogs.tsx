import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tabs, Tag, Modal, Form, Select, Space, Drawer, Descriptions, Input, message, Popconfirm, Spin, Alert, Divider, Typography } from 'antd'
import { EyeOutlined, PlayCircleOutlined, CompareOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { getModelLogs, getLogDetail, replayLog, batchReplay, multiModelCompare, deleteLog, getLogStats, getModels } from '@/api'

const { Text, Paragraph } = Typography

interface LogRecord {
  id: string
  model_id: string
  model_name?: string
  session_id?: string
  request_type: string
  prompt: string
  system_prompt?: string
  params?: Record<string, any>
  response?: string
  response_metadata?: Record<string, any>
  status: string
  error_message?: string
  latency_ms?: number
  is_replay: boolean
  replay_from_log_id?: string
  replay_model_id?: string
  created_at: string
}

interface LogStats {
  total_logs: number
  logs_by_model: Record<string, number>
  logs_by_type: Record<string, number>
  logs_by_status: Record<string, number>
  avg_latency_ms?: number
  replay_count: number
}

interface ReplayResult {
  log_id: string
  original_response?: string
  original_model_id: string
  original_model_name?: string
  replay_model_id: string
  replay_model_name?: string
  replay_response?: string
  replay_latency_ms?: number
  replay_status: string
  replay_error?: string
  comparison?: Record<string, any>
}

interface ModelOption {
  id: string
  name: string
  model_type: string
}

const ModelLogs: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [logs, setLogs] = useState<LogRecord[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<LogStats | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null)

  const [detailDrawerVisible, setDetailDrawerVisible] = useState(false)
  const [selectedLog, setSelectedLog] = useState<LogRecord | null>(null)

  const [replayModalVisible, setReplayModalVisible] = useState(false)
  const [replayLogId, setReplayLogId] = useState<string | null>(null)
  const [replayLoading, setReplayLoading] = useState(false)
  const [replayForm] = Form.useForm()

  const [batchReplayModalVisible, setBatchReplayModalVisible] = useState(false)
  const [batchReplayLoading, setBatchReplayLoading] = useState(false)
  const [batchReplayForm] = Form.useForm()
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])

  const [compareModalVisible, setCompareModalVisible] = useState(false)
  const [compareLoading, setCompareLoading] = useState(false)
  const [compareLogId, setCompareLogId] = useState<string | null>(null)
  const [compareForm] = Form.useForm()
  const [compareResult, setCompareResult] = useState<any>(null)

  const [page, setPage] = useState(0)
  const pageSize = 20

  const fetchModels = async () => {
    try {
      const data = await getModels('llm')
      setModels(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchStats = async () => {
    try {
      const data = await getLogStats(selectedModelId)
      setStats(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const data = await getModelLogs({
        model_id: selectedModelId,
        request_type: selectedType,
        status: selectedStatus,
        skip: page * pageSize,
        limit: pageSize,
      })
      setLogs(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchModels()
  }, [])

  useEffect(() => {
    fetchLogs()
    fetchStats()
  }, [selectedModelId, selectedType, selectedStatus, page])

  const showDetail = async (log: LogRecord) => {
    try {
      const detail = await getLogDetail(log.id)
      setSelectedLog(detail)
      setDetailDrawerVisible(true)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const showReplayModal = (logId: string) => {
    setReplayLogId(logId)
    replayForm.resetFields()
    setReplayModalVisible(true)
  }

  const handleReplay = async () => {
    try {
      const values = await replayForm.validateFields()
      setReplayLoading(true)
      const result = await replayLog(replayLogId!, values.target_model_id)
      message.success('回放成功')
      setReplayModalVisible(false)
      showDetail(result as LogRecord)
      fetchLogs()
      fetchStats()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setReplayLoading(false)
    }
  }

  const showBatchReplayModal = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择日志')
      return
    }
    batchReplayForm.resetFields()
    setBatchReplayModalVisible(true)
  }

  const handleBatchReplay = async () => {
    try {
      const values = await batchReplayForm.validateFields()
      setBatchReplayLoading(true)
      const result = await batchReplay({
        log_ids: selectedRowKeys,
        target_model_ids: values.target_model_ids,
      })
      message.success(`批量回放完成，成功 ${result.filter(r => r.replay_status === 'success').length} 条`)
      setBatchReplayModalVisible(false)
      setSelectedRowKeys([])
      fetchLogs()
      fetchStats()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setBatchReplayLoading(false)
    }
  }

  const showCompareModal = (logId: string) => {
    setCompareLogId(logId)
    compareForm.resetFields()
    setCompareResult(null)
    setCompareModalVisible(true)
  }

  const handleCompare = async () => {
    try {
      const values = await compareForm.validateFields()
      setCompareLoading(true)
      const result = await multiModelCompare({
        log_id: compareLogId!,
        target_model_ids: values.target_model_ids,
      })
      setCompareResult(result)
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setCompareLoading(false)
    }
  }

  const handleDelete = async (logId: string) => {
    try {
      await deleteLog(logId)
      message.success('删除成功')
      fetchLogs()
      fetchStats()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    {
      title: '模型',
      dataIndex: 'model_name',
      key: 'model_name',
      render: (v: string) => v || '-',
    },
    {
      title: '类型',
      dataIndex: 'request_type',
      key: 'request_type',
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '提示词',
      dataIndex: 'prompt',
      key: 'prompt',
      ellipsis: true,
      width: 300,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => {
        if (v === 'success') return <Tag color="success">成功</Tag>
        if (v === 'failed') return <Tag color="error">失败</Tag>
        return <Tag color="processing">{v}</Tag>
      },
    },
    {
      title: '耗时',
      dataIndex: 'latency_ms',
      key: 'latency_ms',
      render: (v: number) => v ? `${v}ms` : '-',
    },
    {
      title: '回放',
      dataIndex: 'is_replay',
      key: 'is_replay',
      render: (v: boolean) => v ? <Tag color="blue">回放</Tag> : null,
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: LogRecord) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => showDetail(record)}>
            查看
          </Button>
          <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => showReplayModal(record.id)}>
            回放
          </Button>
          <Button type="link" size="small" icon={<CompareOutlined />} onClick={() => showCompareModal(record.id)}>
            对比
          </Button>
          <Popconfirm title="确定删除此日志?" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="模型请求日志"
      extra={
        <Space>
          <Button onClick={() => { fetchLogs(); fetchStats(); }} icon={<ReloadOutlined />}>
            刷新
          </Button>
          <Button onClick={showBatchReplayModal} disabled={selectedRowKeys.length === 0}>
            批量回放 ({selectedRowKeys.length})
          </Button>
        </Space>
      }
    >
      {stats && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space split={<Divider type="vertical" />}>
            <span>总日志: <Text strong>{stats.total_logs}</Text></span>
            <span>成功率: <Text strong>{((stats.logs_by_status['success'] || 0) / stats.total_logs * 100 || 0).toFixed(1)}%</Text></span>
            <span>平均耗时: <Text strong>{stats.avg_latency_ms?.toFixed(0) || '-'}ms</Text></span>
            <span>回放数: <Text strong>{stats.replay_count}</Text></span>
          </Space>
        </Card>
      )}

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="选择模型"
          allowClear
          style={{ width: 200 }}
          value={selectedModelId}
          onChange={setSelectedModelId}
          options={models.map(m => ({ value: m.id, label: m.name }))}
        />
        <Select
          placeholder="请求类型"
          allowClear
          style={{ width: 120 }}
          value={selectedType}
          onChange={setSelectedType}
          options={[
            { value: 'chat', label: 'Chat' },
            { value: 'embedding', label: 'Embedding' },
            { value: 'rerank', label: 'Rerank' },
          ]}
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 120 }}
          value={selectedStatus}
          onChange={setSelectedStatus}
          options={[
            { value: 'success', label: '成功' },
            { value: 'failed', label: '失败' },
            { value: 'pending', label: '进行中' },
          ]}
        />
      </Space>

      <Table
        dataSource={logs}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page + 1,
          pageSize,
          total,
          onChange: (p) => setPage(p - 1),
        }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
        }}
      />

      {/* 详情抽屉 */}
      <Drawer
        title="日志详情"
        width={600}
        open={detailDrawerVisible}
        onClose={() => setDetailDrawerVisible(false)}
      >
        {selectedLog && (
          <>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="模型">{selectedLog.model_name}</Descriptions.Item>
              <Descriptions.Item label="类型">{selectedLog.request_type}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {selectedLog.status === 'success' ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="耗时">{selectedLog.latency_ms}ms</Descriptions.Item>
              <Descriptions.Item label="回放">{selectedLog.is_replay ? '是' : '否'}</Descriptions.Item>
              <Descriptions.Item label="时间">{new Date(selectedLog.created_at).toLocaleString()}</Descriptions.Item>
            </Descriptions>

            <Divider>请求内容</Divider>
            {selectedLog.system_prompt && (
              <>
                <Text strong>系统提示:</Text>
                <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8 }}>
                  {selectedLog.system_prompt}
                </Paragraph>
              </>
            )}
            <Text strong>用户输入:</Text>
            <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8 }}>
              {selectedLog.prompt}
            </Paragraph>

            <Divider>响应内容</Divider>
            {selectedLog.status === 'failed' ? (
              <Alert type="error" message={selectedLog.error_message} />
            ) : (
              <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8 }}>
                {selectedLog.response || '(空)'}
              </Paragraph>
            )}

            {selectedLog.response_metadata && (
              <Divider>响应元数据</Divider>
              <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8 }}>
                {JSON.stringify(selectedLog.response_metadata, null, 2)}
              </Paragraph>
            )}

            <Divider />
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => { setDetailDrawerVisible(false); showReplayModal(selectedLog.id); }}>
              回放测试
            </Button>
            <Button icon={<CompareOutlined />} style={{ marginLeft: 8 }} onClick={() => { setDetailDrawerVisible(false); showCompareModal(selectedLog.id); }}>
              多模型对比
            </Button>
          </>
        )}
      </Drawer>

      {/* 回放弹窗 */}
      <Modal
        title="回放测试"
        open={replayModalVisible}
        onCancel={() => setReplayModalVisible(false)}
        onOk={handleReplay}
        confirmLoading={replayLoading}
      >
        <Form form={replayForm} labelCol={{ span: 6 }}>
          <Form.Item name="target_model_id" label="目标模型" rules={[{ required: true }]}>
            <Select options={models.map(m => ({ value: m.id, label: m.name }))} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 批量回放弹窗 */}
      <Modal
        title="批量回放测试"
        open={batchReplayModalVisible}
        onCancel={() => setBatchReplayModalVisible(false)}
        onOk={handleBatchReplay}
        confirmLoading={batchReplayLoading}
      >
        <Alert message={`已选择 ${selectedRowKeys.length} 条日志`} style={{ marginBottom: 16 }} />
        <Form form={batchReplayForm} labelCol={{ span: 6 }}>
          <Form.Item name="target_model_ids" label="目标模型" rules={[{ required: true }]}>
            <Select mode="multiple" options={models.map(m => ({ value: m.id, label: m.name }))} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 多模型对比弹窗 */}
      <Modal
        title="多模型对比"
        open={compareModalVisible}
        onCancel={() => setCompareModalVisible(false)}
        footer={null}
        width={800}
      >
        <Form form={compareForm} labelCol={{ span: 6 }}>
          <Form.Item name="target_model_ids" label="对比模型" rules={[{ required: true }]}>
            <Select mode="multiple" options={models.map(m => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" onClick={handleCompare} loading={compareLoading}>
              开始对比
            </Button>
          </Form.Item>
        </Form>

        {compareResult && (
          <>
            <Divider>对比结果</Divider>
            <Text strong>原始提示词:</Text>
            <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8, marginBottom: 16 }}>
              {compareResult.original_prompt}
            </Paragraph>

            <Text strong>原始响应 ({compareResult.original_model_name}):</Text>
            <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#e6f7ff', padding: 8, marginBottom: 16 }}>
              {compareResult.original_response || '(空)'}
            </Paragraph>

            {compareResult.results.map((r: ReplayResult, idx: number) => (
              <Card key={idx} size="small" title={r.replay_model_name} style={{ marginBottom: 8 }}>
                {r.replay_status === 'success' ? (
                  <>
                    <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f6ffed', padding: 8 }}>
                      {r.replay_response}
                    </Paragraph>
                    <Descriptions size="small" column={2}>
                      <Descriptions.Item label="耗时">{r.replay_latency_ms}ms</Descriptions.Item>
                      <Descriptions.Item label="长度差">{r.comparison?.length_diff || 0} 字符</Descriptions.Item>
                    </Descriptions>
                  </>
                ) : (
                  <Alert type="error" message={r.replay_error} />
                )}
              </Card>
            ))}
          </>
        )}
      </Modal>
    </Card>
  )
}

export default ModelLogs