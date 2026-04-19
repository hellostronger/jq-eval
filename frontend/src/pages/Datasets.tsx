import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, message, Popconfirm, Select, InputNumber, Space } from 'antd'
import { PlusOutlined, SyncOutlined, LoadingOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getDatasets, createDataset, deleteDataset, createDataSource, executeSync, testDataSourceConnection } from '@/api'
import type { Dataset } from '@/types'

const Datasets: React.FC = () => {
  const navigate = useNavigate()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [syncModalVisible, setSyncModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [form] = Form.useForm()
  const [syncForm] = Form.useForm()

  const RAG_TYPES = [
    { value: 'dify', label: 'Dify' },
    { value: 'coze', label: 'Coze' },
    { value: 'fastgpt', label: 'FastGPT' },
    { value: 'lightrag', label: 'LightRAG' },
  ]

  const DB_TYPES = [
    { value: 'postgresql', label: 'PostgreSQL' },
    { value: 'mongodb', label: 'MongoDB' },
    { value: 'mysql', label: 'MySQL' },
    { value: 'sqlite', label: 'SQLite' },
  ]

  const fetchDatasets = async () => {
    setLoading(true)
    try {
      const data = await getDatasets()
      setDatasets(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDatasets()
  }, [])

  const showCreateDialog = () => {
    form.resetFields()
    setModalVisible(true)
  }

  const showSyncDialog = () => {
    syncForm.resetFields()
    setTestResult(null)
    setSyncModalVisible(true)
  }

  const testConnection = async () => {
    try {
      const values = await syncForm.validateFields(['db_type', 'db_url', 'password'])
      setTesting(true)
      setTestResult(null)
      // 创建临时数据源用于测试连接
      const dataSource = await createDataSource({
        name: `temp_test_${Date.now()}`,
        source_type: 'database',
        system_type: values.rag_type || 'custom',
        connection_config: {
          db_type: values.db_type,
          db_url: values.db_url,
          password: values.password,
        },
      })
      // 测试连接
      const result = await testDataSourceConnection(dataSource.id)
      setTestResult({ success: result.success, message: result.message || '连接成功' })
      if (result.success) {
        message.success('数据库连接成功')
      } else {
        message.error('数据库连接失败')
      }
    } catch (e) {
      setTestResult({ success: false, message: '连接测试失败' })
    } finally {
      setTesting(false)
    }
  }

  const saveDataset = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createDataset(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchDatasets()
    } finally {
      setSaving(false)
    }
  }

  const syncDataset = async () => {
    try {
      const values = await syncForm.validateFields()
      setSyncing(true)
      // 创建数据源
      const dataSource = await createDataSource({
        name: `${values.rag_type}_${values.version}_source`,
        source_type: 'database',
        system_type: values.rag_type,
        connection_config: {
          db_type: values.db_type,
          db_url: values.db_url,
          password: values.password,
          version: values.version,
        },
      })
      // 创建目标数据集
      const dataset = await createDataset({
        name: `${values.rag_type}_${values.version}_dataset`,
        description: `从 ${values.rag_type} v${values.version} 同步的数据集`,
      })
      // 执行同步
      await executeSync(dataSource.id, {
        dataset_id: dataset.id,
        tables: [],
        mappings: {},
      })
      message.success('同步任务已创建')
      setSyncModalVisible(false)
      fetchDatasets()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setSyncing(false)
    }
  }

  const handleDeleteDataset = async (dataset: Dataset) => {
    try {
      await deleteDataset(dataset.id)
      message.success('删除成功')
      fetchDatasets()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description' },
    {
      title: '记录数',
      dataIndex: 'total_records',
      key: 'total_records',
      render: (v: number) => <Tag color="blue">{v}</Tag>,
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
      render: (_: unknown, record: Dataset) => (
        <>
          <Button type="link" size="small" onClick={() => navigate(`/datasets/${record.id}`)}>
            查看
          </Button>
          <Popconfirm title="确定删除此数据集?" onConfirm={() => handleDeleteDataset(record)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </>
      ),
    },
  ]

  return (
    <Card
      title="数据集"
      extra={
        <>
          <Button icon={<SyncOutlined />} onClick={showSyncDialog} style={{ marginRight: 8 }}>
            拉取数据库
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
            新建数据集
          </Button>
        </>
      }
    >
      <Table dataSource={datasets} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title="新建数据集"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveDataset}
        confirmLoading={saving}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="数据集名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="数据集描述" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="从RAG系统同步数据集"
        open={syncModalVisible}
        onCancel={() => setSyncModalVisible(false)}
        onOk={syncDataset}
        confirmLoading={syncing}
        width={500}
      >
        <Form form={syncForm} labelCol={{ span: 6 }} layout="horizontal">
          <Form.Item name="rag_type" label="RAG类型" rules={[{ required: true, message: '请选择RAG类型' }]}>
            <Select placeholder="选择RAG系统类型" options={RAG_TYPES} />
          </Form.Item>
          <Form.Item name="version" label="版本号" rules={[{ required: true, message: '请输入版本号' }]}>
            <InputNumber placeholder="如: 1.0" style={{ width: '100%' }} min={0} step={0.1} />
          </Form.Item>
          <Form.Item name="db_type" label="数据库类型" rules={[{ required: true, message: '请选择数据库类型' }]}>
            <Select placeholder="选择数据库类型" options={DB_TYPES} />
          </Form.Item>
          <Form.Item name="db_url" label="数据库URL" rules={[{ required: true, message: '请输入数据库连接URL' }]}>
            <Input placeholder="如: postgresql://host:5432/db" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="数据库密码" />
          </Form.Item>
          <Form.Item label="连接测试">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button
                icon={testing ? <LoadingOutlined /> : null}
                onClick={testConnection}
                disabled={testing}
              >
                {testing ? '探测中...' : '探测连接'}
              </Button>
              {testResult && (
                <Tag color={testResult.success ? 'green' : 'red'}>
                  {testResult.message}
                </Tag>
              )}
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Datasets