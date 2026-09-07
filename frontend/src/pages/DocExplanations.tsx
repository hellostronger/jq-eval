import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space, Popconfirm,
  Upload, Tabs, Segmented, InputNumber, Empty, Progress,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, UploadOutlined, EyeOutlined,
  FileTextOutlined, SearchOutlined, InboxOutlined, ThunderboltOutlined, ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getDocExplanations, createDocExplanation, updateDocExplanation, deleteDocExplanation,
  getDocuments, uploadGlobalDocument, getDocumentDetail, deleteDocument, createGlobalDocumentFromText,
  getModels, getParseSourceFiles, uploadParseSourceFile, deleteParseSourceFile,
  createDocParseBatch, getDocParseBatches, getDocParseResults, getDocParseResult,
  deleteDocParseBatch, evaluateDocParseBatch,
} from '@/api'
import type { DocExplanation, DocumentInfo } from '@/types'
import type { DocParseSourceFile, DocParseBatchInfo, DocParseResultInfo } from '@/api'

const SOURCE_LABELS: Record<string, string> = {
  manual: '手动输入',
  upload: '文件上传',
  text_input: '文本粘贴',
  generated: '系统生成',
  mineru: 'minerU解析',
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  ready: { label: '就绪', color: 'success' },
  archived: { label: '已归档', color: 'warning' },
}

const SOURCE_OPTIONS = [
  { value: 'manual', label: '手动输入' },
  { value: 'upload', label: '文件上传' },
  { value: 'text_input', label: '文本粘贴' },
  { value: 'generated', label: '系统生成' },
]

const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'ready', label: '就绪' },
  { value: 'archived', label: '已归档' },
]

const CHUNK_PRESET = { size: 500, overlap: 50 }

const DocExplanations: React.FC = () => {
  const [activeTab, setActiveTab] = useState('explanations')

  // 解释列表
  const [explanations, setExplanations] = useState<DocExplanation[]>([])
  const [expLoading, setExpLoading] = useState(false)
  const [expSearch, setExpSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()

  // 源文档列表
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [docLoading, setDocLoading] = useState(false)
  const [docSearch, setDocSearch] = useState('')

  // 新建解释弹窗
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [createMode, setCreateMode] = useState<'select' | 'upload'>('select')
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadedDoc, setUploadedDoc] = useState<DocumentInfo | null>(null)
  const [form] = Form.useForm()

  // 编辑弹窗
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingExp, setEditingExp] = useState<DocExplanation | null>(null)
  const [editForm] = Form.useForm()

  // 查看弹窗
  const [viewingExp, setViewingExp] = useState<DocExplanation | null>(null)

  // 上传文档弹窗（源文档页签）
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [chunkSize, setChunkSize] = useState(CHUNK_PRESET.size)
  const [chunkOverlap, setChunkOverlap] = useState(CHUNK_PRESET.overlap)

  // 粘贴文本弹窗
  const [textModalVisible, setTextModalVisible] = useState(false)
  const [textSaving, setTextSaving] = useState(false)
  const [textForm] = Form.useForm()

  // 文档预览弹窗
  const [previewDoc, setPreviewDoc] = useState<DocumentInfo | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // ---------- 文档解析（minerU） ----------
  const [parseSourceFiles, setParseSourceFiles] = useState<DocParseSourceFile[]>([])
  const [parseFilesLoading, setParseFilesLoading] = useState(false)
  const [parseBatches, setParseBatches] = useState<DocParseBatchInfo[]>([])
  const [parseBatchesLoading, setParseBatchesLoading] = useState(false)
  const [parseUploading, setParseUploading] = useState(false)
  const [selectedFileKeys, setSelectedFileKeys] = useState<React.Key[]>([])
  const [parseModalVisible, setParseModalVisible] = useState(false)
  const [parserModels, setParserModels] = useState<{ id: string; name: string; provider?: string }[]>([])
  const [parseSubmitting, setParseSubmitting] = useState(false)
  const [parseForm] = Form.useForm()
  // 结果查看
  const [viewingBatchId, setViewingBatchId] = useState<string | null>(null)
  const [viewingResults, setViewingResults] = useState<DocParseResultInfo[]>([])
  const [viewingResultsLoading, setViewingResultsLoading] = useState(false)
  const [viewingMd, setViewingMd] = useState<{ fileName: string; content: string; evaluation?: DocParseResultInfo['evaluation'] } | null>(null)
  const [viewingMdLoading, setViewingMdLoading] = useState(false)
  const [evaluatingBatchId, setEvaluatingBatchId] = useState<string | null>(null)

  const fetchExplanations = async () => {
    setExpLoading(true)
    try {
      const data = await getDocExplanations()
      setExplanations(data)
    } finally {
      setExpLoading(false)
    }
  }

  const fetchDocuments = async () => {
    setDocLoading(true)
    try {
      const docData = await getDocuments()
      setDocuments(docData.items || docData)
    } finally {
      setDocLoading(false)
    }
  }

  useEffect(() => {
    fetchExplanations()
    fetchDocuments()
  }, [])

  // ---------- 新建解释 ----------
  const showCreateModal = async (presetDocId?: string) => {
    form.resetFields()
    setCreateMode('select')
    setUploadedDoc(null)
    if (presetDocId) form.setFieldsValue({ doc_id: presetDocId })
    setCreateModalVisible(true)
    fetchDocuments()
  }

  const handleCreateUpload = async (file: File) => {
    setUploading(true)
    try {
      const doc = await uploadGlobalDocument(file, chunkSize, chunkOverlap)
      message.success(`文档上传成功，已分片 ${doc.chunk_count ?? 0} 个`)
      setUploadedDoc(doc)
      form.setFieldsValue({ doc_id: doc.id })
      fetchDocuments()
    } catch (e) {
      // 错误已由拦截器处理
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createDocExplanation(values)
      message.success('创建成功')
      setCreateModalVisible(false)
      fetchExplanations()
    } finally {
      setSaving(false)
    }
  }

  // ---------- 编辑 ----------
  const showEditModal = (exp: DocExplanation) => {
    setEditingExp(exp)
    editForm.setFieldsValue({
      explanation: exp.explanation,
      source: exp.source,
      status: exp.status,
    })
    setEditModalVisible(true)
  }

  const handleEdit = async () => {
    if (!editingExp) return
    try {
      const values = await editForm.validateFields()
      setSaving(true)
      await updateDocExplanation(editingExp.id, values)
      message.success('更新成功')
      setEditModalVisible(false)
      fetchExplanations()
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteExp = async (id: string) => {
    try {
      await deleteDocExplanation(id)
      message.success('删除成功')
      fetchExplanations()
    } catch (e) {
      // 错误已处理
    }
  }

  // ---------- 源文档 ----------
  const handleUploadDocument = async (file: File) => {
    setUploading(true)
    try {
      const doc = await uploadGlobalDocument(file, chunkSize, chunkOverlap)
      message.success(`文档上传成功，已分片 ${doc.chunk_count ?? 0} 个`)
      setUploadModalVisible(false)
      fetchDocuments()
    } catch (e) {
      // 错误已由拦截器处理
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleCreateFromText = async () => {
    try {
      const values = await textForm.validateFields()
      setTextSaving(true)
      const doc = await createGlobalDocumentFromText({
        title: values.title || undefined,
        content: values.content,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
      })
      message.success(`文档创建成功，已分片 ${doc.chunk_count ?? 0} 个`)
      setTextModalVisible(false)
      textForm.resetFields()
      fetchDocuments()
    } catch (e) {
      // validateFields 抛错或请求失败已处理
    } finally {
      setTextSaving(false)
    }
  }

  const handlePreviewDoc = async (doc: DocumentInfo) => {
    setPreviewDoc(doc)
    setPreviewLoading(true)
    try {
      const detail = await getDocumentDetail(doc.id)
      setPreviewDoc(detail)
    } catch (e) {
      // 保留列表摘要展示
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleDeleteDoc = async (id: string) => {
    try {
      await deleteDocument(id)
      message.success('文档已删除（关联的解释与分片一并清除）')
      fetchDocuments()
      fetchExplanations()
    } catch (e) {
      // 错误已处理
    }
  }

  // ---------- 文档解析（minerU） ----------
  const fetchParseFiles = async () => {
    setParseFilesLoading(true)
    try {
      const data = await getParseSourceFiles()
      setParseSourceFiles(data.items || [])
    } catch (e) {
      // 错误已处理
    } finally {
      setParseFilesLoading(false)
    }
  }

  const fetchParseBatches = async () => {
    setParseBatchesLoading(true)
    try {
      const data = await getDocParseBatches()
      setParseBatches(data || [])
    } catch (e) {
      // 错误已处理
    } finally {
      setParseBatchesLoading(false)
    }
  }

  // 轮询运行中的批次
  useEffect(() => {
    const running = parseBatches.filter(b => b.status === 'running' || b.status === 'pending')
    if (running.length === 0) return
    const timer = window.setInterval(async () => {
      try {
        const data = await getDocParseBatches()
        setParseBatches(data || [])
        // 若正在查看该批次的结果且批次已完成，刷新结果
        if (viewingBatchId) {
          const batch = (data || []).find(b => b.id === viewingBatchId)
          if (batch && batch.status !== 'running' && batch.status !== 'pending') {
            const results = await getDocParseResults(viewingBatchId)
            setViewingResults(results || [])
          }
        }
      } catch (e) {
        // 轮询失败忽略
      }
    }, 5000)
    return () => window.clearInterval(timer)
  }, [parseBatches, viewingBatchId])

  const handleParseFileUpload = async (file: File) => {
    setParseUploading(true)
    try {
      const result = await uploadParseSourceFile(file)
      message.success(`源文件已保存：${result.file_name || file.name}`)
      fetchParseFiles()
    } catch (e) {
      // 错误已处理
    } finally {
      setParseUploading(false)
    }
    return false
  }

  const handleDeleteParseFile = async (objectName: string) => {
    try {
      await deleteParseSourceFile(objectName)
      message.success('源文件已删除')
      fetchParseFiles()
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

  const handleCreateParseBatch = async () => {
    try {
      const values = await parseForm.validateFields()
      setParseSubmitting(true)
      const batch = await createDocParseBatch({
        name: values.name || undefined,
        parser_model_id: values.parser_model_id,
        object_names: selectedFileKeys as string[],
        config: { language: values.language || 'ch' },
      })
      message.success(`解析任务已提交：${batch.name}`)
      setParseModalVisible(false)
      setSelectedFileKeys([])
      fetchParseBatches()
    } catch (e) {
      // 错误已处理
    } finally {
      setParseSubmitting(false)
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
      fetchParseBatches()
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
      fetchParseBatches()
    } catch (e) {
      // 错误已处理
    }
  }

  // ---------- 过滤 ----------
  const filteredExplanations = useMemo(() => {    const kw = expSearch.trim().toLowerCase()
    return explanations.filter(exp => {
      if (statusFilter && exp.status !== statusFilter) return false
      if (!kw) return true
      return (
        (exp.document_title || '').toLowerCase().includes(kw) ||
        exp.explanation.toLowerCase().includes(kw)
      )
    })
  }, [explanations, expSearch, statusFilter])

  const filteredDocuments = useMemo(() => {
    const kw = docSearch.trim().toLowerCase()
    if (!kw) return documents
    return documents.filter(d => (d.title || '').toLowerCase().includes(kw))
  }, [documents, docSearch])

  // ---------- 渲染辅助 ----------
  const renderStatus = (status: string) => {
    const s = STATUS_LABELS[status] || { label: status, color: 'default' }
    return <Tag color={s.color}>{s.label}</Tag>
  }

  const renderSource = (source: string) => <Tag>{SOURCE_LABELS[source] || source}</Tag>

  const explanationColumns = [
    {
      title: '文档标题',
      dataIndex: 'document_title',
      key: 'document_title',
      ellipsis: true,
    },
    {
      title: '解释内容',
      dataIndex: 'explanation',
      key: 'explanation',
      ellipsis: true,
      width: 320,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 100,
      render: renderSource,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: renderStatus,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: DocExplanation) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setViewingExp(record)}>
            查看
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => showEditModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该解释?" onConfirm={() => handleDeleteExp(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const documentColumns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 80,
      render: (t: string) => <Tag color="blue">{(t || 'txt').toUpperCase()}</Tag>,
    },
    {
      title: '分片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
    },
    {
      title: '内容摘要',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      width: 300,
      render: (text: string) => text || '-',
    },
    {
      title: '来源',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 100,
      render: renderSource,
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      render: (_: unknown, record: DocumentInfo) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handlePreviewDoc(record)}>
            预览
          </Button>
          <Button
            type="link"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              setActiveTab('explanations')
              showCreateModal(record.id)
            }}
          >
            新建解释
          </Button>
          <Popconfirm
            title="删除文档将同时删除其所有解释与分片，确定?"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDeleteDoc(record.id)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // ---------- 文档解析表格 ----------
  const parseStatusRender = (status: string) => {
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

  const scoreColor = (score?: number) => (score === undefined ? 'default' : score >= 80 ? 'success' : score >= 60 ? 'warning' : 'error')

  const parseFileColumns = [
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
        <Popconfirm title="确定删除该源文件?" onConfirm={() => handleDeleteParseFile(record.object_name)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
        </Popconfirm>
      ),
    },
  ]

  const parseBatchColumns = [
    { title: '任务名', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '解析服务', dataIndex: 'parser_model_name', key: 'parser_model_name', width: 140 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: parseStatusRender },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 120,
      render: (p: number, record: DocParseBatchInfo) => (
        record.status === 'running'
          ? <Progress percent={p} size="small" status="active" />
          : <Progress percent={p} size="small" />
      ),
    },
    {
      title: '成功/失败',
      key: 'files',
      width: 100,
      render: (_: unknown, record: DocParseBatchInfo) => (
        <span>
          <span style={{ color: '#52c41a' }}>{record.success_files}</span> /{' '}
          <span style={{ color: record.failed_files ? '#f5222d' : undefined }}>{record.failed_files}</span>
        </span>
      ),
    },
    {
      title: '平均分',
      key: 'avg_score',
      width: 90,
      render: (_: unknown, record: DocParseBatchInfo) => {
        const s = record.evaluation_summary?.avg_score
        return s === undefined ? '-' : <Tag color={scoreColor(s)}>{s}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (d: string) => (d ? dayjs(d).format('MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 230,
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

  const parseResultColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: parseStatusRender },
    {
      title: '得分',
      key: 'score',
      width: 80,
      render: (_: unknown, record: DocParseResultInfo) => {
        const s = record.evaluation?.score
        return s === undefined ? '-' : <Tag color={scoreColor(s)}>{s}</Tag>
      },
    },
    {
      title: '耗时',
      dataIndex: 'duration',
      key: 'duration',
      width: 80,
      render: (d?: number) => (d === undefined ? '-' : `${d.toFixed(1)}s`),
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
      width: 160,
      render: (_: unknown, record: DocParseResultInfo) => (
        <Space size="small">
          {record.status === 'success' && (
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewMd(record)}>
              查看
            </Button>
          )}
          {record.doc_id && (
            <Button
              type="link"
              size="small"
              onClick={() => {
                setActiveTab('documents')
                handlePreviewDoc({ id: record.doc_id!, title: record.file_name })
              }}
            >
              文档
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Card title="文档解释" bodyStyle={{ paddingTop: 8 }}>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'explanations',
            label: '文档解释',
            children: (
              <>
                <Space style={{ marginBottom: 16 }} wrap>
                  <Input
                    placeholder="搜索文档标题或解释内容"
                    prefix={<SearchOutlined />}
                    allowClear
                    style={{ width: 260 }}
                    value={expSearch}
                    onChange={e => setExpSearch(e.target.value)}
                  />
                  <Select
                    placeholder="状态筛选"
                    allowClear
                    style={{ width: 120 }}
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={STATUS_OPTIONS}
                  />
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => showCreateModal()}>
                    新建解释
                  </Button>
                </Space>
                <Table
                  dataSource={filteredExplanations}
                  columns={explanationColumns}
                  rowKey="id"
                  loading={expLoading}
                  locale={{ emptyText: <Empty description="暂无解释，点击右上角「新建解释」或先到「源文档」上传文档" /> }}
                />
              </>
            ),
          },
          {
            key: 'documents',
            label: '源文档',
            children: (
              <>
                <Space style={{ marginBottom: 16 }} wrap>
                  <Input
                    placeholder="搜索文档标题"
                    prefix={<SearchOutlined />}
                    allowClear
                    style={{ width: 260 }}
                    value={docSearch}
                    onChange={e => setDocSearch(e.target.value)}
                  />
                  <Button
                    type="primary"
                    icon={<UploadOutlined />}
                    onClick={() => {
                      setChunkSize(CHUNK_PRESET.size)
                      setChunkOverlap(CHUNK_PRESET.overlap)
                      setUploadModalVisible(true)
                    }}
                  >
                    上传文档
                  </Button>
                  <Button
                    icon={<FileTextOutlined />}
                    onClick={() => {
                      setChunkSize(CHUNK_PRESET.size)
                      setChunkOverlap(CHUNK_PRESET.overlap)
                      textForm.resetFields()
                      setTextModalVisible(true)
                    }}
                  >
                    粘贴文本创建
                  </Button>
                </Space>
                <Table
                  dataSource={filteredDocuments}
                  columns={documentColumns}
                  rowKey="id"
                  loading={docLoading}
                  locale={{ emptyText: <Empty description="暂无文档，点击上方「上传文档」或「粘贴文本创建」添加源文件" /> }}
                />
              </>
            ),
          },
          {
            key: 'parse',
            label: '文档解析',
            children: (
              <>
                <Space style={{ marginBottom: 16 }} wrap>
                  <Upload beforeUpload={handleParseFileUpload} showUploadList={false} disabled={parseUploading}>
                    <Button type="primary" icon={<UploadOutlined />} loading={parseUploading}>
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
                  <Button icon={<ReloadOutlined />} onClick={() => { fetchParseFiles(); fetchParseBatches() }}>
                    刷新
                  </Button>
                </Space>
                <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  <div style={{ flex: '1 1 480px', minWidth: 0 }}>
                    <div style={{ fontWeight: 500, marginBottom: 8 }}>源文件</div>
                    <Table
                      dataSource={parseSourceFiles}
                      columns={parseFileColumns}
                      rowKey="object_name"
                      loading={parseFilesLoading}
                      size="small"
                      pagination={{ pageSize: 8, showTotal: t => `共 ${t} 个文件` }}
                      rowSelection={{ selectedRowKeys: selectedFileKeys, onChange: setSelectedFileKeys }}
                      locale={{ emptyText: <Empty description="暂无源文件，点击上方「上传源文件」保存 PDF/图片等待解析" /> }}
                    />
                  </div>
                  <div style={{ flex: '1 1 480px', minWidth: 0 }}>
                    <div style={{ fontWeight: 500, marginBottom: 8 }}>解析任务</div>
                    <Table
                      dataSource={parseBatches}
                      columns={parseBatchColumns}
                      rowKey="id"
                      loading={parseBatchesLoading}
                      size="small"
                      pagination={{ pageSize: 8, showTotal: t => `共 ${t} 个任务` }}
                      locale={{ emptyText: <Empty description="暂无解析任务，勾选源文件后点击「发起解析」" /> }}
                    />
                  </div>
                </div>
              </>
            ),
          },
        ]}
      />

      {/* 新建解释弹窗 */}
      <Modal
        title="新建文档解释"
        open={createModalVisible}
        onCancel={() => setCreateModalVisible(false)}
        onOk={handleCreate}
        confirmLoading={saving}
        width={640}
        okText="创建"
      >
        <Form form={form} labelCol={{ span: 5 }}>
          <Form.Item label="文档" required>
            <Segmented
              value={createMode}
              onChange={v => setCreateMode(v as 'select' | 'upload')}
              options={[
                { value: 'select', label: '选择已有文档' },
                { value: 'upload', label: '上传新文档' },
              ]}
              style={{ marginBottom: 8 }}
            />
            {createMode === 'select' ? (
              <Form.Item
                name="doc_id"
                noStyle
                rules={[{ required: true, message: '请选择文档' }]}
              >
                <Select
                  placeholder="搜索并选择文档"
                  showSearch
                  optionFilterProp="label"
                  loading={docLoading}
                  options={documents.map(d => ({ value: d.id, label: d.title || d.id }))}
                />
              </Form.Item>
            ) : (
              <div>
                <Upload.Dragger
                  beforeUpload={handleCreateUpload}
                  accept=".txt,.md,.pdf"
                  showUploadList={false}
                  disabled={uploading}
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">{uploading ? '上传中...' : '点击或拖拽文件到此处上传'}</p>
                  <p className="ant-upload-hint">支持 TXT、Markdown、PDF，上传后自动分片并选中</p>
                </Upload.Dragger>
                {uploadedDoc && (
                  <div style={{ marginTop: 8 }}>
                    <Tag color="success" style={{ fontSize: 13, padding: '2px 8px' }}>
                      {uploadedDoc.title}（{uploadedDoc.chunk_count ?? 0} 分片）
                    </Tag>
                  </div>
                )}
                {/* doc_id 由上传结果写入，隐藏校验 */}
                <Form.Item name="doc_id" hidden rules={[{ required: true, message: '请先上传文档' }]}>
                  <Input />
                </Form.Item>
              </div>
            )}
          </Form.Item>
          <Form.Item name="explanation" label="解释内容" rules={[{ required: true, message: '请输入解释内容' }]}>
            <Input.TextArea rows={6} placeholder="输入文档解释内容" />
          </Form.Item>
          <Form.Item name="source" label="来源" initialValue="manual">
            <Select options={SOURCE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑弹窗 */}
      <Modal
        title="编辑文档解释"
        open={editModalVisible}
        onCancel={() => setEditModalVisible(false)}
        onOk={handleEdit}
        confirmLoading={saving}
        width={640}
        okText="保存"
      >
        {editingExp && (
          <div style={{ marginBottom: 12, color: '#666', fontSize: 13 }}>
            文档：{editingExp.document_title || editingExp.doc_id}
          </div>
        )}
        <Form form={editForm} labelCol={{ span: 5 }}>
          <Form.Item name="explanation" label="解释内容" rules={[{ required: true, message: '请输入解释内容' }]}>
            <Input.TextArea rows={6} placeholder="输入文档解释内容" />
          </Form.Item>
          <Form.Item name="source" label="来源">
            <Select options={SOURCE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={STATUS_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 查看解释弹窗 */}
      <Modal
        title={`解释详情${viewingExp?.document_title ? ` - ${viewingExp.document_title}` : ''}`}
        open={!!viewingExp}
        onCancel={() => setViewingExp(null)}
        footer={[
          <Button key="edit" type="primary" onClick={() => {
            const exp = viewingExp
            setViewingExp(null)
            if (exp) showEditModal(exp)
          }}>
            编辑
          </Button>,
          <Button key="close" onClick={() => setViewingExp(null)}>关闭</Button>,
        ]}
        width={720}
      >
        {viewingExp && (
          <>
            <div style={{ fontWeight: 500, marginBottom: 8 }}>文档内容</div>
            <div
              style={{
                maxHeight: 260, overflowY: 'auto', padding: 12,
                background: '#f5f5f5', borderRadius: 6, whiteSpace: 'pre-wrap',
                fontSize: 13, lineHeight: 1.6,
              }}
            >
              {viewingExp.document_content || '（无内容）'}
            </div>
            <div style={{ fontWeight: 500, margin: '16px 0 8px' }}>解释内容</div>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6 }}>
              {viewingExp.explanation}
            </div>
            <div style={{ marginTop: 16 }}>
              {renderSource(viewingExp.source)} {renderStatus(viewingExp.status)}
              <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                创建于 {viewingExp.created_at ? dayjs(viewingExp.created_at).format('YYYY-MM-DD HH:mm') : '-'}
              </span>
            </div>
          </>
        )}
      </Modal>

      {/* 上传文档弹窗 */}
      <Modal
        title="上传文档"
        open={uploadModalVisible}
        onCancel={() => setUploadModalVisible(false)}
        footer={null}
        width={560}
      >
        <div style={{ marginBottom: 16 }}>
          <Space>
            <span>分片大小：</span>
            <InputNumber min={100} max={4000} value={chunkSize} onChange={(v: number | null) => setChunkSize(v || CHUNK_PRESET.size)} style={{ width: 100 }} />
            <span>字符</span>
            <span style={{ marginLeft: 8 }}>重叠：</span>
            <InputNumber min={0} max={1000} value={chunkOverlap} onChange={(v: number | null) => setChunkOverlap(v || 0)} style={{ width: 100 }} />
            <span>字符</span>
          </Space>
        </div>
        <Upload.Dragger
          beforeUpload={handleUploadDocument}
          accept=".txt,.md,.pdf"
          showUploadList={false}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">{uploading ? '上传中...' : '点击或拖拽文件到此处上传'}</p>
          <p className="ant-upload-hint">支持 TXT、Markdown、PDF，上传后自动分片</p>
        </Upload.Dragger>
      </Modal>

      {/* 粘贴文本弹窗 */}
      <Modal
        title="粘贴文本创建文档"
        open={textModalVisible}
        onCancel={() => setTextModalVisible(false)}
        onOk={handleCreateFromText}
        confirmLoading={textSaving}
        okText="创建"
        width={640}
      >
        <Form form={textForm} labelCol={{ span: 5 }}>
          <Form.Item name="title" label="文档标题">
            <Input placeholder="可选，默认按内容长度生成" />
          </Form.Item>
          <Form.Item name="content" label="文本内容" rules={[{ required: true, message: '请输入文本内容' }]}>
            <Input.TextArea rows={10} placeholder="粘贴文档内容..." />
          </Form.Item>
          <Form.Item label="分片设置">
            <Space>
              <span>大小</span>
              <InputNumber min={100} max={4000} value={chunkSize} onChange={(v: number | null) => setChunkSize(v || CHUNK_PRESET.size)} style={{ width: 100 }} />
              <span>字符 / 重叠</span>
              <InputNumber min={0} max={1000} value={chunkOverlap} onChange={(v: number | null) => setChunkOverlap(v || 0)} style={{ width: 100 }} />
              <span>字符</span>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 文档预览弹窗 */}
      <Modal
        title={`文档预览${previewDoc?.title ? ` - ${previewDoc.title}` : ''}`}
        open={!!previewDoc}
        onCancel={() => setPreviewDoc(null)}
        footer={<Button onClick={() => setPreviewDoc(null)}>关闭</Button>}
        width={760}
      >
        {previewDoc && (
          <>
            <div style={{ marginBottom: 12 }}>
              <Tag color="blue">{(previewDoc.file_type || 'txt').toUpperCase()}</Tag>
              {renderSource(previewDoc.source_type || '')}
              <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                {previewDoc.chunk_count ?? 0} 个分片
              </span>
            </div>
            <div
              style={{
                maxHeight: 480, overflowY: 'auto', padding: 12,
                background: '#f5f5f5', borderRadius: 6, whiteSpace: 'pre-wrap',
                fontSize: 13, lineHeight: 1.7,
              }}
            >
              {previewLoading ? '加载全文中...' : (previewDoc.content || '（无内容）')}
            </div>
          </>
        )}
      </Modal>

      {/* 发起解析弹窗 */}
      <Modal
        title={`发起解析（已选 ${selectedFileKeys.length} 个源文件）`}
        open={parseModalVisible}
        onCancel={() => setParseModalVisible(false)}
        onOk={handleCreateParseBatch}
        confirmLoading={parseSubmitting}
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
              loading={false}
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
        title={`解析结果${viewingBatchId ? ` - ${parseBatches.find(b => b.id === viewingBatchId)?.name || ''}` : ''}`}
        open={!!viewingBatchId}
        onCancel={() => { setViewingBatchId(null); setViewingResults([]) }}
        footer={null}
        width={820}
      >
        {viewingBatchId && parseBatches.find(b => b.id === viewingBatchId)?.error && (
          <div style={{ marginBottom: 12 }}>
            <Tag color="error">{parseBatches.find(b => b.id === viewingBatchId)!.error}</Tag>
          </div>
        )}
        <Table
          dataSource={viewingResults}
          columns={parseResultColumns}
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
                    得分 {viewingMd.evaluation.score}
                  </Tag>
                  {Object.entries(viewingMd.evaluation.metrics).map(([k, v]) => (
                    <Tag key={k}>{k}: {(v * 100).toFixed(0)}</Tag>
                  ))}
                </Space>
                <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                  {viewingMd.evaluation.suggestions.map((s, i) => <div key={i}>💡 {s}</div>)}
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
    </Card>
  )
}

export default DocExplanations
