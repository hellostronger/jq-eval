import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, message, Popconfirm, Select, Space, Switch } from 'antd'
import { PlusOutlined, EditOutlined, LinkOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getOpenSourceDatasets, createOpenSourceDataset, updateOpenSourceDataset, deleteOpenSourceDataset } from '@/api'
import type { OpenSourceDataset } from '@/types'

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

  const fetchDatasets = async () => {
    setLoading(true)
    try {
      const data = await getOpenSourceDatasets({ page, size })
      setDatasets(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDatasets()
  }, [page, size])

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
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
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

  return (
    <Card
      title="开源数据集"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新建数据集
        </Button>
      }
    >
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
          showTotal: (total) => `共 ${total} 条`,
          onChange: (p, s) => {
            setPage(p)
            setSize(s)
          },
        }}
      />

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
    </Card>
  )
}

export default OpenSourceDatasets