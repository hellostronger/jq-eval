import React, { useState, useEffect, useRef } from 'react'
import { Card, Input, Button, Space, Typography, Row, Col, Layout, List, Tag, Spin, message, Modal, Form, Tabs, Divider } from 'antd'
import { SendOutlined, SaveOutlined, PlayCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { vibeAgentApi, Slot, Workflow } from '../api/vibeAgent'
import { useWebSocket } from '../hooks/useWebSocket'

const { TextArea } = Input
const { Title, Text } = Typography
const { Sider, Content } = Layout

const VibeAgent: React.FC = () => {
  // State
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [description, setDescription] = useState('')
  const [messages, setMessages] = useState<Array<{ role: string; content: string; type?: string }>>([])
  const [slots, setSlots] = useState<Slot[]>([])
  const [workflowType, setWorkflowType] = useState<string>('')
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [mermaidDiagram, setMermaidDiagram] = useState<string>('')
  const [pythonCode, setPythonCode] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [inputText, setInputText] = useState('')
  const [saveModalVisible, setSaveModalVisible] = useState(false)
  const [executeModalVisible, setExecuteModalVisible] = useState(false)
  const [saveForm] = Form.useForm()

  // WebSocket
  const { isConnected, sendMessage: wsSendMessage, lastMessage } = useWebSocket(sessionId)

  // Mermaid rendering
  const mermaidRef = useRef<HTMLDivElement>(null)

  // Handle WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      handleMessage(lastMessage)
    }
  }, [lastMessage])

  // Render Mermaid diagram
  useEffect(() => {
    if (mermaidDiagram && mermaidRef.current) {
      renderMermaid(mermaidDiagram)
    }
  }, [mermaidDiagram])

  const handleMessage = (msg: any) => {
    switch (msg.type) {
      case 'connected':
        addMessage('system', 'WebSocket 连接成功', 'system')
        break

      case 'clarification':
        addMessage('assistant', msg.content, 'question')
        if (msg.slots) {
          setSlots(msg.slots)
        }
        if (msg.workflow_type) {
          setWorkflowType(msg.workflow_type)
        }
        break

      case 'preview':
        addMessage('assistant', msg.content, 'preview')
        if (msg.slots) {
          setSlots(msg.slots)
        }
        break

      case 'slots_update':
        if (msg.slots) {
          setSlots(msg.slots)
        }
        if (msg.workflow_type) {
          setWorkflowType(msg.workflow_type)
        }
        break

      case 'workflow_generated':
        setWorkflow({
          id: '',
          name: msg.workflow_definition?.name || '工作流',
          graph_definition: msg.workflow_definition,
          nodes: msg.workflow_definition?.nodes || [],
          edges: msg.workflow_definition?.edges || [],
          python_code: msg.python_code || '',
          mermaid_diagram: msg.mermaid_diagram || '',
          llm_config: {},
          status: 'draft',
          created_at: new Date().toISOString(),
        })
        setMermaidDiagram(msg.mermaid_diagram || '')
        setPythonCode(msg.python_code || '')
        addMessage('assistant', '工作流已生成！您可以查看流程图和代码，或保存/执行。', 'success')
        break

      case 'progress':
        addMessage('assistant', msg.content, 'progress')
        break

      case 'error':
        message.error(msg.error_message)
        addMessage('system', `错误: ${msg.error_message}`, 'error')
        break
    }
  }

  const addMessage = (role: string, content: string, type?: string) => {
    setMessages(prev => [...prev, { role, content, type }])
  }

  const renderMermaid = async (diagram: string) => {
    if (!mermaidRef.current) return

    try {
      // Dynamic import of mermaid
      const mermaid = await import('mermaid')
      mermaid.default.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose',
      })

      const { svg } = await mermaid.default.render('mermaid-graph', diagram)
      mermaidRef.current.innerHTML = svg
    } catch (e) {
      mermaidRef.current.innerHTML = `<pre style="color: red;">Mermaid 渲染错误: ${e}</pre>`
    }
  }

  // Actions
  const handleStartSession = async () => {
    if (!description.trim()) {
      message.warning('请输入工作流描述')
      return
    }

    setLoading(true)
    try {
      const result = await vibeAgentApi.createSession(description)
      setSessionId(result.session_id)

      // 处理初始结果
      if (result.result.type === 'clarification') {
        addMessage('assistant', result.result.message, 'question')
        setSlots(result.result.slots)
        if (result.result.workflow_type) {
          setWorkflowType(result.result.workflow_type)
        }
      } else if (result.result.type === 'preview') {
        addMessage('assistant', result.result.message, 'preview')
        setSlots(result.result.slots)
      }
    } catch (e) {
      message.error('创建会话失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSendMessage = () => {
    if (!inputText.trim()) return

    addMessage('user', inputText)

    if (isConnected) {
      wsSendMessage('user_message', inputText)
    } else {
      // HTTP fallback
      vibeAgentApi.sendMessage(sessionId!, inputText).then(result => {
        if (result.type === 'clarification') {
          addMessage('assistant', result.message, 'question')
          setSlots(result.slots)
        } else if (result.type === 'preview') {
          addMessage('assistant', result.message, 'preview')
          setSlots(result.slots)
        } else if (result.type === 'generate_request') {
          handleGenerate()
        }
      })
    }

    setInputText('')
  }

  const handleGenerate = async () => {
    if (!sessionId) return

    setLoading(true)
    addMessage('assistant', '正在生成工作流...', 'progress')

    try {
      const result = await vibeAgentApi.generateWorkflow(sessionId)
      setWorkflow({
        id: '',
        name: result.workflow_definition?.name || '工作流',
        graph_definition: result.workflow_definition,
        nodes: result.workflow_definition?.nodes || [],
        edges: result.workflow_definition?.edges || [],
        python_code: result.python_code || '',
        mermaid_diagram: result.mermaid_diagram || '',
        llm_config: {},
        status: 'draft',
        created_at: new Date().toISOString(),
      })
      setMermaidDiagram(result.mermaid_diagram || '')
      setPythonCode(result.python_code || '')
      addMessage('assistant', '工作流已生成！', 'success')
    } catch (e) {
      message.error('生成工作流失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSaveWorkflow = async (values: any) => {
    if (!sessionId) return

    try {
      await vibeAgentApi.saveWorkflow(sessionId, values.name, values.description)
      message.success('工作流已保存')
      setSaveModalVisible(false)
      fetchWorkflows()
    } catch (e) {
      message.error('保存失败')
    }
  }

  const handleExecuteWorkflow = async (values: any) => {
    if (!workflow?.id) {
      message.warning('请先保存工作流')
      return
    }

    try {
      const execResult = await vibeAgentApi.executeWorkflow(workflow.id, values.input_data)
      message.success('执行完成')
      addMessage('system', `执行结果: ${JSON.stringify(execResult.result)}`, 'execution')
      setExecuteModalVisible(false)
    } catch (e) {
      message.error('执行失败')
    }
  }

  const fetchWorkflows = async () => {
    try {
      const result = await vibeAgentApi.listWorkflows()
      setWorkflows(result)
    } catch (e) {
      console.error('Failed to fetch workflows')
    }
  }

  useEffect(() => {
    fetchWorkflows()
  }, [])

  // Render helpers
  const renderSlotStatus = (slot: Slot) => {
    const filled = slot.current_value || slot.confidence === 'auto_decide'
    return (
      <Tag color={filled ? 'green' : 'orange'}>
        {filled ? '已填写' : '待确认'}
      </Tag>
    )
  }

  const messageList = messages.map((msg, idx) => (
    <List.Item key={idx} style={{ padding: '8px 0' }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <Tag color={msg.role === 'user' ? 'blue' : msg.role === 'assistant' ? 'purple' : 'default'}>
          {msg.role === 'user' ? '用户' : msg.role === 'assistant' ? '助手' : '系统'}
        </Tag>
        <Text>{msg.content}</Text>
      </div>
    </List.Item>
  ))

  return (
    <Layout style={{ height: 'calc(100vh - 100px)', background: '#f0f2f5' }}>
      <Sider width={250} style={{ background: '#fff', padding: 16 }}>
        <Title level={5}>已保存的工作流</Title>
        <List
          dataSource={workflows}
          renderItem={(w) => (
            <List.Item style={{ padding: '4px 0' }}>
              <Space>
                <ThunderboltOutlined />
                <Text>{w.name}</Text>
                <Tag>{w.status}</Tag>
              </Space>
            </List.Item>
          )}
          style={{ marginBottom: 16 }}
        />

        <Divider />

        <Title level={5}>配置槽位</Title>
        <div style={{ marginBottom: 8 }}>
          {workflowType && <Tag color="blue">{workflowType}</Tag>}
        </div>
        <List
          dataSource={slots}
          renderItem={(slot) => (
            <List.Item style={{ padding: '4px 0' }}>
              <Space direction="vertical" size={0}>
                <Space>
                  <Text strong>{slot.slot_name}</Text>
                  {renderSlotStatus(slot)}
                </Space>
                {slot.current_value && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    值: {slot.current_value}
                  </Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      </Sider>

      <Content style={{ padding: 16 }}>
        <Row gutter={16}>
          <Col span={8}>
            {/* 对话区域 */}
            <Card
              title="工作流描述"
              extra={sessionId && <Tag color={isConnected ? 'green' : 'red'}>
                {isConnected ? 'WebSocket 已连接' : '未连接'}
              </Tag>}
              style={{ height: '100%' }}
            >
              {!sessionId ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <TextArea
                    rows={4}
                    placeholder="描述你想要的工作流，例如：帮我创建一个智能客服工作流..."
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    onClick={handleStartSession}
                    loading={loading}
                    block
                  >
                    开始创建
                  </Button>
                </Space>
              ) : (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <List
                    dataSource={messageList}
                    style={{ maxHeight: 400, overflow: 'auto' }}
                  />
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      placeholder="输入回复或补充信息..."
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      onPressEnter={handleSendMessage}
                    />
                    <Button type="primary" icon={<SendOutlined />} onClick={handleSendMessage}>
                      发送
                    </Button>
                  </Space.Compact>
                  <Space>
                    <Button onClick={handleGenerate} loading={loading}>
                      生成工作流
                    </Button>
                  </Space>
                </Space>
              )}
            </Card>
          </Col>

          <Col span={8}>
            {/* 流程图预览 */}
            <Card
              title="流程图预览"
              extra={workflow && (
                <Space>
                  <Button icon={<SaveOutlined />} onClick={() => setSaveModalVisible(true)}>
                    保存
                  </Button>
                  <Button icon={<PlayCircleOutlined />} onClick={() => {
                    if (!workflow.id) {
                      message.warning('请先保存工作流')
                    } else {
                      setExecuteModalVisible(true)
                    }
                  }}>
                    执行
                  </Button>
                </Space>
              )}
            >
              <Spin spinning={loading}>
                <div
                  ref={mermaidRef}
                  style={{
                    minHeight: 300,
                    background: '#fafafa',
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  {mermaidDiagram ? null : (
                    <Text type="secondary">等待生成流程图...</Text>
                  )}
                </div>
              </Spin>
            </Card>
          </Col>

          <Col span={8}>
            {/* 代码预览 */}
            <Card title="生成的代码">
              <Tabs
                items={[
                  {
                    key: 'python',
                    label: 'Python',
                    children: (
                      <pre style={{
                        background: '#1e1e1e',
                        color: '#d4d4d4',
                        padding: 16,
                        borderRadius: 8,
                        fontSize: 12,
                        maxHeight: 500,
                        overflow: 'auto',
                      }}>
                        {pythonCode || '等待生成代码...'}
                      </pre>
                    ),
                  },
                  {
                    key: 'mermaid',
                    label: 'Mermaid',
                    children: (
                      <pre style={{
                        background: '#fafafa',
                        padding: 16,
                        borderRadius: 8,
                        fontSize: 12,
                      }}>
                        {mermaidDiagram || '等待生成...'}
                      </pre>
                    ),
                  },
                  {
                    key: 'json',
                    label: 'JSON',
                    children: (
                      <pre style={{
                        background: '#fafafa',
                        padding: 16,
                        borderRadius: 8,
                        fontSize: 12,
                      }}>
                        {workflow ? JSON.stringify(workflow.graph_definition, null, 2) : '等待生成...'}
                      </pre>
                    ),
                  },
                ]}
              />
            </Card>
          </Col>
        </Row>
      </Content>

      {/* 保存工作流 Modal */}
      <Modal
        title="保存工作流"
        open={saveModalVisible}
        onCancel={() => setSaveModalVisible(false)}
        onOk={() => saveForm.submit()}
      >
        <Form form={saveForm} onFinish={handleSaveWorkflow}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="工作流名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={3} placeholder="工作流描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 执行工作流 Modal */}
      <Modal
        title="执行工作流"
        open={executeModalVisible}
        onCancel={() => setExecuteModalVisible(false)}
        onOk={() => {}}
      >
        <Form onFinish={handleExecuteWorkflow}>
          <Form.Item name="input_data" label="输入数据">
            <TextArea rows={4} placeholder="JSON 格式输入数据" defaultValue='{"input": "测试输入"}' />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default VibeAgent