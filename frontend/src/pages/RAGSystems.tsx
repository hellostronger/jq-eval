import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, Switch, message, Popconfirm, Spin, List } from 'antd'
import { PlusOutlined, MessageOutlined, SendOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getRAGSystems, createRAGSystem, updateRAGSystem, deleteRAGSystem, testRAGSystem, queryRAGSystem, getLLMModels } from '@/api'
import type { RAGSystem } from '@/types'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface LLMModel {
  id: string
  name: string
  provider?: string
  model_name?: string
  endpoint?: string
  has_api_key: boolean
}

const RAGSystems: React.FC = () => {
  const [systems, setSystems] = useState<RAGSystem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSystem, setEditingSystem] = useState<RAGSystem | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  // LLM模型列表（用于直连LLM类型）
  const [llmModels, setLLMModels] = useState<LLMModel[]>([])
  const [selectedSystemType, setSelectedSystemType] = useState<string>('dify')

  // 聊天状态
  const [chatModalVisible, setChatModalVisible] = useState(false)
  const [chattingSystem, setChattingSystem] = useState<RAGSystem | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)

  const fetchSystems = async () => {
    setLoading(true)
    try {
      const data = await getRAGSystems()
      setSystems(data)
    } finally {
      setLoading(false)
    }
  }

  const fetchLLMModels = async () => {
    try {
      const data = await getLLMModels()
      setLLMModels(data)
    } catch (e) {
      // 错误已在拦截器处理
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
    setSelectedSystemType('dify')
    fetchLLMModels()
    setModalVisible(true)
  }

  const editSystem = (system: RAGSystem) => {
    setEditingSystem(system)
    // 从 connection_config 中提取字段
    const config = system.connection_config || {}
    setSelectedSystemType(system.system_type)
    fetchLLMModels()
    form.setFieldsValue({
      name: system.name,
      display_name: config.display_name || system.name,
      system_type: system.system_type,
      api_endpoint: config.api_endpoint || '',
      api_key: config.api_key || '',
      llm_model_id: config.llm_model_id || '',
      model_name: config.model_name || '',
      provider: config.provider || 'openai',
      is_active: config.is_active ?? true,
    })
    setModalVisible(true)
  }

  const saveSystem = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      // 构建connection_config
      let connectionConfig: Record<string, any> = {}

      if (values.system_type === 'direct_llm') {
        // 直连LLM类型 - 从选中的LLM模型获取配置
        const selectedModel = llmModels.find(m => m.id === values.llm_model_id)
        if (selectedModel) {
          connectionConfig = {
            api_endpoint: selectedModel.endpoint,
            api_key: selectedModel.has_api_key ? 'use_model_config' : '', // 标记使用模型配置的key
            model_name: selectedModel.model_name || selectedModel.name,
            provider: selectedModel.provider || 'openai',
            llm_model_id: selectedModel.id,
            display_name: values.display_name,
            is_active: values.is_active,
            temperature: values.temperature ?? 0.7,
            max_tokens: values.max_tokens ?? 2048,
          }
        }
      } else {
        // 其他系统类型
        connectionConfig = {
          api_endpoint: values.api_endpoint,
          api_key: values.api_key,
          display_name: values.display_name,
          is_active: values.is_active,
        }
      }

      // 转换数据格式以匹配后端API
      const payload = {
        name: values.name,
        system_type: values.system_type,
        description: values.display_name,
        connection_config: connectionConfig,
        llm_config: {},
        retrieval_config: {},
      }
      if (editingSystem) {
        await updateRAGSystem(editingSystem.id, payload)
        message.success('更新成功')
      } else {
        await createRAGSystem(payload)
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

  // 打开聊天窗口
  const openChat = (system: RAGSystem) => {
    setChattingSystem(system)
    setChatMessages([])
    setChatInput('')
    setChatModalVisible(true)
  }

  // 发送聊天消息
  const sendChatMessage = async () => {
    if (!chatInput.trim() || !chattingSystem) return

    const userMessage = chatInput.trim()
    setChatMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setChatInput('')
    setChatLoading(true)

    try {
      const res = await queryRAGSystem(chattingSystem.id, userMessage)
      const assistantContent = res.answer || res.response || res.content || '无响应'
      setChatMessages(prev => [...prev, { role: 'assistant', content: assistantContent }])
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'assistant', content: '查询失败，请检查连接配置' }])
    } finally {
      setChatLoading(false)
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '显示名称',
      key: 'display_name',
      render: (_: unknown, record: RAGSystem) => record.connection_config?.display_name || record.name,
    },
    {
      title: '类型',
      dataIndex: 'system_type',
      key: 'system_type',
      render: (type: string) => <Tag color="blue">{type.toUpperCase()}</Tag>,
    },
    {
      title: 'API地址',
      key: 'api_endpoint',
      render: (_: unknown, record: RAGSystem) => record.connection_config?.api_endpoint || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => <Tag color={v === 'active' ? 'success' : 'default'}>{v === 'active' ? '启用' : '禁用'}</Tag>,
    },
    {
      title: '健康状态',
      dataIndex: 'health_status',
      key: 'health_status',
      render: (v?: string) => {
        if (!v) return <Tag color="default">未检查</Tag>
        return <Tag color={v === 'healthy' ? 'green' : 'red'}>{v}</Tag>
      },
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
          <Button type="link" size="small" icon={<MessageOutlined />} onClick={() => openChat(record)}>
            聊天
          </Button>
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
    { value: 'direct_llm', label: '直连LLM' },
  ]

  const providerOptions = [
    { value: 'openai', label: 'OpenAI' },
    { value: 'azure', label: 'Azure OpenAI' },
    { value: 'zhipuai', label: '智谱AI' },
    { value: 'baidu', label: '百度千帆' },
    { value: 'aliyun', label: '阿里云百炼' },
    { value: 'volcengine', label: '火山引擎' },
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
            <Input placeholder="系统标识名称" disabled={editingSystem !== null} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="展示名称" />
          </Form.Item>
          <Form.Item name="system_type" label="系统类型" rules={[{ required: true }]}>
            <Select
              options={systemTypes}
              disabled={editingSystem !== null}
              onChange={(value) => {
                setSelectedSystemType(value)
                if (value === 'direct_llm') {
                  fetchLLMModels()
                }
              }}
            />
          </Form.Item>

          {/* 直连LLM类型的表单字段 */}
          {selectedSystemType === 'direct_llm' && (
            <>
              <Form.Item name="llm_model_id" label="LLM模型" rules={[{ required: true, message: '请选择LLM模型' }]}>
                <Select
                  placeholder="选择已配置的LLM模型"
                  options={llmModels.map(m => ({
                    value: m.id,
                    label: `${m.name} (${m.provider || 'openai'} - ${m.model_name || m.name})`,
                    disabled: !m.has_api_key
                  }))}
                />
              </Form.Item>
              <Form.Item name="provider" label="供应商">
                <Select options={providerOptions} placeholder="默认使用模型配置的供应商" />
              </Form.Item>
              <Form.Item name="temperature" label="Temperature">
                <Input type="number" placeholder="0.7" min={0} max={2} step={0.1} />
              </Form.Item>
              <Form.Item name="max_tokens" label="Max Tokens">
                <Input type="number" placeholder="2048" min={1} />
              </Form.Item>
            </>
          )}

          {/* 其他系统类型的表单字段 */}
          {selectedSystemType !== 'direct_llm' && (
            <>
              <Form.Item name="api_endpoint" label="API地址" rules={[{ required: true }]}>
                <Input placeholder="API Endpoint URL" />
              </Form.Item>
              <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
                <Input.Password placeholder="API Key" />
              </Form.Item>
            </>
          )}

          <Form.Item name="is_active" label="启用状态" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 聊天弹窗 */}
      <Modal
        title={`与 ${chattingSystem?.connection_config?.display_name || chattingSystem?.name} 聊天`}
        open={chatModalVisible}
        onCancel={() => setChatModalVisible(false)}
        footer={null}
        width={700}
      >
        <div style={{ height: 400, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, overflow: 'auto', marginBottom: 16 }}>
            {chatMessages.length === 0 && (
              <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>
                输入问题开始对话
              </div>
            )}
            <List
              dataSource={chatMessages}
              renderItem={(msg) => (
                <List.Item style={{ border: 'none', padding: '8px 0' }}>
                  <div style={{
                    maxWidth: '80%',
                    padding: '8px 12px',
                    borderRadius: 8,
                    backgroundColor: msg.role === 'user' ? '#e6f7ff' : '#f5f5f5',
                    alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  }}>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>
                      {msg.role === 'user' ? '你' : '系统'}
                    </div>
                    <div>{msg.content}</div>
                  </div>
                </List.Item>
              )}
            />
            {chatLoading && (
              <div style={{ textAlign: 'center', padding: 10 }}>
                <Spin size="small" />
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="输入问题..."
              onPressEnter={sendChatMessage}
              disabled={chatLoading}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={sendChatMessage}
              loading={chatLoading}
            >
              发送
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  )
}

export default RAGSystems