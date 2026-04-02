import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tabs, Tag, Modal, Form, Input, Select, Switch, Slider, InputNumber, message, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getModels, createModel, updateModel, deleteModel, testModel } from '@/api'
import type { ModelConfig, ModelType } from '@/types'

const Models: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ModelType>('llm')
  const [models, setModels] = useState<ModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingModel, setEditingModel] = useState<ModelConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchModels = async () => {
    setLoading(true)
    try {
      const data = await getModels(activeTab)
      setModels(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchModels()
  }, [activeTab])

  const showCreateDialog = () => {
    setEditingModel(null)
    form.resetFields()
    form.setFieldsValue({
      model_type: activeTab,
      provider: 'openai',
      temperature: 0.7,
      max_tokens: 2048,
      dimension: 1536,
      is_default: false,
    })
    setModalVisible(true)
  }

  const editModel = (model: ModelConfig) => {
    setEditingModel(model)
    form.setFieldsValue({
      name: model.name,
      model_type: model.model_type,
      provider: model.provider,
      model_name: model.model_name,
      api_base: model.api_base,
      api_key: model.api_key,
      temperature: model.temperature || 0.7,
      max_tokens: model.max_tokens || 2048,
      dimension: model.dimension || 1536,
      is_default: model.is_default,
    })
    setModalVisible(true)
  }

  const onProviderChange = (provider: string) => {
    const presets: Record<string, { api_base: string }> = {
      openai: { api_base: 'https://api.openai.com/v1' },
      azure: { api_base: '' },
      zhipuai: { api_base: 'https://open.bigmodel.cn/api/paas/v4' },
      baidu: { api_base: '' },
      aliyun: { api_base: '' },
      volcengine: { api_base: '' },
      local: { api_base: 'http://localhost:8000/v1' },
    }
    if (presets[provider]) {
      form.setFieldsValue({ api_base: presets[provider].api_base })
    }
  }

  const saveModel = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingModel) {
        await updateModel(editingModel.id, values)
        message.success('更新成功')
      } else {
        await createModel(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      fetchModels()
    } catch (e) {
      // 验证错误已在拦截器处理
    } finally {
      setSaving(false)
    }
  }

  const handleTestModel = async (model: ModelConfig) => {
    try {
      const result = await testModel(model.id)
      if (result.success) {
        message.success('测试成功')
      } else {
        message.error(result.error || '测试失败')
      }
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDeleteModel = async (model: ModelConfig) => {
    try {
      await deleteModel(model.id)
      message.success('删除成功')
      fetchModels()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '提供商', dataIndex: 'provider', key: 'provider' },
    { title: '模型名称', dataIndex: 'model_name', key: 'model_name' },
    { title: 'API地址', dataIndex: 'api_base', key: 'api_base' },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      render: (v: boolean) => v ? <Tag color="success">默认</Tag> : null,
    },
    {
      title: 'Temperature',
      dataIndex: 'temperature',
      key: 'temperature',
      render: (v: number) => v || '-',
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
      render: (_: unknown, record: ModelConfig) => (
        <>
          <Button type="link" size="small" onClick={() => handleTestModel(record)}>
            测试
          </Button>
          <Button type="link" size="small" onClick={() => editModel(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此模型配置?" onConfirm={() => handleDeleteModel(record)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </>
      ),
    },
  ]

  const tabItems = [
    { key: 'llm', label: 'LLM' },
    { key: 'embedding', label: 'Embedding' },
    { key: 'reranker', label: 'Reranker' },
  ]

  return (
    <Card
      title="模型配置"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新增配置
        </Button>
      }
    >
      <Tabs items={tabItems} activeKey={activeTab} onChange={(key) => setActiveTab(key as ModelType)} />

      <Table dataSource={models} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title={editingModel ? '编辑模型配置' : '新增模型配置'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveModel}
        confirmLoading={saving}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="模型配置名称" />
          </Form.Item>
          <Form.Item name="model_type" label="模型类型">
            <Select disabled options={[
              { value: 'llm', label: 'LLM' },
              { value: 'embedding', label: 'Embedding' },
              { value: 'reranker', label: 'Reranker' },
            ]} />
          </Form.Item>
          <Form.Item name="provider" label="提供商">
            <Select onChange={onProviderChange} options={[
              { value: 'openai', label: 'OpenAI' },
              { value: 'azure', label: 'Azure OpenAI' },
              { value: 'zhipuai', label: '智谱AI' },
              { value: 'baidu', label: '百度千帆' },
              { value: 'aliyun', label: '阿里云百炼' },
              { value: 'volcengine', label: '火山引擎' },
              { value: 'local', label: '本地部署' },
            ]} />
          </Form.Item>
          <Form.Item name="model_name" label="模型名称" rules={[{ required: true }]}>
            <Input placeholder="如 gpt-4, text-embedding-ada-002" />
          </Form.Item>
          <Form.Item name="api_base" label="API地址" rules={[{ required: true }]}>
            <Input placeholder="API Base URL" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
            <Input.Password placeholder="API Key" />
          </Form.Item>
          <Form.Item shouldUpdate={(prev, curr) => prev.model_type !== curr.model_type}>
            {({ getFieldValue }) => {
              const modelType = getFieldValue('model_type')
              if (modelType === 'llm') {
                return (
                  <>
                    <Form.Item name="temperature" label="Temperature">
                      <Slider min={0} max={2} step={0.1} />
                    </Form.Item>
                    <Form.Item name="max_tokens" label="Max Tokens">
                      <InputNumber min={100} max={32000} />
                    </Form.Item>
                  </>
                )
              }
              if (modelType === 'embedding') {
                return (
                  <Form.Item name="dimension" label="向量维度">
                    <InputNumber min={256} max={4096} />
                  </Form.Item>
                )
              }
              return null
            }}
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Models