import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, message, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getDataSources, createDataSource, testDataSourceConnection, deleteDataSource } from '@/api'
import type { DataSource } from '@/types'

const DataSources: React.FC = () => {
  const [dataSources, setDataSources] = useState<DataSource[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchDataSources = async () => {
    setLoading(true)
    try {
      const data = await getDataSources()
      setDataSources(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDataSources()
  }, [])

  const showCreateDialog = () => {
    form.resetFields()
    form.setFieldsValue({
      system_type: 'dify',
    })
    setModalVisible(true)
  }

  const saveDataSource = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createDataSource(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchDataSources()
    } finally {
      setSaving(false)
    }
  }

  const handleTestConnection = async (dataSource: DataSource) => {
    try {
      await testDataSourceConnection(dataSource.id)
      message.success('连接测试成功')
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDeleteDataSource = async (dataSource: DataSource) => {
    try {
      await deleteDataSource(dataSource.id)
      message.success('删除成功')
      fetchDataSources()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型',
      dataIndex: 'system_type',
      key: 'system_type',
      render: (type: string) => <Tag color="blue">{type.toUpperCase()}</Tag>,
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
      render: (_: unknown, record: DataSource) => (
        <>
          <Button type="link" size="small" onClick={() => handleTestConnection(record)}>
            测试连接
          </Button>
          <Popconfirm title="确定删除此数据源?" onConfirm={() => handleDeleteDataSource(record)}>
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
      title="数据源"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新增数据源
        </Button>
      }
    >
      <Table dataSource={dataSources} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title="新增数据源"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveDataSource}
        confirmLoading={saving}
        width={600}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="数据源名称" />
          </Form.Item>
          <Form.Item name="system_type" label="系统类型" rules={[{ required: true }]}>
            <Select options={systemTypes} />
          </Form.Item>
          <Form.Item name={['connection_config', 'api_endpoint']} label="API地址" rules={[{ required: true }]}>
            <Input placeholder="API Endpoint URL" />
          </Form.Item>
          <Form.Item name={['connection_config', 'api_key']} label="API Key" rules={[{ required: true }]}>
            <Input.Password placeholder="API Key" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default DataSources