import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  DeleteOutlined,
  EyeOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { formatTime } from '@/utils/format'
import { usePollingWhenRunning } from '@/hooks/usePollingWhenRunning'
import {
  cancelMMRun,
  createMMRun,
  deleteMMDataset,
  getMMDataset,
  getMMDatasets,
  getMMRun,
  getMMRunQueries,
  getMMRuns,
  getModels,
  importMMDataset,
  rerunMMRun,
} from '@/api'
import type {
  MMDataset,
  MMDatasetDetail,
  MMMetrics,
  MMQueryResult,
  MMQueryResultPage,
  MMRun,
  ModelConfig,
} from '@/types'

const METRIC_COLUMNS: Array<{ key: keyof MMMetrics; label: string }> = [
  { key: 'recall@1', label: 'Recall@1' },
  { key: 'recall@5', label: 'Recall@5' },
  { key: 'recall@10', label: 'Recall@10' },
  { key: 'mrr@10', label: 'MRR@10' },
  { key: 'ndcg@10', label: 'nDCG@10' },
]

const fmtMetric = (value?: number | null) => (value == null ? '-' : value.toFixed(4))

const statusTag = (status: string) => {
  const map: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '排队中' },
    running: { color: 'processing', text: '运行中' },
    completed: { color: 'success', text: '已完成' },
    failed: { color: 'error', text: '失败' },
    cancelled: { color: 'warning', text: '已取消' },
    importing: { color: 'processing', text: '导入中' },
    ready: { color: 'success', text: '就绪' },
  }
  const entry = map[status] ?? { color: 'default', text: status }
  return <Tag color={entry.color}>{entry.text}</Tag>
}

const normFile = (event: any) => (Array.isArray(event) ? event : event?.fileList)

const runIsActive = (run: MMRun) => run.status === 'pending' || run.status === 'running'

const MultimodalEmbeddings: React.FC = () => {
  const [tab, setTab] = useState('runs')
  const [runs, setRuns] = useState<MMRun[]>([])
  const [datasets, setDatasets] = useState<MMDataset[]>([])
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [runStatusFilter, setRunStatusFilter] = useState<string | undefined>()

  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createForm] = Form.useForm()

  const [importOpen, setImportOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importForm] = Form.useForm()
  const [importFile, setImportFile] = useState<File | null>(null)

  const [detailRun, setDetailRun] = useState<MMRun | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [queryPage, setQueryPage] = useState<MMQueryResultPage | null>(null)
  const [queryLoading, setQueryLoading] = useState(false)
  const [queryFilter, setQueryFilter] = useState<{
    page: number
    page_size: number
    subset?: string
    only_missed: boolean
  }>({ page: 1, page_size: 20, only_missed: false })

  const [datasetDetail, setDatasetDetail] = useState<MMDatasetDetail | null>(null)
  const [datasetOpen, setDatasetOpen] = useState(false)
  const [datasetLoading, setDatasetLoading] = useState(false)

  const fetchAll = async (showLoading = true) => {
    if (showLoading) setLoading(true)
    try {
      const [runData, datasetData, modelData] = await Promise.all([
        getMMRuns().catch((e) => { console.error('getMMRuns failed:', e); return [] }),
        getMMDatasets().catch((e) => { console.error('getMMDatasets failed:', e); return [] }),
        getModels('embedding').catch((e) => { console.error('getModels embedding failed:', e); return [] }),
      ])
      setRuns(runData)
      setDatasets(datasetData)
      setEmbeddingModels(modelData)
    } finally {
      if (showLoading) setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
  }, [])

  usePollingWhenRunning(runs.some(runIsActive), () => fetchAll(false), 5000)

  const refreshDetail = async (runId: string, silent = true) => {
    if (!silent) setQueryLoading(true)
    try {
      const [run, page] = await Promise.all([
        getMMRun(runId),
        getMMRunQueries(runId, {
          page: queryFilter.page,
          page_size: queryFilter.page_size,
          subset: queryFilter.subset,
          only_missed: queryFilter.only_missed,
        }),
      ])
      setDetailRun(run)
      setQueryPage(page)
    } finally {
      if (!silent) setQueryLoading(false)
    }
  }

  usePollingWhenRunning(
    !!detailRun && runIsActive(detailRun),
    () => (detailRun ? refreshDetail(detailRun.id) : undefined),
    4000,
    [detailRun?.id, queryFilter.page, queryFilter.subset, queryFilter.only_missed],
  )

  const openRunDetail = async (run: MMRun) => {
    setDetailRun(run)
    setDetailOpen(true)
    setQueryFilter({ page: 1, page_size: 20, only_missed: false })
    setQueryLoading(true)
    try {
      const page = await getMMRunQueries(run.id, { page: 1, page_size: 20, only_missed: false })
      setQueryPage(page)
      const fresh = await getMMRun(run.id)
      setDetailRun(fresh)
    } catch (e) {
      // 拦截器已提示
    } finally {
      setQueryLoading(false)
    }
  }

  const reloadQueries = async (patch: Partial<typeof queryFilter>) => {
    if (!detailRun) return
    const next = { ...queryFilter, ...patch }
    setQueryFilter(next)
    setQueryLoading(true)
    try {
      const page = await getMMRunQueries(detailRun.id, {
        page: next.page,
        page_size: next.page_size,
        subset: next.subset,
        only_missed: next.only_missed,
      })
      setQueryPage(page)
    } finally {
      setQueryLoading(false)
    }
  }

  const openDatasetDetail = async (dataset: MMDataset) => {
    setDatasetOpen(true)
    setDatasetLoading(true)
    setDatasetDetail(null)
    try {
      setDatasetDetail(await getMMDataset(dataset.id, 20))
    } finally {
      setDatasetLoading(false)
    }
  }

  const showCreate = () => {
    createForm.resetFields()
    createForm.setFieldsValue({
      image_transport: 'data_url',
      request_format: 'content_array',
      batch_size: 8,
      top_k: 10,
    })
    setCreateOpen(true)
  }

  const submitCreate = async () => {
    const values = await createForm.validateFields()
    setCreating(true)
    try {
      await createMMRun({
        name: values.name,
        dataset_id: values.dataset_id,
        model_id: values.model_id,
        params: {
          image_transport: values.image_transport,
          request_format: values.request_format,
          batch_size: values.batch_size,
          top_k: values.top_k,
          ...(values.timeout ? { timeout: values.timeout } : {}),
          ...(values.max_retries != null ? { max_retries: values.max_retries } : {}),
        },
      })
      message.success('评测任务已创建')
      setCreateOpen(false)
      fetchAll(false)
    } finally {
      setCreating(false)
    }
  }

  const submitImport = async () => {
    const values = await importForm.validateFields()
    const file = importFile
    if (!file) {
      message.warning('请选择数据文件')
      return
    }
    setImporting(true)
    try {
      await importMMDataset({ file, name: values.name, description: values.description })
      message.success('评测集导入完成')
      setImportOpen(false)
      setImportFile(null)
      importForm.resetFields()
      fetchAll(false)
    } finally {
      setImporting(false)
    }
  }

  const handleCancel = async (run: MMRun) => {
    await cancelMMRun(run.id)
    message.success('已请求取消，任务将在批次边界停止')
    fetchAll(false)
  }

  const handleForceCancel = async (run: MMRun) => {
    await cancelMMRun(run.id, true)
    message.success('已强制取消')
    fetchAll(false)
  }

  const handleRerun = async (run: MMRun) => {
    await rerunMMRun(run.id)
    message.success('已重新派发')
    fetchAll(false)
  }

  const handleDeleteDataset = async (dataset: MMDataset) => {
    await deleteMMDataset(dataset.id)
    message.success('已删除评测集')
    fetchAll(false)
  }

  const readyDatasets = useMemo(() => datasets.filter((d) => d.status === 'ready'), [datasets])
  const activeCount = useMemo(() => runs.filter(runIsActive).length, [runs])

  const runColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '评测集 / 模型',
      key: 'refs',
      render: (_: unknown, record: MMRun) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span>{record.dataset_name || record.dataset_id}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {record.model_name || record.model_id}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 190,
      render: (_: unknown, record: MMRun) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {statusTag(record.status)}
          {(record.status === 'running' || record.status === 'pending') && (
            <Progress percent={record.progress} size="small" status="active" />
          )}
          {record.error && (
            <Tooltip title={record.error}>
              <Typography.Text type="danger" ellipsis style={{ maxWidth: 160 }}>
                {record.error}
              </Typography.Text>
            </Tooltip>
          )}
        </div>
      ),
    },
    {
      title: '指标',
      key: 'metrics',
      render: (_: unknown, record: MMRun) => {
        if (!record.metrics || record.metrics.query_count == null) return <Typography.Text type="secondary">-</Typography.Text>
        return (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {METRIC_COLUMNS.map(({ key, label }) => (
              <span key={key} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                {label} {fmtMetric(record.metrics?.[key])}
              </span>
            ))}
          </div>
        )
      },
    },
    {
      title: '查询数',
      dataIndex: 'query_count',
      key: 'query_count',
      width: 90,
      render: (value: number, record: MMRun) => (
        <Tooltip title={`跳过 ${record.skipped_queries} 个候选不足的查询，共编码 ${record.encoded_items} 条图文`}>
          <span>{value}</span>
        </Tooltip>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value?: string) => (value ? formatTime(value) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: MMRun) => (
        <Space size={0} wrap>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openRunDetail(record)}>
            详情
          </Button>
          {(record.status === 'running' || record.status === 'pending') && (
            <Popconfirm
              title="请求取消？"
              description="任务会在当前批次的嵌入请求完成后停止"
              onConfirm={() => handleCancel(record)}
            >
              <Button type="link" size="small" icon={<StopOutlined />}>
                取消
              </Button>
            </Popconfirm>
          )}
          {(record.status === 'failed' || record.status === 'cancelled') && (
            <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => handleRerun(record)}>
              重跑
            </Button>
          )}
          {(record.status === 'running' || record.status === 'pending') && (
            <Popconfirm
              title="强制取消？"
              description="worker 已丢失时使用：直接终结状态，不会真正停止远端调用"
              onConfirm={() => handleForceCancel(record)}
            >
              <Button type="link" size="small" danger>
                强制
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const datasetColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => statusTag(value) },
    { title: '查询数', dataIndex: 'query_count', key: 'query_count', width: 90 },
    { title: '样例行数', dataIndex: 'record_count', key: 'record_count', width: 100 },
    { title: '图片数', dataIndex: 'image_count', key: 'image_count', width: 90 },
    {
      title: '模态分组',
      key: 'subsets',
      render: (_: unknown, record: MMDataset) => {
        const entries = Object.entries(record.subset_stats || {})
        if (!entries.length) return '-'
        return (
          <Space size={4} wrap>
            {entries.slice(0, 6).map(([subset, stat]) => (
              <Tooltip key={subset} title={`${stat.queries} 个查询 / ${stat.candidates} 条候选`}>
                <Tag>{subset}</Tag>
              </Tooltip>
            ))}
            {entries.length > 6 && <Tag>+{entries.length - 6}</Tag>}
          </Space>
        )
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value?: string) => (value ? formatTime(value) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, record: MMDataset) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDatasetDetail(record)}>
            预览
          </Button>
          <Popconfirm
            title="删除评测集？"
            description="同时删除 MinIO 中的图片；已被评测运行引用的会拒绝删除"
            onConfirm={() => handleDeleteDataset(record)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const queryColumns = [
    { title: 'qid', dataIndex: 'qid', key: 'qid', width: 160, ellipsis: true },
    { title: '分组', dataIndex: 'subset', key: 'subset', width: 90, render: (v?: string) => v || '-' },
    {
      title: '首个正例排名',
      dataIndex: 'rank',
      key: 'rank',
      width: 130,
      render: (rank: number | null) => {
        if (rank == null) return <Tag color="error">未命中</Tag>
        if (rank <= 10) return <Tag color="success">#{rank}</Tag>
        return <Tag color="warning">#{rank}</Tag>
      },
    },
    {
      title: '候选 / 正例',
      key: 'candidates',
      width: 110,
      render: (_: unknown, record: MMQueryResult) => `${record.candidate_count} / ${record.positive_count}`,
    },
    {
      title: 'Recall@10 / MRR@10 / nDCG@10',
      key: 'metrics',
      render: (_: unknown, record: MMQueryResult) => (
        <span style={{ fontFamily: 'monospace', fontSize: 12 }}>
          {fmtMetric(record.metrics?.['recall@10'])} / {fmtMetric(record.metrics?.['mrr@10'])} /{' '}
          {fmtMetric(record.metrics?.['ndcg@10'])}
        </span>
      ),
    },
  ]

  const subsetRows = useMemo(
    () =>
      Object.entries(detailRun?.subset_metrics || {}).map(([subset, metrics]) => ({
        key: subset,
        subset,
        ...metrics,
      })),
    [detailRun?.subset_metrics],
  )

  const subsetOptions = useMemo(
    () => Object.keys(detailRun?.subset_metrics || {}).map((subset) => ({ value: subset, label: subset })),
    [detailRun?.subset_metrics],
  )

  const datasetSampleColumns = [
    { title: 'qid', dataIndex: 'qid', key: 'qid', width: 160, ellipsis: true },
    { title: '分组', dataIndex: 'subset', key: 'subset', width: 90, render: (v?: string) => v || '-' },
    {
      title: '标签',
      dataIndex: 'label',
      key: 'label',
      width: 80,
      render: (label: number) => (label ? <Tag color="success">正例</Tag> : <Tag>负例</Tag>),
    },
    {
      title: 'Query',
      key: 'query',
      render: (_: unknown, record: any) => (
        <Space align="start">
          {record.query_image_url && (
            <Image src={record.query_image_url} width={56} height={56} style={{ objectFit: 'cover' }} />
          )}
          <span style={{ maxWidth: 260 }}>{record.query_text || <i>（图片查询）</i>}</span>
        </Space>
      ),
    },
    {
      title: 'Target',
      key: 'target',
      render: (_: unknown, record: any) => (
        <Space align="start">
          {record.target_image_url && (
            <Image src={record.target_image_url} width={56} height={56} style={{ objectFit: 'cover' }} />
          )}
          <span style={{ maxWidth: 260 }}>{record.target_text || <i>（图片目标）</i>}</span>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="多模态嵌入评测"
      extra={
        <Space>
          <Tag color={activeCount ? 'processing' : 'default'}>{activeCount} 个运行中</Tag>
          <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>
            导入评测集
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={showCreate} disabled={!readyDatasets.length}>
            新建评测
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="把 query 与候选图文分别编码后按余弦相似度排序，按分组宏平均统计 Recall@k / MRR@10 / nDCG@10；检索指标不经过 LLM 打分。"
      />
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'runs',
            label: `评测运行 (${runs.length})`,
            children: (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Select
                    allowClear
                    placeholder="按状态过滤"
                    style={{ width: 160 }}
                    value={runStatusFilter}
                    onChange={setRunStatusFilter}
                    options={[
                      { value: 'running', label: '运行中' },
                      { value: 'completed', label: '已完成' },
                      { value: 'failed', label: '失败' },
                      { value: 'cancelled', label: '已取消' },
                    ]}
                  />
                  <Button icon={<ReloadOutlined />} onClick={() => fetchAll()}>
                    刷新
                  </Button>
                </Space>
                <Table
                  dataSource={runStatusFilter ? runs.filter((r) => r.status === runStatusFilter) : runs}
                  columns={runColumns}
                  rowKey="id"
                  loading={loading}
                  locale={{ emptyText: <Empty description="还没有评测运行" /> }}
                />
              </>
            ),
          },
          {
            key: 'datasets',
            label: `评测集 (${datasets.length})`,
            children: (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>
                    导入评测集
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={() => fetchAll()}>
                    刷新
                  </Button>
                </Space>
                <Table
                  dataSource={datasets}
                  columns={datasetColumns}
                  rowKey="id"
                  loading={loading}
                  locale={{ emptyText: <Empty description="还没有评测集，先导入 MMEB 或自定义 jsonl/zip" /> }}
                />
              </>
            ),
          },
        ]}
      />

      <Modal
        title="新建多模态嵌入评测"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={submitCreate}
        confirmLoading={creating}
        width={640}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item name="name" label="名称" extra="留空自动使用「评测集 · 模型」">
            <Input placeholder="例如：EmbeddingGemma 在 MMEB 上的表现" />
          </Form.Item>
          <Form.Item name="dataset_id" label="评测集" rules={[{ required: true }]}>
            <Select
              placeholder="选择已就绪的评测集"
              options={readyDatasets.map((d) => ({
                value: d.id,
                label: `${d.name}（${d.query_count} 查询 / ${d.record_count} 行）`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="model_id"
            label="嵌入模型"
            rules={[{ required: true }]}
            extra="仅 embedding 类型；OpenAI 兼容与 Gemini 原生协议均自动适配"
          >
            <Select
              placeholder="选择模型配置"
              options={embeddingModels.map((m) => ({
                value: m.id,
                label: `${m.name}（${m.model_name}）`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="image_transport"
            label="图片传输"
            extra="data_url 把图片转 base64 内联（无需公网访问）；url 传 MinIO 预签名地址（模型所在服务需能访问）"
          >
            <Select
              options={[
                { value: 'data_url', label: 'data_url（base64 内联）' },
                { value: 'url', label: 'url（预签名地址）' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="request_format"
            label="请求格式"
            extra="content_array 是标准的 OpenAI 多模态输入；messages 供只支持 chat 式 embedding 的兼容服务；text_only 忽略图片"
          >
            <Select
              options={[
                { value: 'content_array', label: 'content_array（标准 OpenAI）' },
                { value: 'messages', label: 'messages（逐条 chat）' },
                { value: 'text_only', label: 'text_only（仅文本）' },
              ]}
            />
          </Form.Item>
          <Space size="large" wrap>
            <Form.Item name="batch_size" label="批大小">
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item name="top_k" label="Top-K">
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item name="timeout" label="超时（秒）">
              <InputNumber min={10} max={1800} placeholder="180" />
            </Form.Item>
            <Form.Item name="max_retries" label="重试次数">
              <InputNumber min={0} max={10} placeholder="2" />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title="导入评测集"
        open={importOpen}
        onCancel={() => {
          setImportOpen(false)
          setImportFile(null)
          importForm.resetFields()
        }}
        onOk={submitImport}
        confirmLoading={importing}
        okText="开始导入"
        width={620}
      >
        <Form form={importForm} layout="vertical">
          <Form.Item name="name" label="评测集名称" rules={[{ required: true }]}>
            <Input placeholder="例如：MMEB-v2 检索子集" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <Form.Item
            name="file"
            label="数据文件"
            valuePropName="fileList"
            getValueFromEvent={normFile}
            rules={[{ required: true, message: '请选择文件' }]}
            extra="MMEB 官方 jsonl（qry_text/qry_image_path/tgt_text/tgt_image_path）、通用 jsonl/json，或包含图片目录的 zip；图片会自动登记到 MinIO"
          >
            <Upload.Dragger
              beforeUpload={(file) => {
                setImportFile(file)
                return false
              }}
              onRemove={() => setImportFile(null)}
              maxCount={1}
              accept=".jsonl,.json,.zip"
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽文件到此区域（≤200MB）</p>
            </Upload.Dragger>
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={detailRun ? `评测详情 · ${detailRun.name}` : '评测详情'}
        width={960}
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false)
          setDetailRun(null)
          setQueryPage(null)
        }}
      >
        {detailRun && (
          <>
            <Descriptions size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="状态">{statusTag(detailRun.status)}</Descriptions.Item>
              <Descriptions.Item label="进度">
                <Progress percent={detailRun.progress} size="small" style={{ width: 160 }} />
              </Descriptions.Item>
              <Descriptions.Item label="评测集">{detailRun.dataset_name || detailRun.dataset_id}</Descriptions.Item>
              <Descriptions.Item label="模型">{detailRun.model_name || detailRun.model_id}</Descriptions.Item>
              <Descriptions.Item label="查询数">
                {detailRun.query_count}（跳过 {detailRun.skipped_queries}）
              </Descriptions.Item>
              <Descriptions.Item label="编码条目">{detailRun.encoded_items}</Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {detailRun.started_at ? formatTime(detailRun.started_at) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {detailRun.completed_at ? formatTime(detailRun.completed_at) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="参数" span={2}>
                <Typography.Text code style={{ fontSize: 12 }}>
                  {JSON.stringify(detailRun.params || {})}
                </Typography.Text>
              </Descriptions.Item>
            </Descriptions>

            {detailRun.error && <Alert type="error" showIcon message={detailRun.error} style={{ marginBottom: 16 }} />}

            <Card size="small" title="总体指标" style={{ marginBottom: 16 }}>
              <Space size={40} wrap>
                {METRIC_COLUMNS.map(({ key, label }) => (
                  <Statistic
                    key={key}
                    title={label}
                    value={detailRun.metrics?.[key] ?? 0}
                    precision={4}
                    valueStyle={{ fontSize: 22 }}
                  />
                ))}
                <Statistic title="查询数" value={detailRun.metrics?.query_count ?? 0} valueStyle={{ fontSize: 22 }} />
              </Space>
            </Card>

            <Card size="small" title="分组指标" style={{ marginBottom: 16 }}>
              <Table
                size="small"
                rowKey="subset"
                pagination={false}
                dataSource={subsetRows}
                locale={{ emptyText: <Empty description="暂无分组汇总（运行完成后生成）" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                columns={[
                  { title: '分组', dataIndex: 'subset', key: 'subset' },
                  { title: '查询数', dataIndex: 'query_count', key: 'query_count', width: 90 },
                  ...METRIC_COLUMNS.map(({ key, label }) => ({
                    title: label,
                    key,
                    width: 110,
                    render: (_: unknown, record: MMMetrics) => fmtMetric(record[key]),
                  })),
                ]}
              />
            </Card>

            <Card
              size="small"
              title="逐条查询"
              extra={
                <Space>
                  <Select
                    allowClear
                    placeholder="全部分组"
                    style={{ width: 140 }}
                    value={queryFilter.subset}
                    onChange={(value) => reloadQueries({ subset: value, page: 1 })}
                    options={subsetOptions}
                  />
                  <Button
                    size="small"
                    type={queryFilter.only_missed ? 'primary' : 'default'}
                    onClick={() => reloadQueries({ only_missed: !queryFilter.only_missed, page: 1 })}
                  >
                    只看漏召
                  </Button>
                </Space>
              }
            >
              <Table
                size="small"
                rowKey="id"
                loading={queryLoading}
                dataSource={queryPage?.items || []}
                columns={queryColumns}
                expandable={{
                  rowExpandable: (record) => !!record.retrieved_top?.length,
                  expandedRowRender: (record) => (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {record.retrieved_top.map((item, index) => (
                        <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Tag color={item.label ? 'success' : 'default'}>{item.label ? '正例' : '负例'}</Tag>
                          <span style={{ width: 32 }}>#{index + 1}</span>
                          <span style={{ fontFamily: 'monospace', width: 64 }}>{item.score.toFixed(4)}</span>
                          {item.image_url && (
                            <Image src={item.image_url} width={44} height={44} style={{ objectFit: 'cover' }} />
                          )}
                          <Typography.Text ellipsis style={{ maxWidth: 560 }}>
                            {item.text || '（图片）'}
                          </Typography.Text>
                        </div>
                      ))}
                    </div>
                  ),
                }}
                pagination={{
                  current: queryPage?.page || 1,
                  pageSize: queryPage?.page_size || 20,
                  total: queryPage?.total || 0,
                  showSizeChanger: true,
                  onChange: (page, pageSize) => reloadQueries({ page, page_size: pageSize }),
                }}
              />
            </Card>
          </>
        )}
      </Drawer>

      <Drawer
        title={datasetDetail ? `评测集预览 · ${datasetDetail.name}` : '评测集预览'}
        width={900}
        open={datasetOpen}
        onClose={() => {
          setDatasetOpen(false)
          setDatasetDetail(null)
        }}
      >
        {datasetLoading && <Card loading />}
        {datasetDetail && (
          <>
            <Descriptions size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="状态">{statusTag(datasetDetail.status)}</Descriptions.Item>
              <Descriptions.Item label="查询数">{datasetDetail.query_count}</Descriptions.Item>
              <Descriptions.Item label="样例行数">{datasetDetail.record_count}</Descriptions.Item>
              <Descriptions.Item label="图片数">{datasetDetail.image_count}</Descriptions.Item>
              <Descriptions.Item label="来源" span={2}>
                <Typography.Text code style={{ fontSize: 12 }}>
                  {JSON.stringify(datasetDetail.source_meta || {})}
                </Typography.Text>
              </Descriptions.Item>
            </Descriptions>
            {datasetDetail.error && (
              <Alert type="error" showIcon message={datasetDetail.error} style={{ marginBottom: 16 }} />
            )}
            <Typography.Paragraph type="secondary">
              仅预览前 {datasetDetail.samples.length} 行；评测时同 qid 的候选会组成候选池。
            </Typography.Paragraph>
            <Table
              size="small"
              rowKey={(record) => `${record.qid}-${record.label}-${record.target_text ?? ''}-${record.target_image_url ?? ''}`}
              dataSource={datasetDetail.samples}
              columns={datasetSampleColumns}
              pagination={false}
              scroll={{ y: 520 }}
            />
          </>
        )}
      </Drawer>
    </Card>
  )
}

export default MultimodalEmbeddings
