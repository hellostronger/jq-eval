import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, Switch, message, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getRAGSystems, createRAGSystem, updateRAGSystem, deleteRAGSystem, testRAGSystem } from '@/api'
import type { RAGSystem } from '@/types'

const RAGSystems: React.FC = () => {
  const [systems, setSystems] = useState<RAGSystem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSystem, setEditingSystem] = useState<RAGSystem | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchSystems = async () => {
    setLoading(true)
    try {
      const data = await getRAGSystems()
      setSystems(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSystems()
  }, [])

  const showCreateDialog = () => {
    setEditingSystem(null)
    form.resetFields()
    form.setFieldsValue({
      system_type: 'dify',
      is_active: true,
    })
    setModalVisible(true)
  }

  const editSystem = (system: RAGSystem) => {
    setEditingSystem(system)
    form.setFieldsValue({
      name: system.name,
      display_name: system.display_name,
      system_type: system.system_type,
      api_endpoint: system.api_endpoint,
      api_key: system.api_key,
      is_active: system.is_active,
    })
    setModalVisible(true)
  }

  const saveSystem = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingSystem) {
        await updateRAGSystem(editingSystem.id, values)
        message.success('更新成功')
      } else {
        await createRAGSystem(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      fetchSystems()
    } finally {
      setSaving(false)
    }
  }

  const handleTestSystem = async (system: RAGSystem) => {
    try {
      await testRAGSystem(system.id)
      message.success('连接测试成功')
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDeleteSystem = async (system: RAGSystem) => {
    try {
      await deleteRAGSystem(system.id)
      message.success('删除成功')
      fetchSystems()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '类型',
      dataIndex: 'system_type',
      key: 'system_type',
      render: (type: string) => <Tag color="blue">{type.toUpperCase()}</Tag>,
    },
    { title: 'API地址', dataIndex: 'api_endpoint', key: 'api_endpoint' },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '禁用'}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => dayjs(date).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: RAGSystem) => (
        <>
          <Button type="link" size="small" onClick={() => handleTestSystem(record)}>
            测试连接
          </Button>
          <Button type="link" size="small" onClick={() => editSystem(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此RAG系统?" onConfirm={() => handleDeleteSystem(record)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </>
      ),
    },
  ]

  const systemTypes = [
    { value: 'dify', label: 'Dify' },
    { value: 'coze', label: 'Coze' },
    { value: 'fastgpt', label: 'FastGPT' },
    { value: 'n8n', label: 'n8n' },
    { value: 'custom', label: '自定义' },
  ]

  return (
    <Card
      title="RAG系统"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新增系统
        </Button>
      }
    >
      <Table dataSource={systems} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title={editingSystem ? '编辑RAG系统' : '新增RAG系统'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveSystem}
        confirmLoading={saving}
        width={600}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="系统标识名称" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="展示名称" />
          </Form.Item>
          <Form.Item name="system_type" label="系统类型" rules={[{ required: true }]}>
            <Select options={systemTypes} />
          </Form.Item>
          <Form.Item name="api_endpoint" label="API地址" rules={[{ required: true }]}>
            <Input placeholder="API Endpoint URL" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
            <Input.Password placeholder="API Key" />
          </Form.Item>
          <Form.Item name="is_active" label="启用状态" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default RAGSystems