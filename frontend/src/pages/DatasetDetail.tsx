import React, { useEffect, useState } from 'react'
import { Card, Table, Upload, Button, message, Tabs, Tag, Space, Divider, Popconfirm, Modal, Descriptions, Input, InputNumber, Select, Spin, Alert, Typography } from 'antd'
import { UploadOutlined, DownloadOutlined, DeleteOutlined, EyeOutlined, PlusOutlined, FileTextOutlined, EnvironmentOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { getDataset, getQARecords, uploadDatasetFile, downloadTemplate, deleteQARecord, batchDeleteQARecords, getDatasetDocuments, getDatasetChunks, uploadDocument, createDocumentFromText, createDocumentsFromNews, getDocumentChunks, getHotArticles } from '@/api'
import GeneratePanel from '@/components/GeneratePanel'
import type { Dataset, QARecord, DocumentInfo, ChunkInfo, HotArticle } from '@/types'

const DatasetDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [qaRecords, setQARecords] = useState<QARecord[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  // 文档和分片状态
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [docTotal, setDocTotal] = useState(0)
  const [docLoading, setDocLoading] = useState(false)
  const [docPage, setDocPage] = useState(1)
  const [docPageSize, setDocPageSize] = useState(10)

  const [chunks, setChunks] = useState<ChunkInfo[]>([])
  const [chunkTotal, setChunkTotal] = useState(0)
  const [chunkLoading, setChunkLoading] = useState(false)
  const [chunkPage, setChunkPage] = useState(1)
  const [chunkPageSize, setChunkPageSize] = useState(10)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)

  // 详情弹窗
  const [docDetailVisible, setDocDetailVisible] = useState(false)
  const [chunkDetailVisible, setChunkDetailVisible] = useState(false)
  const [selectedDoc, setSelectedDoc] = useState<DocumentInfo | null>(null)
  const [selectedChunk, setSelectedChunk] = useState<ChunkInfo | null>(null)

  // 创建文档相关
  const [createDocModalVisible, setCreateDocModalVisible] = useState(false)
  const [createDocType, setCreateDocType] = useState<'upload' | 'text' | 'news'>('upload')
  const [newDocTitle, setNewDocTitle] = useState('')
  const [newDocContent, setNewDocContent] = useState('')
  const [chunkSize, setChunkSize] = useState(500)
  const [chunkOverlap, setChunkOverlap] = useState(50)
  const [creatingDoc, setCreatingDoc] = useState(false)

  // 热点新闻选择
  const [newsArticles, setNewsArticles] = useState<HotArticle[]>([])
  const [newsLoading, setNewsLoading] = useState(false)
  const [selectedNewsIds, setSelectedNewsIds] = useState<string[]>([])

  // 文档分片详情查看
  const [docChunksVisible, setDocChunksVisible] = useState(false)
  const [docChunks, setDocChunks] = useState<ChunkInfo[]>([])
  const [docChunksTotal, setDocChunksTotal] = useState(0)
  const [docChunksLoading, setDocChunksLoading] = useState(false)
  const [docChunksPage, setDocChunksPage] = useState(1)

  const fetchDataset = async () => {
    if (!id) return
    try {
      const data = await getDataset(id)
      setDataset(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchQARecords = async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await getQARecords(id, { page, size: pageSize })
      setQARecords(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  const fetchDocuments = async () => {
    if (!id) return
    setDocLoading(true)
    try {
      const data = await getDatasetDocuments(id, { page: docPage, size: docPageSize })
      setDocuments(data.items)
      setDocTotal(data.total)
    } finally {
      setDocLoading(false)
    }
  }

  const fetchChunks = async () => {
    if (!id) return
    setChunkLoading(true)
    try {
      const params: { page: number; size: number; doc_id?: string } = { page: chunkPage, size: chunkPageSize }
      if (selectedDocId) {
        params.doc_id = selectedDocId
      }
      const data = await getDatasetChunks(id, params)
      setChunks(data.items)
      setChunkTotal(data.total)
    } finally {
      setChunkLoading(false)
    }
  }

  useEffect(() => {
    fetchDataset()
    fetchQARecords()
  }, [id, page, pageSize])

  useEffect(() => {
    fetchDocuments()
  }, [id, docPage, docPageSize])

  useEffect(() => {
    fetchChunks()
  }, [id, chunkPage, chunkPageSize, selectedDocId])

  // 加载热点新闻
  const fetchNewsArticles = async () => {
    setNewsLoading(true)
    try {
      const data = await getHotArticles({ limit: 50 })
      setNewsArticles(data)
    } finally {
      setNewsLoading(false)
    }
  }

  // 上传文档
  const handleUploadDocument = async (file: File) => {
    if (!id) return
    setCreatingDoc(true)
    try {
      const result = await uploadDocument(id, file, chunkSize, chunkOverlap)
      message.success(`文档上传成功，已分片 ${result.chunk_count} 个`)
      setCreateDocModalVisible(false)
      fetchDocuments()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setCreatingDoc(false)
    }
    return false
  }

  // 从文本创建文档
  const handleCreateFromText = async () => {
    if (!id || !newDocContent) {
      message.error('请输入文档内容')
      return
    }
    setCreatingDoc(true)
    try {
      const result = await createDocumentFromText(id, {
        title: newDocTitle,
        content: newDocContent,
        source_type: 'text_input',
        file_type: 'text'
      }, { chunk_size: chunkSize, chunk_overlap: chunkOverlap })
      message.success(`文档创建成功，已分片 ${result.chunk_count} 个`)
      setCreateDocModalVisible(false)
      setNewDocTitle('')
      setNewDocContent('')
      fetchDocuments()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setCreatingDoc(false)
    }
  }

  // 从热点新闻创建文档
  const handleCreateFromNews = async () => {
    if (!id || selectedNewsIds.length === 0) {
      message.error('请选择至少一篇新闻')
      return
    }
    setCreatingDoc(true)
    try {
      const result = await createDocumentsFromNews(id, selectedNewsIds, chunkSize, chunkOverlap)
      message.success(`成功创建 ${result.created_count} 个文档`)
      setCreateDocModalVisible(false)
      setSelectedNewsIds([])
      fetchDocuments()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setCreatingDoc(false)
    }
  }

  // 查看文档分片详情
  const handleViewDocChunks = async (doc: DocumentInfo) => {
    if (!id) return
    setSelectedDoc(doc)
    setDocChunksVisible(true)
    setDocChunksLoading(true)
    setDocChunksPage(1)
    try {
      const data = await getDocumentChunks(id, doc.id, { page: 1, size: 20 })
      setDocChunks(data.items)
      setDocChunksTotal(data.total)
    } finally {
      setDocChunksLoading(false)
    }
  }

  // 加载更多分片
  const loadMoreChunks = async (page: number) => {
    if (!id || !selectedDoc) return
    setDocChunksLoading(true)
    setDocChunksPage(page)
    try {
      const data = await getDocumentChunks(id, selectedDoc.id, { page, size: 20 })
      setDocChunks(data.items)
    } finally {
      setDocChunksLoading(false)
    }
  }

  const handleUpload = async (file: File) => {
    if (!id) return
    try {
      await uploadDatasetFile(id, file)
      message.success('导入成功')
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
    return false
  }

  const handleDeleteRecord = async (recordId: string) => {
    if (!id) return
    try {
      await deleteQARecord(id, recordId)
      message.success('删除成功')
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleBatchDelete = async () => {
    if (!id || selectedRowKeys.length === 0) return
    try {
      await batchDeleteQARecords(id, selectedRowKeys as string[])
      message.success(`成功删除 ${selectedRowKeys.length} 条记录`)
      setSelectedRowKeys([])
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      ellipsis: true,
    },
    {
      title: '回答',
      dataIndex: 'answer',
      key: 'answer',
      ellipsis: true,
      render: (v: string) => v || <Tag color="default">无</Tag>,
    },
    {
      title: '参考上下文',
      dataIndex: 'contexts',
      key: 'contexts',
      ellipsis: true,
      render: (contexts: string[]) => {
        if (!contexts || contexts.length === 0) return <Tag color="default">无</Tag>
        return (
          <div style={{ maxWidth: 200 }}>
            {contexts.slice(0, 2).map((c, i) => (
              <div key={i} style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 12,
                color: '#666',
                marginBottom: 2
              }}>
                [{i + 1}] {c.substring(0, 50)}...
              </div>
            ))}
            {contexts.length > 2 && <span style={{ fontSize: 12, color: '#999' }}>+{contexts.length - 2}条</span>}
          </div>
        )
      },
    },
    {
      title: 'Ground Truth',
      dataIndex: 'ground_truth',
      key: 'ground_truth',
      ellipsis: true,
      render: (v: string) => v || <Tag color="default">无</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (date: string) => dayjs(date).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: QARecord) => (
        <Popconfirm
          title="确定删除此记录？"
          onConfirm={() => handleDeleteRecord(record.id)}
        >
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys)
    },
  }

  // 文档表格列
  const docColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80, ellipsis: true },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (v: string) => v || <Tag color="default">无标题</Tag>,
    },
    {
      title: '内容预览',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (v: string) => v ? `${v.substring(0, 100)}...` : <Tag color="default">无</Tag>,
    },
    {
      title: '文件类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 100,
      render: (v: string) => v ? <Tag>{v}</Tag> : '-',
    },
    {
      title: '来源',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 100,
      render: (v: string) => v || '-',
    },
    {
      title: '分片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
      render: (v: number) => v || 0,
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: DocumentInfo) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => {
              setSelectedDoc(record)
              setDocDetailVisible(true)
            }}
          >
            查看
          </Button>
          <Button
            type="link"
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => handleViewDocChunks(record)}
          >
            分片详情
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setSelectedDocId(record.id)
              setChunkPage(1)
            }}
          >
            分片列表
          </Button>
        </Space>
      ),
    },
  ]

  // 分片表格列
  const chunkColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80, ellipsis: true },
    {
      title: '文档',
      dataIndex: 'document_title',
      key: 'document_title',
      width: 150,
      ellipsis: true,
      render: (v: string) => v || <Tag color="default">未知</Tag>,
    },
    {
      title: '序号',
      dataIndex: 'chunk_index',
      key: 'chunk_index',
      width: 60,
    },
    {
      title: '内容预览',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (v: string) => v ? `${v.substring(0, 80)}...` : '-',
    },
    {
      title: '字符范围',
      key: 'char_range',
      width: 100,
      render: (_: unknown, record: ChunkInfo) => {
        if (record.start_char && record.end_char) {
          return `${record.start_char}-${record.end_char}`
        }
        return '-'
      },
    },
    {
      title: 'Milvus ID',
      dataIndex: 'milvus_id',
      key: 'milvus_id',
      width: 100,
      ellipsis: true,
      render: (v: string) => v ? <Tag color="blue">{v.substring(0, 8)}...</Tag> : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: ChunkInfo) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => {
            setSelectedChunk(record)
            setChunkDetailVisible(true)
          }}
        >
          查看
        </Button>
      ),
    },
  ]

  const tabItems = [
    {
      key: 'records',
      label: 'QA记录',
      children: (
        <div>
          {selectedRowKeys.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <Popconfirm
                title={`确定删除选中的 ${selectedRowKeys.length} 条记录？`}
                onConfirm={handleBatchDelete}
              >
                <Button danger icon={<DeleteOutlined />}>
                  批量删除 ({selectedRowKeys.length})
                </Button>
              </Popconfirm>
            </div>
          )}
          <Table
            dataSource={qaRecords}
            columns={columns}
            rowKey="id"
            loading={loading}
            rowSelection={rowSelection}
            pagination={{
              current: page,
              pageSize,
              total,
              onChange: (p, ps) => {
                setPage(p)
                setPageSize(ps)
                setSelectedRowKeys([]) // 切换页码时清空选择
              },
            }}
          />
        </div>
      ),
    },
    {
      key: 'generate',
      label: '生成数据',
      children: (
        <GeneratePanel
          datasetId={id || ''}
          onGenerateSuccess={fetchQARecords}
        />
      ),
    },
    {
      key: 'import',
      label: '导入数据',
      children: (
        <Card>
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>下载模板</div>
              <Space>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate('json')}
                >
                  JSON 模板
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate('jsonl')}
                >
                  JSONL 模板
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate('csv')}
                >
                  CSV 模板
                </Button>
              </Space>
              <p style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
                选择合适的模板格式下载，按模板格式填写数据后上传导入
              </p>
            </div>

            <Divider />

            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>上传文件</div>
              <Upload
                beforeUpload={handleUpload}
                accept=".json,.jsonl,.csv"
                showUploadList={false}
              >
                <Button icon={<UploadOutlined />}>上传文件导入</Button>
              </Upload>
              <p style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
                支持 JSON、JSONL、CSV 格式文件
              </p>
            </div>
          </Space>
        </Card>
      ),
    },
    {
      key: 'documents',
      label: '文档查看',
      children: (
        <div>
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  setCreateDocType('upload')
                  setCreateDocModalVisible(true)
                  fetchNewsArticles()
                }}
              >
                创建文档
              </Button>
            </Space>
          </div>
          <Table
            dataSource={documents}
            columns={docColumns}
            rowKey="id"
            loading={docLoading}
            pagination={{
              current: docPage,
              pageSize: docPageSize,
              total: docTotal,
              onChange: (p, ps) => {
                setDocPage(p)
                setDocPageSize(ps)
              },
            }}
          />
        </div>
      ),
    },
    {
      key: 'chunks',
      label: '分片查看',
      children: (
        <div>
          {selectedDocId && (
            <div style={{ marginBottom: 16 }}>
              <Space>
                <Tag color="blue">筛选文档: {selectedDocId}</Tag>
                <Button size="small" onClick={() => setSelectedDocId(null)}>
                  清除筛选
                </Button>
              </Space>
            </div>
          )}
          <Table
            dataSource={chunks}
            columns={chunkColumns}
            rowKey="id"
            loading={chunkLoading}
            pagination={{
              current: chunkPage,
              pageSize: chunkPageSize,
              total: chunkTotal,
              onChange: (p, ps) => {
                setChunkPage(p)
                setChunkPageSize(ps)
              },
            }}
          />
        </div>
      ),
    },
  ]

  return (
    <Card title={dataset?.name || '数据集详情'}>
      <Tabs items={tabItems} />

      {/* 创建文档弹窗 */}
      <Modal
        title="创建文档"
        open={createDocModalVisible}
        onCancel={() => setCreateDocModalVisible(false)}
        footer={null}
        width={700}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <div style={{ marginBottom: 8 }}>选择创建方式：</div>
            <Select
              value={createDocType}
              onChange={(v) => {
                setCreateDocType(v)
                if (v === 'news') fetchNewsArticles()
              }}
              style={{ width: '100%' }}
              options={[
                { value: 'upload', label: '上传文档' },
                { value: 'text', label: '输入文本' },
                { value: 'news', label: '从热点新闻创建' },
              ]}
            />
          </div>

          <Divider />

          {/* 分片参数 */}
          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>分片参数：</div>
            <Space>
              <span>分片大小：</span>
              <InputNumber
                value={chunkSize}
                onChange={(v: number | null) => setChunkSize(v || 500)}
                min={100}
                max={2000}
                style={{ width: 100 }}
              />
              <span>字符</span>
              <Divider type="vertical" />
              <span>重叠大小：</span>
              <InputNumber
                value={chunkOverlap}
                onChange={(v: number | null) => setChunkOverlap(v || 50)}
                min={0}
                max={200}
                style={{ width: 100 }}
              />
              <span>字符</span>
            </Space>
          </div>

          <Divider />

          {/* 上传文档 */}
          {createDocType === 'upload' && (
            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>上传文档文件：</div>
              <Upload
                beforeUpload={handleUploadDocument}
                accept=".txt,.md,.pdf"
                showUploadList={false}
              >
                <Button icon={<UploadOutlined />} loading={creatingDoc}>
                  选择文件上传
                </Button>
              </Upload>
              <p style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
                支持 TXT、Markdown、PDF 格式文件
              </p>
            </div>
          )}

          {/* 输入文本 */}
          {createDocType === 'text' && (
            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>文档标题：</div>
              <Input
                value={newDocTitle}
                onChange={(e) => setNewDocTitle(e.target.value)}
                placeholder="可选，默认根据内容长度生成"
              />
              <div style={{ marginTop: 16, marginBottom: 8, fontWeight: 500 }}>文档内容：</div>
              <Input.TextArea
                value={newDocContent}
                onChange={(e) => setNewDocContent(e.target.value)}
                rows={8}
                placeholder="请输入文档内容..."
              />
              <div style={{ marginTop: 16 }}>
                <Button
                  type="primary"
                  onClick={handleCreateFromText}
                  loading={creatingDoc}
                  disabled={!newDocContent}
                >
                  创建文档
                </Button>
              </div>
            </div>
          )}

          {/* 从热点新闻创建 */}
          {createDocType === 'news' && (
            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>选择热点新闻：</div>
              {newsLoading ? (
                <Spin />
              ) : (
                <Select
                  mode="multiple"
                  value={selectedNewsIds}
                  onChange={(v) => setSelectedNewsIds(v)}
                  style={{ width: '100%' }}
                  placeholder="选择要创建文档的新闻文章"
                  maxTagCount={5}
                  options={newsArticles.map(a => ({
                    value: a.id,
                    label: a.title,
                  }))}
                />
              )}
              <p style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
                已选择 {selectedNewsIds.length} 篇新闻
              </p>
              <div style={{ marginTop: 16 }}>
                <Button
                  type="primary"
                  onClick={handleCreateFromNews}
                  loading={creatingDoc}
                  disabled={selectedNewsIds.length === 0}
                >
                  创建文档
                </Button>
              </div>
            </div>
          )}
        </Space>
      </Modal>

      {/* 文档详情弹窗 */}
      <Modal
        title="文档详情"
        open={docDetailVisible}
        onCancel={() => setDocDetailVisible(false)}
        footer={null}
        width={700}
      >
        {selectedDoc && (
          <Descriptions bordered column={2}>
            <Descriptions.Item label="ID">{selectedDoc.id}</Descriptions.Item>
            <Descriptions.Item label="标题">{selectedDoc.title || '无'}</Descriptions.Item>
            <Descriptions.Item label="文件类型">{selectedDoc.file_type || '-'}</Descriptions.Item>
            <Descriptions.Item label="来源">{selectedDoc.source_type || '-'}</Descriptions.Item>
            <Descriptions.Item label="分片数">{selectedDoc.chunk_count || 0}</Descriptions.Item>
            <Descriptions.Item label="内容" span={2}>
              <div style={{ maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                {selectedDoc.content || '无内容'}
              </div>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {/* 文档分片详情弹窗（带位置标注） */}
      <Modal
        title={`文档分片详情 - ${selectedDoc?.title || '未知文档'}`}
        open={docChunksVisible}
        onCancel={() => setDocChunksVisible(false)}
        footer={null}
        width={900}
      >
        {selectedDoc && (
          <div>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`文档共 ${docChunksTotal} 个分片，每个分片标注了在原文中的起始和结束位置`}
            />
            <Table
              dataSource={docChunks}
              rowKey="id"
              loading={docChunksLoading}
              pagination={{
                current: docChunksPage,
                pageSize: 20,
                total: docChunksTotal,
                onChange: loadMoreChunks,
              }}
              columns={[
                {
                  title: '序号',
                  dataIndex: 'chunk_index',
                  key: 'chunk_index',
                  width: 60,
                  render: (v: number) => <Tag color="blue">#{v}</Tag>,
                },
                {
                  title: '位置范围',
                  key: 'position',
                  width: 120,
                  render: (_: unknown, record: ChunkInfo) => (
                    <Space>
                      <EnvironmentOutlined style={{ color: '#1890ff' }} />
                      <span>
                        {record.start_char ?? '-'} - {record.end_char ?? '-'}
                      </span>
                      {(record.start_char !== undefined && record.end_char !== undefined) && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          ({record.end_char - record.start_char}字)
                        </Typography.Text>
                      )}
                    </Space>
                  ),
                },
                {
                  title: '内容',
                  dataIndex: 'content',
                  key: 'content',
                  ellipsis: false,
                  render: (v: string) => (
                    <div
                      style={{
                        maxHeight: 150,
                        overflow: 'auto',
                        whiteSpace: 'pre-wrap',
                        background: '#f5f5f5',
                        padding: 8,
                        borderRadius: 4,
                        fontSize: 13,
                      }}
                    >
                      {v}
                    </div>
                  ),
                },
                {
                  title: '操作',
                  key: 'action',
                  width: 80,
                  render: (_: unknown, record: ChunkInfo) => (
                    <Button
                      type="link"
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={() => {
                        setSelectedChunk(record)
                        setChunkDetailVisible(true)
                      }}
                    >
                      详情
                    </Button>
                  ),
                },
              ]}
            />
          </div>
        )}
      </Modal>

      {/* 分片详情弹窗 */}
      <Modal
        title="分片详情"
        open={chunkDetailVisible}
        onCancel={() => setChunkDetailVisible(false)}
        footer={null}
        width={700}
      >
        {selectedChunk && (
          <Descriptions bordered column={2}>
            <Descriptions.Item label="ID">{selectedChunk.id}</Descriptions.Item>
            <Descriptions.Item label="文档">{selectedChunk.document_title || '未知'}</Descriptions.Item>
            <Descriptions.Item label="序号">
              <Tag color="blue">#{selectedChunk.chunk_index}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="字符范围">
              <Space>
                <EnvironmentOutlined style={{ color: '#1890ff' }} />
                {selectedChunk.start_char && selectedChunk.end_char
                  ? `${selectedChunk.start_char} - ${selectedChunk.end_char} (${selectedChunk.end_char - selectedChunk.start_char}字)`
                  : '-'}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="Milvus ID">{selectedChunk.milvus_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="文档ID">{selectedChunk.doc_id}</Descriptions.Item>
            <Descriptions.Item label="内容" span={2}>
              <div style={{ maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                {selectedChunk.content}
              </div>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </Card>
  )
}

export default DatasetDetail