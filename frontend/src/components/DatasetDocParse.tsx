import React, { useEffect, useState } from 'react'
import { Table, Button, Tag, Space, Popconfirm, Modal, Form, Input, Select, Upload, Empty, Progress, message } from 'antd'
import { UploadOutlined, DeleteOutlined, EyeOutlined, ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import { formatShortTime } from '@/utils/format'
import {
  getParseSourceFiles, uploadParseSourceFile, deleteParseSourceFile,
  createDocParseBatch, getDocParseBatches, getDocParseResults, getDocParseResult,
  evaluateDocParseBatch, deleteDocParseBatch, getModels,
} from '@/api'
import type { DocParseSourceFile, DocParseBatchInfo, DocParseResultInfo } from '@/api'
import { usePollingWhenRunning } from '@/hooks/usePollingWhenRunning'

interface DatasetDocParseProps {
  datasetId: string
  /** 解析完成（批次有新完成的产物）时回调，用于刷新文档列表 */
  onDocsChanged?: () => void
}

const statusRender = (status: string) => {
  const map: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '待解析' },
    running: { color: 'processing', text: '解析中' },
    success: { color: 'success', text: '成功' },
    completed: { color: 'success', text: '已完成' },
    failed: { color: 'error', text: '失败' },
  }
  const s = map[status] || { color: 'default', text: status }
  return <Tag color={s.color}>{s.text}</Tag>
}

// 注意用 == null 而不是 === undefined：后端把 SQL NULL 序列化成 JSON null，
// 而 null === undefined 为 false，漏过去的 null 会在调用处 .toFixed() 直接崩掉整页
const scoreColor = (score?: number | null) =>
  score == null ? 'default' : score >= 80 ? 'success' : score >= 60 ? 'warning' : 'error'

/**
 * 数据集内文档解析（minerU）
 * 上传的源文件存入数据集前缀目录，解析批次与产物文档归属该数据集
 */
const DatasetDocParse: React.FC<DatasetDocParseProps> = ({ datasetId, onDocsChanged }) => {
  const [sourceFiles, setSourceFiles] = useState<DocParseSourceFile[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [selectedFileKeys, setSelectedFileKeys] = useState<React.Key[]>([])
  const [batches, setBatches] = useState<DocParseBatchInfo[]>([])
  const [batchesLoading, setBatchesLoading] = useState(false)
  const [parseModalVisible, setParseModalVisible] = useState(false)
  const [parserModels, setParserModels] = useState<{ id: string; name: string; provider?: string }[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [parseForm] = Form.useForm()
  // 结果查看
  const [viewingBatchId, setViewingBatchId] = useState<string | null>(null)
  const [viewingResults, setViewingResults] = useState<DocParseResultInfo[]>([])
  const [viewingResultsLoading, setViewingResultsLoading] = useState(false)
  const [viewingMd, setViewingMd] = useState<{ fileName: string; content: string; evaluation?: DocParseResultInfo['evaluation'] } | null>(null)
  const [viewingMdLoading, setViewingMdLoading] = useState(false)
  const [evaluatingBatchId, setEvaluatingBatchId] = useState<string | null>(null)

  const fetchSourceFiles = async () => {
    setFilesLoading(true)
    try {
      const data = await getParseSourceFiles(datasetId)
      setSourceFiles(data.items || [])
    } catch (e) {
      // 错误已处理
    } finally {
      setFilesLoading(false)
    }
  }

  const fetchBatches = async () => {
    setBatchesLoading(true)
    try {
      const data = await getDocParseBatches(datasetId)
      setBatches(data || [])
    } catch (e) {
      // 错误已处理
    } finally {
      setBatchesLoading(false)
    }
  }

  useEffect(() => {
    if (!datasetId) return
    fetchSourceFiles()
    fetchBatches()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId])

  // 轮询运行中的批次
  usePollingWhenRunning(
    batches.some(b => b.status === 'running' || b.status === 'pending'),
    async () => {
      const data = await getDocParseBatches(datasetId)
      setBatches(data || [])
      if (viewingBatchId) {
        const batch = (data || []).find(b => b.id === viewingBatchId)
        if (batch && batch.status !== 'running' && batch.status !== 'pending') {
          const results = await getDocParseResults(viewingBatchId)
          setViewingResults(results || [])
        }
      }
    },
    5000,
    [viewingBatchId, datasetId],
  )

  const handleFileUpload = async (file: File) => {
    setUploading(true)
    try {
      await uploadParseSourceFile(file, datasetId)
      message.success('源文件已保存')
      fetchSourceFiles()
    } catch (e) {
      // 错误已处理
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleDeleteFile = async (objectName: string) => {
    try {
      await deleteParseSourceFile(objectName)
      message.success('源文件已删除')
      fetchSourceFiles()
    } catch (e) {
      // 错误已处理
    }
  }

  const showParseModal = async () => {
    if (selectedFileKeys.length === 0) {
      message.warning('请先勾选要解析的源文件')
      return
    }
    parseForm.resetFields()
    setParseModalVisible(true)
    try {
      const models = await getModels('doc_parser')
      setParserModels(models.map(m => ({ id: m.id, name: m.name, provider: m.provider })))
    } catch (e) {
      // 错误已处理
    }
  }

  const handleCreateBatch = async () => {
    try {
      const values = await parseForm.validateFields()
      setSubmitting(true)
      const batch = await createDocParseBatch({
        name: values.name || undefined,
        parser_model_id: values.parser_model_id,
        object_names: selectedFileKeys as string[],
        config: { language: values.language || 'ch' },
        dataset_id: datasetId,
      })
      message.success(`解析任务已提交：${batch.name}`)
      setParseModalVisible(false)
      setSelectedFileKeys([])
      fetchBatches()
    } catch (e) {
      // 错误已处理
    } finally {
      setSubmitting(false)
    }
  }

  const handleViewBatchResults = async (batchId: string) => {
    setViewingBatchId(batchId)
    setViewingResultsLoading(true)
    try {
      const results = await getDocParseResults(batchId)
      setViewingResults(results || [])
    } catch (e) {
      // 错误已处理
    } finally {
      setViewingResultsLoading(false)
    }
  }

  const handleViewMd = async (result: DocParseResultInfo) => {
    setViewingMdLoading(true)
    try {
      const detail = await getDocParseResult(result.id)
      setViewingMd({
        fileName: detail.file_name,
        content: detail.md_content || '（无内容）',
        evaluation: detail.evaluation,
      })
    } catch (e) {
      setViewingMd({ fileName: result.file_name, content: '加载失败' })
    } finally {
      setViewingMdLoading(false)
    }
  }

  const handleEvaluateBatch = async (batch: DocParseBatchInfo) => {
    setEvaluatingBatchId(batch.id)
    try {
      const res = await evaluateDocParseBatch(batch.id)
      message.success(res.message || '评估完成')
      fetchBatches()
      if (viewingBatchId === batch.id) {
        const results = await getDocParseResults(batch.id)
        setViewingResults(results || [])
      }
    } catch (e) {
      // 错误已处理
    } finally {
      setEvaluatingBatchId(null)
    }
  }

  const handleDeleteBatch = async (batch: DocParseBatchInfo) => {
    try {
      await deleteDocParseBatch(batch.id)
      message.success('解析批次已删除')
      if (viewingBatchId === batch.id) setViewingBatchId(null)
      fetchBatches()
    } catch (e) {
      // 错误已处理
    }
  }

  // 批次完成后产物文档入库，回调刷新文档列表
  useEffect(() => {
    const completed = batches.filter(b => b.status === 'completed' && b.success_files > 0)
    if (completed.length > 0) onDocsChanged?.()
    // 仅依赖批次状态变化，避免循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batches.map(b => `${b.id}:${b.status}`).join(',')])

  const fileColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (s: number) => (s ? `${(s / 1024 / 1024).toFixed(2)} MB` : '-'),
    },
    {
      title: '类型',
      key: 'ext',
      width: 80,
      render: (_: unknown, record: DocParseSourceFile) => {
        const ext = record.file_name.includes('.') ? record.file_name.split('.').pop() : ''
        return <Tag color="blue">{(ext || '?').toUpperCase()}</Tag>
      },
    },
    {
      title: '可解析',
      dataIndex: 'parseable',
      key: 'parseable',
      width: 90,
      render: (ok: boolean) => (ok ? <Tag color="success">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, record: DocParseSourceFile) => (
        <Popconfirm title="确定删除该源文件?" onConfirm={() => handleDeleteFile(record.object_name)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
        </Popconfirm>
      ),
    },
  ]

  const batchColumns = [
    { title: '任务名', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '解析服务', dataIndex: 'parser_model_name', key: 'parser_model_name', width: 130 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: statusRender },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 110,
      render: (p: number, record: DocParseBatchInfo) => (
        record.status === 'running'
          ? <Progress percent={p} size="small" status="active" />
          : <Progress percent={p} size="small" />
      ),
    },
    {
      title: '成功/失败',
      key: 'files',
      width: 90,
      render: (_: unknown, record: DocParseBatchInfo) => (
        <span>
          <span style={{ color: '#52c41a' }}>{record.success_files}</span> /{' '}
          <span style={{ color: record.failed_files ? '#f5222d' : undefined }}>{record.failed_files}</span>
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (d: string) => formatShortTime(d),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: DocParseBatchInfo) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewBatchResults(record.id)}>
            结果
          </Button>
          <Button
            type="link"
            size="small"
            disabled={record.status !== 'completed' || record.success_files === 0}
            loading={evaluatingBatchId === record.id}
            onClick={() => handleEvaluateBatch(record)}
          >
            评估
          </Button>
          <Popconfirm title="确定删除该解析批次?" onConfirm={() => handleDeleteBatch(record)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled={record.status === 'running'} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const resultColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: statusRender },
    {
      title: '得分',
      key: 'score',
      width: 80,
      render: (_: unknown, record: DocParseResultInfo) => {
        const s = record.evaluation?.score
        return s == null ? '-' : <Tag color={scoreColor(s)}>{s}</Tag>
      },
    },
    {
      title: '耗时',
      dataIndex: 'duration',
      key: 'duration',
      width: 80,
      // duration 为 SQL NULL 时后端返回 null（不是 undefined），
      // 用 === undefined 判断会漏过 null，然后 d.toFixed(1) 抛错、
      // React 整棵树被卸载，点一次「结果」整页白屏
      render: (d?: number | null) => (d == null ? '-' : `${d.toFixed(1)}s`),
    },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      ellipsis: true,
      render: (e?: string) => e || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: DocParseResultInfo) => (
        <Space size="small">
          {record.status === 'success' && (
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewMd(record)}>
              查看
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Upload beforeUpload={handleFileUpload} showUploadList={false} disabled={uploading}>
          <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
            上传源文件
          </Button>
        </Upload>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={showParseModal}
          disabled={selectedFileKeys.length === 0}
        >
          发起解析（已选 {selectedFileKeys.length} 个）
        </Button>
        <Button icon={<ReloadOutlined />} onClick={() => { fetchSourceFiles(); fetchBatches() }}>
          刷新
        </Button>
      </Space>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 480px', minWidth: 0 }}>
          <div style={{ fontWeight: 500, marginBottom: 8 }}>源文件</div>
          <Table
            dataSource={sourceFiles}
            columns={fileColumns}
            rowKey="object_name"
            loading={filesLoading}
            size="small"
            pagination={{ pageSize: 8, showTotal: t => `共 ${t} 个文件` }}
            rowSelection={{ selectedRowKeys: selectedFileKeys, onChange: setSelectedFileKeys }}
            locale={{ emptyText: <Empty description="暂无源文件，点击上方「上传源文件」保存 PDF/图片等待解析（仅存储原文件，不做分片）" /> }}
          />
        </div>
        <div style={{ flex: '1 1 480px', minWidth: 0 }}>
          <div style={{ fontWeight: 500, marginBottom: 8 }}>解析任务</div>
          <Table
            dataSource={batches}
            columns={batchColumns}
            rowKey="id"
            loading={batchesLoading}
            size="small"
            pagination={{ pageSize: 8, showTotal: t => `共 ${t} 个任务` }}
            locale={{ emptyText: <Empty description="暂无解析任务，勾选源文件后点击「发起解析」" /> }}
          />
        </div>
      </div>

      {/* 发起解析弹窗 */}
      <Modal
        title={`发起解析（已选 ${selectedFileKeys.length} 个源文件）`}
        open={parseModalVisible}
        onCancel={() => setParseModalVisible(false)}
        onOk={handleCreateBatch}
        confirmLoading={submitting}
        okText="提交解析"
        width={560}
      >
        <Form form={parseForm} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="任务名称">
            <Input placeholder="可选，默认按时间生成" />
          </Form.Item>
          <Form.Item
            name="parser_model_id"
            label="解析服务"
            rules={[{ required: true, message: '请选择解析服务' }]}
            extra={parserModels.length === 0 ? '尚未配置解析服务，请到「模型配置 → 文档解析」新增（MinerU 自部署或官方API）' : undefined}
          >
            <Select
              placeholder="选择 doc_parser 模型"
              options={parserModels.map(m => ({
                value: m.id,
                label: `${m.name}${m.provider === 'mineru_api' ? '（官方API）' : m.provider === 'mineru' ? '（自部署）' : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="language" label="文档语言" initialValue="ch">
            <Select options={[{ value: 'ch', label: '中文' }, { value: 'en', label: '英文' }]} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 批次结果弹窗 */}
      <Modal
        title={`解析结果${viewingBatchId ? ` - ${batches.find(b => b.id === viewingBatchId)?.name || ''}` : ''}`}
        open={!!viewingBatchId}
        onCancel={() => { setViewingBatchId(null); setViewingResults([]) }}
        footer={null}
        width={820}
      >
        {viewingBatchId && batches.find(b => b.id === viewingBatchId)?.error && (
          <div style={{ marginBottom: 12 }}>
            <Tag color="error">{batches.find(b => b.id === viewingBatchId)!.error}</Tag>
          </div>
        )}
        <Table
          dataSource={viewingResults}
          columns={resultColumns}
          rowKey="id"
          loading={viewingResultsLoading}
          size="small"
          pagination={false}
          expandable={{
            rowExpandable: record => !!(record.evaluation?.suggestions?.length || record.error),
            expandedRowRender: record => (
              <div style={{ fontSize: 12 }}>
                {record.error && <div style={{ color: '#f5222d', marginBottom: 4 }}>错误：{record.error}</div>}
                {record.evaluation?.suggestions?.map((s, i) => <div key={i}>💡 {s}</div>)}
              </div>
            ),
          }}
        />
      </Modal>

      {/* Markdown 查看弹窗 */}
      <Modal
        title={`解析结果${viewingMd ? ` - ${viewingMd.fileName}` : ''}`}
        open={!!viewingMd}
        onCancel={() => setViewingMd(null)}
        footer={<Button onClick={() => setViewingMd(null)}>关闭</Button>}
        width={860}
      >
        {viewingMd && (
          <>
            {viewingMd.evaluation && (
              <div style={{ marginBottom: 12 }}>
                <Space size="small" wrap>
                  <Tag color={scoreColor(viewingMd.evaluation.score)} style={{ fontSize: 14, padding: '2px 10px' }}>
                    得分 {viewingMd.evaluation.score ?? '-'}
                  </Tag>
                  {/* metrics / suggestions 都可能整体为 null，
                      逐项再判一次空值，避免 (v * 100) 和 .map 在 null 上炸掉整页 */}
                  {Object.entries(viewingMd.evaluation.metrics || {}).map(([k, v]) => (
                    <Tag key={k}>{k}: {v == null ? '-' : `${(v * 100).toFixed(0)}`}</Tag>
                  ))}
                </Space>
                <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                  {(viewingMd.evaluation.suggestions || []).map((s, i) => <div key={i}>💡 {s}</div>)}
                </div>
              </div>
            )}
            <div
              style={{
                maxHeight: 520, overflowY: 'auto', padding: 12,
                background: '#f5f5f5', borderRadius: 6, whiteSpace: 'pre-wrap',
                fontSize: 13, lineHeight: 1.7,
              }}
            >
              {viewingMdLoading ? '加载中...' : viewingMd.content}
            </div>
          </>
        )}
      </Modal>
    </div>
  )
}

export default DatasetDocParse
