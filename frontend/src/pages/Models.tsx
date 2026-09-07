import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tabs, Tag, Modal, Form, Input, Select, Switch, Slider, InputNumber, message, Popconfirm, Alert } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { getModels, createModel, updateModel, deleteModel, testModel } from '@/api'
import type { ModelConfig, ModelType } from '@/types'

const { TextArea } = Input

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
    const defaults: Record<string, Record<string, unknown>> = {
      doc_parser: {
        model_type: 'doc_parser',
        provider: 'mineru',
        endpoint: 'http://localhost:8888',
        output_format: 'markdown',
        language: 'ch',
        backend_url: 'pipeline',
        is_default: false,
        save_logs: false,
      },
    }
    form.setFieldsValue(defaults[activeTab] || {
      model_type: activeTab,
      provider: 'openai',
      temperature: 0.7,
      max_tokens: 2048,
      dimension: 1536,
      is_vlm: false,
      extra_params_text: '',
      is_default: false,
      save_logs: false,
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
      endpoint: model.endpoint,
      // API key 显示掩码值作为 placeholder，实际值为空（不修改则保留原值）
      api_key: '',
      temperature: model.params?.temperature || 0.7,
      max_tokens: model.params?.max_tokens || 2048,
      dimension: model.dimension || 1536,
      max_input_length: model.max_input_length,
      output_format: model.params?.output_format || 'markdown',
      language: model.params?.language || 'ch',
      backend_url: model.params?.backend_url || 'pipeline',
      is_vlm: model.is_vlm || false,
      extra_params_text: model.params?.extra_params ? JSON.stringify(model.params.extra_params, null, 2) : '',
      is_default: model.is_default,
      save_logs: model.save_logs || false,
    })
    setModalVisible(true)
  }

  const onProviderChange = (provider: string) => {
    const modelType = form.getFieldValue('model_type')
    if (modelType === 'doc_parser') {
      const parserPresets: Record<string, { endpoint: string }> = {
        mineru: { endpoint: 'http://localhost:8888' },
        mineru_api: { endpoint: 'https://mineru.net' },
        custom: { endpoint: '' },
      }
      if (parserPresets[provider]) {
        form.setFieldsValue({ endpoint: parserPresets[provider].endpoint })
      }
      return
    }
    const presets: Record<string, { endpoint: string }> = {
      openai: { endpoint: 'https://api.openai.com/v1' },
      azure: { endpoint: '' },
      zhipuai: { endpoint: 'https://open.bigmodel.cn/api/paas/v4' },
      baidu: { endpoint: '' },
      aliyun: { endpoint: '' },
      volcengine: { endpoint: '' },
      local: { endpoint: 'http://localhost:8000/v1' },
    }
    if (presets[provider]) {
      form.setFieldsValue({ endpoint: presets[provider].endpoint })
    }
  }

  const saveModel = async () => {
    try {
      const values = await form.validateFields()
      // 解析额外请求参数 JSON
      let extraParams: Record<string, unknown> | undefined
      const extraText = (values.extra_params_text || '').trim()
      if (extraText) {
        try {
          extraParams = JSON.parse(extraText)
        } catch {
          message.error('额外请求参数不是合法的 JSON')
          return
        }
        if (typeof extraParams !== 'object' || Array.isArray(extraParams) || extraParams === null) {
          message.error('额外请求参数必须是 JSON 对象，如 {"thinking": {"type": "disabled"}}')
          return
        }
      }
      setSaving(true)
      const payload: Record<string, unknown> = {
        name: values.name,
        model_type: values.model_type,
        provider: values.provider,
        model_name: values.model_name,
        endpoint: values.endpoint,
        api_key: values.api_key,
        temperature: values.temperature,
        max_tokens: values.max_tokens,
        dimension: values.dimension,
        max_input_length: values.max_input_length,
        is_vlm: values.is_vlm || false,
        extra_params: extraParams,
        is_default: values.is_default,
        save_logs: values.save_logs,
      }
      if (values.model_type === 'doc_parser') {
        payload.parse_config = {
          output_format: values.output_format || 'markdown',
          language: values.language || 'ch',
          backend_url: values.backend_url || 'pipeline',
        }
      }
      if (editingModel) {
        await updateModel(editingModel.id, payload)
        message.success('更新成功')
      } else {
        await createModel(payload)
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
    { title: 'API地址', dataIndex: 'endpoint', key: 'endpoint' },
    {
      title: 'VLM',
      dataIndex: 'is_vlm',
      key: 'is_vlm',
      width: 80,
      render: (v: boolean, record: ModelConfig) =>
        record.model_type === 'llm'
          ? (v ? <Tag color="purple">VLM</Tag> : <Tag>纯文本</Tag>)
          : null,
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      render: (v: boolean) => v ? <Tag color="success">默认</Tag> : null,
    },
    {
      title: '保存日志',
      dataIndex: 'save_logs',
      key: 'save_logs',
      render: (v: boolean) => v ? <Tag color="blue">开启</Tag> : <Tag>关闭</Tag>,
    },
    {
      title: 'Temperature',
      key: 'temperature',
      render: (_: unknown, record: ModelConfig) => record.params?.temperature || '-',
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
    { key: 'doc_parser', label: '文档解析' },
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
              { value: 'doc_parser', label: '文档解析' },
            ]} />
          </Form.Item>
          <Form.Item shouldUpdate={(prev, curr) => prev.model_type !== curr.model_type}>
            {({ getFieldValue }) => {
              const modelType = getFieldValue('model_type')
              if (modelType === 'doc_parser') {
                return (
                  <Form.Item name="provider" label="解析服务" rules={[{ required: true }]}>
                    <Select onChange={onProviderChange} options={[
                      { value: 'mineru', label: 'MinerU（自部署）' },
                      { value: 'mineru_api', label: 'MinerU（官方API）' },
                      { value: 'custom', label: '自定义' },
                    ]} />
                  </Form.Item>
                )
              }
              return (
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
              )
            }}
          </Form.Item>
          <Form.Item shouldUpdate={(prev, curr) => prev.model_type !== curr.model_type}>
            {({ getFieldValue }) => {
              const modelType = getFieldValue('model_type')
              if (modelType !== 'doc_parser') return null
              return (
                <>
                  <Form.Item
                    name="endpoint"
                    label="服务地址"
                    rules={[{ required: getFieldValue('provider') !== 'mineru_api', message: '请输入服务地址' }]}
                  >
                    <Input placeholder="MinerU服务地址, 如 http://localhost:8888" />
                  </Form.Item>
                  <Form.Item
                    name="api_key"
                    label="API Key"
                    rules={[{ required: getFieldValue('provider') === 'mineru_api', message: 'MinerU官方API需要API Key' }]}
                  >
                    <Input.Password placeholder={editingModel?.api_key_masked || (getFieldValue('provider') === 'mineru_api' ? 'mineru.net 申请的 Token' : '可选')} />
                  </Form.Item>
                  <Form.Item name="output_format" label="输出格式">
                    <Select options={[
                      { value: 'markdown', label: 'Markdown' },
                      { value: 'json', label: 'JSON' },
                    ]} />
                  </Form.Item>
                  <Form.Item name="language" label="文档语言">
                    <Select options={[
                      { value: 'ch', label: '中文' },
                      { value: 'en', label: '英文' },
                    ]} />
                  </Form.Item>
                  <Form.Item name="backend_url" label="解析后端">
                    <Select options={[
                      { value: 'pipeline', label: 'pipeline（默认）' },
                      { value: 'vlm-transformers', label: 'vlm-transformers' },
                      { value: 'vlm-sglang', label: 'vlm-sglang' },
                    ]} />
                  </Form.Item>
                </>
              )
            }}
          </Form.Item>
          <Form.Item shouldUpdate={(prev, curr) => prev.model_type !== curr.model_type}>
            {({ getFieldValue }) => {
              // 文档解析服务没有模型名称/API地址/API Key（在上方单独渲染）
              if (getFieldValue('model_type') === 'doc_parser') return null
              return (
                <>
                  <Form.Item name="model_name" label="模型名称" rules={[{ required: true }]}>
                    <Input placeholder="如 gpt-4, text-embedding-ada-002" />
                  </Form.Item>
                  <Form.Item name="endpoint" label="API地址" rules={[{ required: true }]}>
                    <Input placeholder="API Base URL" />
                  </Form.Item>
                  <Form.Item name="api_key" label="API Key" rules={[{ required: !editingModel, message: '请输入 API Key' }]}>
                    <Input.Password placeholder={editingModel?.api_key_masked || 'API Key'} />
                  </Form.Item>
                </>
              )
            }}
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
                    <Form.Item
                      name="is_vlm"
                      label="视觉模型(VLM)"
                      valuePropName="checked"
                      tooltip="开启后标记该模型支持识别图片（视觉语言模型），评估/生成任务会按需发送图片输入"
                    >
                      <Switch />
                    </Form.Item>
                  </>
                )
              }
              if (modelType === 'embedding') {
                return (
                  <>
                    <Form.Item name="dimension" label="向量维度">
                      <InputNumber min={256} max={4096} />
                    </Form.Item>
                    <Form.Item name="max_input_length" label="最大输入长度">
                      <InputNumber min={512} max={8192} />
                    </Form.Item>
                  </>
                )
              }
              return null
            }}
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.model_type !== curr.model_type}>
            {({ getFieldValue }) => {
              // 仅 LLM/Embedding/Reranker 显示额外请求参数（doc_parser 无意义）
              if (getFieldValue('model_type') === 'doc_parser') return null
              return (
                <Form.Item
                  name="extra_params_text"
                  label="额外参数"
                  tooltip="以 JSON 对象填写，会顶层透传给模型 API 请求体，可控制关闭思考等。调用方可传同名参数覆盖"
                >
                  <TextArea
                    rows={4}
                    placeholder={'例如关闭思考：\n{"thinking": {"type": "disabled"}}\n或 {"enable_thinking": false}'}
                    style={{ fontFamily: 'monospace' }}
                  />
                </Form.Item>
              )
            }}
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.model_type !== curr.model_type}>
            {({ getFieldValue }) => {
              if (getFieldValue('model_type') === 'doc_parser' || !getFieldValue('extra_params_text')) return null
              return (
                <Form.Item label=" " colon={false}>
                  <Alert
                    type="info"
                    showIcon
                    message="这些参数会原样合并进每次 LLM 请求体（顶层字段）"
                  />
                </Form.Item>
              )
            }}
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="save_logs" label="保存请求响应" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Models