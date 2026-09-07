import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tabs, Tag, Modal, Form, Select, Space, Drawer, Descriptions, Input, message, Popconfirm, Alert, Divider, Typography, Switch, Tooltip } from 'antd'
import { EyeOutlined, PlayCircleOutlined, SwapOutlined, DeleteOutlined, PlusOutlined, CopyOutlined, EditOutlined, ApiOutlined, CodeOutlined } from '@ant-design/icons'
import {
  getModelLogs, replayLog, batchReplay, multiModelCompare, deleteLog, getLogStats, getModels,
  getModelMappings, createMapping, updateMapping, resetMappingKey, deleteMapping,
} from '@/api'
import type { ModelMapping } from '@/api'

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
  source?: string
  mapping_id?: string
  mapping_name?: string
  created_at: string
}

interface LogStats {
  total_logs: number
  logs_by_model: Record<string, number>
  logs_by_type: Record<string, number>
  logs_by_status: Record<string, number>
  avg_latency_ms?: number
  replay_count: number
  token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  logs_with_usage?: number
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

// 复制文本小组件（http 环境降级 execCommand）
const CopyableText: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => (
  <Space size={4} style={style}>
    <Text code copyable={false} style={{ fontSize: 12 }}>{text}</Text>
    <Button
      type="text"
      size="small"
      icon={<CopyOutlined />}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          message.success('已复制')
        } catch {
          const input = document.createElement('textarea')
          input.value = text
          document.body.appendChild(input)
          input.select()
          document.execCommand('copy')
          document.body.removeChild(input)
          message.success('已复制')
        }
      }}
    />
  </Space>
)

// ---------------------------------------------------------------------------
// 调用日志 Tab（原有功能）
// ---------------------------------------------------------------------------

const LogsTab: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [logs, setLogs] = useState<LogRecord[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<LogStats | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null)
  const [selectedSource, setSelectedSource] = useState<string | null>(null)

  const [detailDrawerVisible, setDetailDrawerVisible] = useState(false)
  const [selectedLog, setSelectedLog] = useState<LogRecord | null>(null)

  const showDetail = async (log: LogRecord) => {
    setSelectedLog(log)
    setDetailDrawerVisible(true)
  }

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
      const data = await getLogStats(selectedModelId ?? undefined)
      setStats(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const data = await getModelLogs({
        model_id: selectedModelId ?? undefined,
        request_type: selectedType ?? undefined,
        status: selectedStatus ?? undefined,
        source: selectedSource ?? undefined,
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
  }, [selectedModelId, selectedType, selectedStatus, selectedSource, page])

  const showReplayModal = (logId: string) => {
    setReplayLogId(logId)
    replayForm.resetFields()
    setReplayModalVisible(true)
  }

  const handleReplay = async () => {
    try {
      const values = await replayForm.validateFields()
      setReplayLoading(true)
      await replayLog(replayLogId!, values.target_model_id)
      message.success('回放成功')
      setReplayModalVisible(false)
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
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 130,
      render: (v: string, record: LogRecord) =>
        v === 'mapping' ? <Tag color="purple">映射: {record.mapping_name || record.mapping_id}</Tag> : <Tag>直接调用</Tag>,
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
          <Button type="link" size="small" icon={<SwapOutlined />} onClick={() => showCompareModal(record.id)}>
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
    <>
      {stats && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space split={<Divider type="vertical" />} wrap>
            <span>总日志: <Text strong>{stats.total_logs}</Text></span>
            <span>成功率: <Text strong>{((stats.logs_by_status['success'] || 0) / stats.total_logs * 100 || 0).toFixed(1)}%</Text></span>
            <span>平均耗时: <Text strong>{stats.avg_latency_ms?.toFixed(0) || '-'}ms</Text></span>
            <span>回放数: <Text strong>{stats.replay_count}</Text></span>
            <Tooltip title={`含 token 用量的日志 ${stats.logs_with_usage ?? 0} 条；其余日志因上游未返回 usage 或链路未记录而缺失`}>
              <span>
                Token 用量: <Text strong>{(stats.token_usage?.total_tokens ?? 0).toLocaleString()}</Text>
                <Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>
                  (输入 {(stats.token_usage?.prompt_tokens ?? 0).toLocaleString()} / 输出 {(stats.token_usage?.completion_tokens ?? 0).toLocaleString()})
                </Text>
              </span>
            </Tooltip>
          </Space>
        </Card>
      )}

      <Space style={{ marginBottom: 16 }} wrap>
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
        <Select
          placeholder="来源"
          allowClear
          style={{ width: 130 }}
          value={selectedSource}
          onChange={setSelectedSource}
          options={[
            { value: 'direct', label: '直接调用' },
            { value: 'mapping', label: '映射调用' },
          ]}
        />
        <Button onClick={() => showBatchReplayModal()} disabled={selectedRowKeys.length === 0}>
          批量回放 ({selectedRowKeys.length})
        </Button>
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
              {(() => {
                const usage = selectedLog.response_metadata?.usage_tokens || selectedLog.response_metadata?.usage
                return usage ? (
                  <Descriptions.Item label="Token 用量" span={2}>
                    <Space split={<Divider type="vertical" />}>
                      <span>输入: <Text strong>{(usage.prompt_tokens ?? usage.input_tokens ?? 0).toLocaleString()}</Text></span>
                      <span>输出: <Text strong>{(usage.completion_tokens ?? usage.output_tokens ?? 0).toLocaleString()}</Text></span>
                      <span>总计: <Text strong>{(usage.total_tokens ?? 0).toLocaleString()}</Text></span>
                    </Space>
                  </Descriptions.Item>
                ) : null
              })()}
              {selectedLog.source === 'mapping' && (
                <Descriptions.Item label="映射服务" span={2}>
                  {selectedLog.mapping_name || selectedLog.mapping_id}
                  {selectedLog.params?.inbound_protocol && (
                    <Tag style={{ marginLeft: 8 }}>入站: {String(selectedLog.params.inbound_protocol)}</Tag>
                  )}
                  {selectedLog.params?.outbound_protocol && (
                    <Tag style={{ marginLeft: 4 }}>出站: {String(selectedLog.params.outbound_protocol)}</Tag>
                  )}
                </Descriptions.Item>
              )}
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
              <>
                <Divider>响应元数据</Divider>
                <Paragraph style={{ whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8 }}>
                  {JSON.stringify(selectedLog.response_metadata, null, 2)}
                </Paragraph>
              </>
            )}

            <Divider />
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => { setDetailDrawerVisible(false); showReplayModal(selectedLog.id); }}>
              回放测试
            </Button>
            <Button icon={<SwapOutlined />} style={{ marginLeft: 8 }} onClick={() => { setDetailDrawerVisible(false); showCompareModal(selectedLog.id); }}>
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
    </>
  )
}

// ---------------------------------------------------------------------------
// 映射服务 Tab
// ---------------------------------------------------------------------------

const MappingsTab: React.FC<{ onNotify: () => void }> = ({ onNotify }) => {
  const [loading, setLoading] = useState(false)
  const [mappings, setMappings] = useState<ModelMapping[]>([])
  const [models, setModels] = useState<ModelOption[]>([])

  const [modalVisible, setModalVisible] = useState(false)
  const [editingMapping, setEditingMapping] = useState<ModelMapping | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const [keyModalVisible, setKeyModalVisible] = useState(false)
  const [plainKey, setPlainKey] = useState<string>('')

  const [curlModalVisible, setCurlModalVisible] = useState(false)
  const [curlSample, setCurlSample] = useState('')

  const origin = window.location.origin

  // 生成 curl 调用示例（OpenAI / Anthropic 两种协议，含流式）
  const showCurlExamples = (mapping: ModelMapping) => {
    const baseUrl = `${origin}/api/v1/model-mappings/${mapping.id}`
    const key = mapping.auth_required ? 'Authorization: Bearer $MAPPING_KEY' : null
    const authLine = key ? `\n  -H "${key}" \\` : ''
    const authLineA = mapping.auth_required
      ? `\n  -H "x-api-key: $MAPPING_KEY" \\\n  -H "anthropic-version: 2023-06-01" \\`
      : '\n  -H "anthropic-version: 2023-06-01" \\'
    const keyExport = mapping.auth_required
      ? `# 映射服务密钥（在「密钥」列查看，重置后旧密钥失效）\nexport MAPPING_KEY="你的密钥"\n\n`
      : ''

    const text = `${keyExport}# 1. OpenAI 协议调用（兼容 /v1/chat/completions）\ncurl -X POST "${baseUrl}/v1/chat/completions" \\${authLine}
  -H "Content-Type: application/json" \\
  -d '{
    "model": "任意值（以映射的目标模型为准）",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 1024
  }'

# 2. OpenAI 协议流式调用（SSE）
curl -N -X POST "${baseUrl}/v1/chat/completions" \\${authLine}
  -H "Content-Type: application/json" \\
  -d '{"messages": [{"role": "user", "content": "你好"}], "stream": true, "max_tokens": 1024}'

# 3. Anthropic 协议调用（兼容 /v1/messages）
curl -X POST "${baseUrl}/v1/messages" \\${authLineA}
  -H "Content-Type: application/json" \\
  -d '{
    "model": "任意值（以映射的目标模型为准）",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好"}]
  }'`
    setCurlSample(text)
    setCurlModalVisible(true)
  }


  const fetchMappings = async () => {
    setLoading(true)
    try {
      const data = await getModelMappings()
      setMappings(data)
    } finally {
      setLoading(false)
    }
  }

  const fetchModels = async () => {
    try {
      const data = await getModels('llm')
      setModels(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  useEffect(() => {
    fetchMappings()
    fetchModels()
  }, [])

  const showCreateDialog = () => {
    setEditingMapping(null)
    form.resetFields()
    form.setFieldsValue({ auth_required: true, log_enabled: false })
    setModalVisible(true)
  }

  const showEditDialog = (mapping: ModelMapping) => {
    setEditingMapping(mapping)
    form.setFieldsValue({
      name: mapping.name,
      target_model_id: mapping.target_model_id,
      auth_required: mapping.auth_required,
      log_enabled: mapping.log_enabled,
      description: mapping.description,
    })
    setModalVisible(true)
  }

  const saveMapping = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingMapping) {
        await updateMapping(editingMapping.id, values)
        message.success('更新成功')
      } else {
        const created = await createMapping(values)
        message.success('创建成功')
        if (created.api_key) {
          setPlainKey(created.api_key)
          setKeyModalVisible(true)
        }
      }
      setModalVisible(false)
      fetchMappings()
      onNotify()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setSaving(false)
    }
  }

  const handleResetKey = async (mapping: ModelMapping) => {
    try {
      const result = await resetMappingKey(mapping.id)
      setPlainKey(result.api_key)
      setKeyModalVisible(true)
      fetchMappings()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDelete = async (mappingId: string) => {
    try {
      await deleteMapping(mappingId)
      message.success('删除成功')
      fetchMappings()
      onNotify()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleToggle = async (mapping: ModelMapping, field: 'auth_required' | 'log_enabled' | 'status', value: any) => {
    try {
      await updateMapping(mapping.id, { [field]: value })
      message.success('已更新')
      fetchMappings()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (v: string, record: ModelMapping) => (
        <div>
          <div>{v}</div>
          {record.description && <Text type="secondary" style={{ fontSize: 12 }}>{record.description}</Text>}
        </div>
      ),
    },
    {
      title: '目标模型',
      dataIndex: 'target_model_name',
      key: 'target_model_name',
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-',
    },
    {
      title: '调用端点',
      key: 'endpoints',
      width: 320,
      render: (_: unknown, record: ModelMapping) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <CopyableText text={`${origin}/api/v1/model-mappings/${record.id}/v1`} />
          <CopyableText text={`${origin}/api/v1/model-mappings/${record.id}`} />
        </div>
      ),
    },
    {
      title: '密钥',
      dataIndex: 'api_key_masked',
      key: 'api_key_masked',
      width: 200,
      render: (v: string, record: ModelMapping) => (
        <Space size={4}>
          {v ? <Text code style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text>}
          {v && (
            <Tooltip title="重置密钥（旧密钥立即失效）">
              <Popconfirm title="确定重置密钥?" onConfirm={() => handleResetKey(record)}>
                <Button type="link" size="small">重置</Button>
              </Popconfirm>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '鉴权',
      dataIndex: 'auth_required',
      key: 'auth_required',
      width: 80,
      render: (v: boolean, record: ModelMapping) => (
        <Switch checked={v} onChange={(val) => handleToggle(record, 'auth_required', val)} />
      ),
    },
    {
      title: '记录调用',
      dataIndex: 'log_enabled',
      key: 'log_enabled',
      width: 90,
      render: (v: boolean, record: ModelMapping) => (
        <Switch checked={v} onChange={(val) => handleToggle(record, 'log_enabled', val)} />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string, record: ModelMapping) => (
        <Switch
          checkedChildren="启用"
          unCheckedChildren="停用"
          checked={v === 'active'}
          onChange={(val) => handleToggle(record, 'status', val ? 'active' : 'disabled')}
        />
      ),
    },
    {
      title: '最近调用',
      dataIndex: 'last_called_at',
      key: 'last_called_at',
      width: 150,
      render: (v: string) => v ? new Date(v).toLocaleString() : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: ModelMapping) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => showEditDialog(record)}>
            编辑
          </Button>
          <Button type="link" size="small" icon={<CodeOutlined />} onClick={() => showCurlExamples(record)}>
            调用示例
          </Button>
          <Popconfirm title="确定删除此映射服务?" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Alert
        type="info"
        showIcon
        icon={<ApiOutlined />}
        message="映射服务将外部请求转发到目标模型，兼容 OpenAI 与 Anthropic 协议互转（含流式）。OpenAI 客户端 base_url 填第一行，Anthropic 客户端 base_url 填第二行。"
        style={{ marginBottom: 16 }}
        action={
          <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
            新增映射服务
          </Button>
        }
      />

      <Table dataSource={mappings} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title={editingMapping ? '编辑映射服务' : '新增映射服务'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveMapping}
        confirmLoading={saving}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="映射服务名称" />
          </Form.Item>
          <Form.Item name="target_model_id" label="目标模型" rules={[{ required: true, message: '请选择目标模型' }]}>
            <Select
              placeholder="选择 LLM 模型"
              options={models.map(m => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
          <Form.Item
            name="auth_required"
            label="开启鉴权"
            valuePropName="checked"
            extra="开启后调用方需携带密钥（Authorization: Bearer 或 x-api-key）；关闭后任何人都可调用，仅建议内网调试使用"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="log_enabled"
            label="记录调用"
            valuePropName="checked"
            extra="开启后所有调用将写入模型请求日志，可在「调用日志」中查看"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="备注">
            <Input.TextArea rows={2} placeholder="备注说明（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 一次性密钥展示弹窗 */}
      <Modal
        title="映射服务密钥"
        open={keyModalVisible}
        onCancel={() => setKeyModalVisible(false)}
        footer={[
          <Button key="copy" icon={<CopyOutlined />} onClick={async () => {
            try {
              await navigator.clipboard.writeText(plainKey)
              message.success('已复制')
            } catch {
              message.error('复制失败，请手动复制')
            }
          }}>
            复制密钥
          </Button>,
          <Button key="ok" type="primary" onClick={() => setKeyModalVisible(false)}>
            我已保存
          </Button>,
        ]}
      >
        <Alert
          type="warning"
          message="请立即保存此密钥，关闭后将无法再次查看"
          style={{ marginBottom: 16 }}
        />
        <Paragraph code copyable={false} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {plainKey}
        </Paragraph>
      </Modal>

      {/* 调用示例弹窗 */}
      <Modal
        title="调用示例（curl）"
        open={curlModalVisible}
        width={760}
        onCancel={() => setCurlModalVisible(false)}
        footer={[
          <Button key="copy" icon={<CopyOutlined />} onClick={async () => {
            try {
              await navigator.clipboard.writeText(curlSample)
              message.success('已复制')
            } catch {
              const input = document.createElement('textarea')
              input.value = curlSample
              document.body.appendChild(input)
              input.select()
              document.execCommand('copy')
              document.body.removeChild(input)
              message.success('已复制')
            }
          }}>
            复制全部
          </Button>,
          <Button key="ok" type="primary" onClick={() => setCurlModalVisible(false)}>
            关闭
          </Button>,
        ]}
      >
        <Alert
          type="info"
          showIcon
          message="示例中的 URL 已按此映射服务生成；auth_required 开启时密钥用环境变量 MAPPING_KEY 占位，执行前先 export，避免密钥落入 shell 历史"
          style={{ marginBottom: 16 }}
        />
        <pre
          style={{
            background: '#1e1e1e', color: '#d4d4d4', padding: 16, borderRadius: 8,
            fontSize: 12, lineHeight: 1.6, overflowX: 'auto', margin: 0,
            fontFamily: 'Consolas, Monaco, monospace',
          }}
        >
          {curlSample}
        </pre>
      </Modal>
    </>
  )
}

// ---------------------------------------------------------------------------
// 页面主体（Tabs）
// ---------------------------------------------------------------------------

const ModelLogs: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'logs' | 'mappings'>('logs')
  const [logRefreshKey, setLogRefreshKey] = useState(0)

  const tabItems = [
    { key: 'logs', label: '调用日志', children: <LogsTab key={logRefreshKey} /> },
    { key: 'mappings', label: '映射服务', children: <MappingsTab onNotify={() => setLogRefreshKey(k => k + 1)} /> },
  ]

  return (
    <Card title="模型请求日志">
      <Tabs items={tabItems} activeKey={activeTab} onChange={(key) => setActiveTab(key as 'logs' | 'mappings')} />
    </Card>
  )
}

export default ModelLogs
