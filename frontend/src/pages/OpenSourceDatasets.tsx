import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, message, Popconfirm, Select, Space, Switch, Row, Col, Statistic, Divider, InputNumber } from 'antd'
import { PlusOutlined, EditOutlined, LinkOutlined, DeleteOutlined, SearchOutlined, ReloadOutlined, CloudDownloadOutlined, DownloadOutlined } from '@ant-design/icons'
import { formatTime } from '@/utils/format'
import { getOpenSourceDatasets, createOpenSourceDataset, updateOpenSourceDataset, deleteOpenSourceDataset, searchHFDatasets, importHFDataset } from '@/api'
import type { OpenSourceDataset } from '@/types'
import type { HFDatasetSearchResult } from '@/api'

const OpenSourceDatasets: React.FC = () => {
  const [datasets, setDatasets] = useState<OpenSourceDataset[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(10)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editingDataset, setEditingDataset] = useState<OpenSourceDataset | null>(null)
  const [form] = Form.useForm()

  // 本地搜索和筛选
  const [searchText, setSearchText] = useState('')
  const [filterType, setFilterType] = useState<string | undefined>()
  const [filterLanguage, setFilterLanguage] = useState<string | undefined>()
  const [filterStatus, setFilterStatus] = useState<string | undefined>()

  // HuggingFace 搜索
  const [hfSearchVisible, setHfSearchVisible] = useState(false)
  const [hfSearchQuery, setHfSearchQuery] = useState('')
  const [hfSearchLoading, setHfSearchLoading] = useState(false)
  const [hfSearchResults, setHfSearchResults] = useState<HFDatasetSearchResult[]>([])
  const [hfSearchTotal, setHfSearchTotal] = useState(0)
  const [hfImporting, setHfImporting] = useState<string | null>(null)

  const DATASET_TYPES = [
    { value: 'text', label: '文本' },
    { value: 'image', label: '图像' },
    { value: 'audio', label: '音频' },
    { value: 'video', label: '视频' },
    { value: 'multimodal', label: '多模态' },
    { value: 'qa', label: '问答' },
    { value: 'code', label: '代码' },
  ]

  const LANGUAGES = [
    { value: 'zh', label: '中文' },
    { value: 'en', label: '英文' },
    { value: 'ja', label: '日语' },
    { value: 'ko', label: '韩语' },
    { value: 'multi', label: '多语言' },
  ]

  // 竞态保护：快速翻页/切筛选时慢的旧响应不得覆盖新结果
  const seqRef = React.useRef(0)

  const fetchDatasets = async () => {
    const seq = ++seqRef.current
    setLoading(true)
    try {
      const data = await getOpenSourceDatasets({
        page,
        size,
        search: searchText || undefined,
        dataset_type: filterType,
        language: filterLanguage,
        status: filterStatus,
      })
      if (seq !== seqRef.current) return
      setDatasets(data.items)
      setTotal(data.total)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    fetchDatasets()
  }, [page, size, searchText, filterType, filterLanguage, filterStatus])

  // 筛选/搜索变化时回到第一页，避免停留在不存在的页号上显示空表
  const resetPage = () => setPage(1)

  // HuggingFace 搜索
  const handleHfSearch = async () => {
    if (!hfSearchQuery.trim()) {
      message.warning('请输入搜索关键词')
      return
    }
    setHfSearchLoading(true)
    try {
      const data = await searchHFDatasets({ query: hfSearchQuery, limit: 20 })
      setHfSearchResults(data.items)
      setHfSearchTotal(data.total)
    } catch (e) {
      // 错误已处理
    } finally {
      setHfSearchLoading(false)
    }
  }

  // 从 HuggingFace 导入
  const handleHfImport = async (hfDatasetId: string) => {
    setHfImporting(hfDatasetId)
    try {
      await importHFDataset(hfDatasetId)
      message.success(`数据集 ${hfDatasetId} 导入成功`)
      fetchDatasets()
    } catch (e) {
      // 错误已处理
    } finally {
      setHfImporting(null)
    }
  }

  const showCreateDialog = () => {
    form.resetFields()
    setEditingDataset(null)
    setModalVisible(true)
  }

  const showEditDialog = (dataset: OpenSourceDataset) => {
    form.setFieldsValue({
      name: dataset.name,
      url: dataset.url,
      description: dataset.description,
      dataset_type: dataset.dataset_type,
      size_info: dataset.size_info,
      language: dataset.language,
      is_public: dataset.is_public,
      tags: dataset.tags,
      status: dataset.status,
    })
    setEditingDataset(dataset)
    setModalVisible(true)
  }

  const saveDataset = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingDataset) {
        await updateOpenSourceDataset(editingDataset.id, values)
        message.success('更新成功')
      } else {
        await createOpenSourceDataset(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      fetchDatasets()
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteDataset = async (dataset: OpenSourceDataset) => {
    try {
      await deleteOpenSourceDataset(dataset.id)
      message.success('删除成功')
      fetchDatasets()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      width: 250,
      render: (url: string) => (
        <a href={url} target="_blank" rel="noopener noreferrer">
          <LinkOutlined /> {url.length > 40 ? url.slice(0, 40) + '...' : url}
        </a>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: 200,
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'dataset_type',
      key: 'dataset_type',
      render: (type: string) => type ? <Tag color="blue">{type}</Tag> : '-',
    },
    {
      title: '语言',
      dataIndex: 'language',
      key: 'language',
      render: (lang: string) => lang ? <Tag>{lang}</Tag> : '-',
    },
    {
      title: '规模',
      dataIndex: 'size_info',
      key: 'size_info',
      width: 100,
    },
    {
      title: '公开',
      dataIndex: 'is_public',
      key: 'is_public',
      render: (isPublic: boolean) => (
        <Tag color={isPublic ? 'green' : 'orange'}>
          {isPublic ? '公开' : '私有'}
        </Tag>
      ),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (tags: string[]) => tags?.length > 0 ? (
        <Space size="small">
          {tags.slice(0, 3).map(tag => <Tag key={tag}>{tag}</Tag>)}
          {tags.length > 3 && <Tag>+{tags.length - 3}</Tag>}
        </Space>
      ) : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={status === 'active' ? 'green' : 'default'}>
          {status === 'active' ? '活跃' : '归档'}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (date: string) => formatTime(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: OpenSourceDataset) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => showEditDialog(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此开源数据集?" onConfirm={() => handleDeleteDataset(record)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // HuggingFace 搜索结果列配置
  // 各列宽度之和必须放得进弹窗（见下面 Modal 的 width）：
  // 之前「描述」没给宽度，在 tableLayout:fixed 下被压到 60px，
  // 九列合计 1000px 挤在 852px 的弹窗里，最右侧「规模」「操作」被裁掉，
  // 导入按钮点不到。
  const hfColumns = [
    {
      title: '数据集',
      dataIndex: 'id',
      key: 'id',
      width: 180,
      render: (id: string, record: HFDatasetSearchResult) => (
        <a href={record.url} target="_blank" rel="noopener noreferrer">
          <LinkOutlined /> {id}
        </a>
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 140,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      width: 180,
    },
    {
      title: '下载量',
      dataIndex: 'downloads',
      key: 'downloads',
      width: 90,
      render: (downloads: number) => downloads?.toLocaleString() || 0,
    },
    {
      title: '点赞',
      dataIndex: 'likes',
      key: 'likes',
      width: 70,
    },
    {
      title: '语言',
      dataIndex: 'language',
      key: 'language',
      width: 70,
      render: (lang: string) => lang ? <Tag>{lang}</Tag> : '-',
    },
    {
      title: '任务',
      dataIndex: 'task_categories',
      key: 'task_categories',
      width: 140,
      render: (cats: string[]) => cats?.length > 0 ? (
        <Space size="small">
          {cats.slice(0, 2).map(cat => <Tag key={cat} color="blue">{cat}</Tag>)}
        </Space>
      ) : '-',
    },
    {
      title: '规模',
      dataIndex: 'size_info',
      key: 'size_info',
      width: 80,
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, record: HFDatasetSearchResult) => (
        <Button
          type="primary"
          size="small"
          icon={<DownloadOutlined />}
          loading={hfImporting === record.id}
          onClick={() => handleHfImport(record.id)}
        >
          导入
        </Button>
      ),
    },
  ]

  return (
    <Card
      title="开源数据集"
      extra={
        <Space>
          <Button icon={<CloudDownloadOutlined />} onClick={() => setHfSearchVisible(true)}>
            HF搜索
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
            新建数据集
          </Button>
        </Space>
      }
    >
      {/* 本地搜索筛选 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Input.Search
            placeholder="搜索名称/描述"
            allowClear
            enterButton={<SearchOutlined />}
            onSearch={(v) => { resetPage(); setSearchText(v) }}
            onChange={(e) => { resetPage(); setSearchText(e.target.value) }}
          />
        </Col>
        <Col span={4}>
          <Select
            placeholder="筛选类型"
            allowClear
            options={DATASET_TYPES}
            value={filterType}
            onChange={(v) => { resetPage(); setFilterType(v) }}
          />
        </Col>
        <Col span={4}>
          <Select
            placeholder="筛选语言"
            allowClear
            options={LANGUAGES}
            value={filterLanguage}
            onChange={(v) => { resetPage(); setFilterLanguage(v) }}
          />
        </Col>
        <Col span={4}>
          <Select
            placeholder="筛选状态"
            allowClear
            options={[
              { value: 'active', label: '活跃' },
              { value: 'archived', label: '归档' },
            ]}
            value={filterStatus}
            onChange={(v) => { resetPage(); setFilterStatus(v) }}
          />
        </Col>
        <Col span={4}>
          <Button icon={<ReloadOutlined />} onClick={fetchDatasets}>
            刷新
          </Button>
        </Col>
      </Row>

      <Table
        dataSource={datasets}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: size,
          total: total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, s) => {
            // pageSize 变化时重置到第 1 页
            setPage(s !== size ? 1 : p)
            setSize(s)
          },
        }}
      />

      {/* 本地创建/编辑模态框 */}
      <Modal
        title={editingDataset ? '编辑开源数据集' : '新建开源数据集'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveDataset}
        confirmLoading={saving}
        width={600}
      >
        <Form form={form} labelCol={{ span: 6 }} wrapperCol={{ span: 18 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入数据集名称' }]}>
            <Input placeholder="数据集名称" />
          </Form.Item>
          <Form.Item name="url" label="URL" rules={[{ required: true, message: '请输入数据集链接' }]}>
            <Input placeholder="数据集链接地址" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="数据集描述信息" rows={3} />
          </Form.Item>
          <Form.Item name="dataset_type" label="类型">
            <Select placeholder="选择数据集类型" options={DATASET_TYPES} allowClear />
          </Form.Item>
          <Form.Item name="size_info" label="规模">
            <Input placeholder="如: 100万条、10GB" />
          </Form.Item>
          <Form.Item name="language" label="语言">
            <Select placeholder="选择语言" options={LANGUAGES} allowClear />
          </Form.Item>
          <Form.Item name="is_public" label="是否公开" valuePropName="checked">
            <Switch checkedChildren="公开" unCheckedChildren="私有" />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="输入标签" />
          </Form.Item>
          {editingDataset && (
            <Form.Item name="status" label="状态">
              <Select placeholder="选择状态" options={[
                { value: 'active', label: '活跃' },
                { value: 'archived', label: '归档' },
              ]} />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* HuggingFace 搜索模态框 */}
      <Modal
        title="从 HuggingFace Hub 搜索数据集"
        open={hfSearchVisible}
        onCancel={() => setHfSearchVisible(false)}
        footer={null}
        // 1150：容得下 hfColumns 各列宽度之和（约 1040）并留出内边距，
        // 否则表格横向溢出，最右侧的「导入」按钮被裁掉
        width={1150}
      >
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Input.Search
              placeholder="搜索 HuggingFace 数据集（如：squad, instruct, chat）"
              value={hfSearchQuery}
              onChange={(e) => setHfSearchQuery(e.target.value)}
              onSearch={handleHfSearch}
              enterButton={<SearchOutlined />}
              loading={hfSearchLoading}
            />
          </Col>
          <Col span={12}>
            <Space>
              <Select
                placeholder="语言筛选"
                allowClear
                style={{ width: 120 }}
                options={LANGUAGES}
              />
              <InputNumber placeholder="结果数" min={5} max={50} defaultValue={20} />
            </Space>
          </Col>
        </Row>

        <Divider />

        {hfSearchTotal > 0 && (
          <Row style={{ marginBottom: 16 }}>
            <Col>
              <Statistic title="搜索结果" value={hfSearchTotal} suffix="个数据集" />
            </Col>
          </Row>
        )}

        <Table
          dataSource={hfSearchResults}
          columns={hfColumns}
          rowKey="id"
          loading={hfSearchLoading}
          pagination={false}
          scroll={{ x: 'max-content' }}
        />

        {hfSearchResults.length === 0 && !hfSearchLoading && (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            输入关键词搜索 HuggingFace 上的开源数据集，点击导入添加到本地数据库
          </div>
        )}
      </Modal>
    </Card>
  )
}

export default OpenSourceDatasets