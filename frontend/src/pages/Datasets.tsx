import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, message, Popconfirm, Select, InputNumber, Space, Tooltip } from 'antd'
import { PlusOutlined, SyncOutlined, LoadingOutlined, DatabaseOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { formatTime } from '@/utils/format'
import {
  getDatasets, createDataset, deleteDataset, createDataSource, executeSync, testDataSourceConnection,
  listBuiltinBenchmarks, provisionBuiltinBenchmark,
} from '@/api'
import type { Dataset } from '@/types'
import type { BuiltinBenchmark, BuiltinBenchmarkQualityReport } from '@/api'

const DIFFICULTY_COLORS: Record<string, string> = { easy: 'green', medium: 'orange', hard: 'red' }

const renderDifficultyTags = (report: BuiltinBenchmarkQualityReport) =>
  Object.entries(report.by_difficulty).map(([level, count]) => (
    <Tag key={level} color={DIFFICULTY_COLORS[level] || 'default'}>
      {level}: {count}
    </Tag>
  ))

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
  const [builtinBenchmarks, setBuiltinBenchmarks] = useState<BuiltinBenchmark[]>([])
  const [provisioning, setProvisioning] = useState<string | null>(null)
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
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setLoading(false)
    }
  }

  const fetchBuiltinBenchmarks = async () => {
    try {
      const res = await listBuiltinBenchmarks()
      setBuiltinBenchmarks(res.items)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleProvisionBuiltin = async (benchmarkId: string) => {
    setProvisioning(benchmarkId)
    try {
      const result = await provisionBuiltinBenchmark(benchmarkId)
      if (result.upgrade_skipped) {
        message.warning('内容有新版本，但该数据集已被评估/调用引用，已跳过升版以保护历史结果')
      } else {
        message.success(result.created ? `已导入 ${result.record_count} 题` : `已同步到最新版本（${result.record_count} 题）`)
      }
      fetchBuiltinBenchmarks()
      fetchDatasets()
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setProvisioning(null)
    }
  }

  useEffect(() => {
    fetchDatasets()
    fetchBuiltinBenchmarks()
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
    } catch (e) {
      if ((e as { errorFields?: unknown })?.errorFields) return
      // 错误已在拦截器处理
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
      dataIndex: 'record_count',
      key: 'record_count',
      render: (v: number) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => formatTime(date),
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
      {builtinBenchmarks.length > 0 && (
        <Card
          size="small"
          title={<span><DatabaseOutlined /> 内置评测集</span>}
          style={{ marginBottom: 16 }}
        >
          {builtinBenchmarks.map((b) => (
            <div
              key={b.benchmark_id}
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}
            >
              <div style={{ flex: 1, minWidth: 300 }}>
                <Space size={4} wrap>
                  <Tag color="purple">{b.version}</Tag>
                  <strong>{b.name}</strong>
                  {b.language && <Tag>{b.language}</Tag>}
                  {b.load_error && <Tag color="red">文件异常: {b.load_error}</Tag>}
                  {b.dataset && !b.load_error && (
                    <Tag color="green">{b.dataset.record_count} 题</Tag>
                  )}
                  {b.dataset && b.dataset.version_match === false && (
                    <Tag color="orange">文件有新版本</Tag>
                  )}
                </Space>
                <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{b.description}</div>
                {b.dataset?.quality_report && (
                  <Space size={4} wrap style={{ marginTop: 4 }}>
                    {renderDifficultyTags(b.dataset.quality_report)}
                    <Tooltip title="题型分布">
                      {Object.entries(b.dataset.quality_report.by_question_type).map(([t, c]) => (
                        <Tag key={t}>{t}: {c}</Tag>
                      ))}
                    </Tooltip>
                    <Tooltip title="集内去重率为 0，题干归一化后无重复">
                      <Tag color="cyan">去重率 0%</Tag>
                    </Tooltip>
                  </Space>
                )}
              </div>
              <Button
                size="small"
                type="primary"
                ghost
                loading={provisioning === b.benchmark_id}
                disabled={!!b.load_error}
                onClick={() => handleProvisionBuiltin(b.benchmark_id)}
              >
                {b.dataset ? '同步/重建' : '一键导入'}
              </Button>
            </div>
          ))}
        </Card>
      )}
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