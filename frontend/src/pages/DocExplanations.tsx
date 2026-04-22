import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getDocExplanations, createDocExplanation, updateDocExplanation, deleteDocExplanation, getDocuments } from '@/api'
import type { DocExplanation, DocumentInfo } from '@/types'

const DocExplanations: React.FC = () => {
  const [explanations, setExplanations] = useState<DocExplanation[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingExp, setEditingExp] = useState<DocExplanation | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [expData, docData] = await Promise.all([
        getDocExplanations(),
        getDocuments(),
      ])
      setExplanations(expData)
      setDocuments(docData.items || docData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const showCreateModal = () => {
    form.resetFields()
    setModalVisible(true)
  }

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createDocExplanation(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
    } finally {
      setSaving(false)
    }
  }

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
      fetchData()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteDocExplanation(id)
      message.success('删除成功')
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      draft: 'default',
      ready: 'success',
      archived: 'warning',
    }
    return colors[status] || 'default'
  }

  const columns = [
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
      width: 300,
      render: (text: string) => text?.slice(0, 100) + (text?.length > 100 ? '...' : ''),
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      render: (source: string) => <Tag>{source}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusColor(status)}>{status}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, record: DocExplanation) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => showEditModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除?" onConfirm={() => handleDelete(record.id)}>
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
      title="文档解释"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateModal}>
          新建解释
        </Button>
      }
    >
      <Table
        dataSource={explanations}
        columns={columns}
        rowKey="id"
        loading={loading}
      />

      <Modal
        title="新建文档解释"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={handleCreate}
        confirmLoading={saving}
        width={600}
      >
        <Form form={form} labelCol={{ span: 4 }}>
          <Form.Item name="doc_id" label="文档" rules={[{ required: true }]}>
            <Select
              placeholder="选择文档"
              showSearch
              optionFilterProp="label"
              options={documents.map(d => ({ value: d.id, label: d.title || d.id }))}
            />
          </Form.Item>
          <Form.Item name="explanation" label="解释内容" rules={[{ required: true }]}>
            <Input.TextArea rows={6} placeholder="输入文档解释内容" />
          </Form.Item>
          <Form.Item name="source" label="来源">
            <Select
              options={[
                { value: 'manual', label: '手动输入' },
                { value: 'upload', label: '文件上传' },
                { value: 'generated', label: '系统生成' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑文档解释"
        open={editModalVisible}
        onCancel={() => setEditModalVisible(false)}
        onOk={handleEdit}
        confirmLoading={saving}
        width={600}
      >
        <Form form={editForm} labelCol={{ span: 4 }}>
          <Form.Item name="explanation" label="解释内容" rules={[{ required: true }]}>
            <Input.TextArea rows={6} placeholder="输入文档解释内容" />
          </Form.Item>
          <Form.Item name="source" label="来源">
            <Select
              options={[
                { value: 'manual', label: '手动输入' },
                { value: 'upload', label: '文件上传' },
                { value: 'generated', label: '系统生成' },
              ]}
            />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'ready', label: '就绪' },
                { value: 'archived', label: '已归档' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default DocExplanations