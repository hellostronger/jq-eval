import React, { useState, useEffect } from 'react'
import { Card, Table, Button, Modal, Form, Input, Select, Tag, Space, message, Tabs, Typography, Divider } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, HistoryOutlined, BookOutlined } from '@ant-design/icons'
import { promptApi, PromptVersion, PromptFramework } from '../api/prompts'

const { TextArea } = Input
const { Title, Text } = Typography

const Prompts: React.FC = () => {
  const [prompts, setPrompts] = useState<PromptVersion[]>([])
  const [frameworks, setFrameworks] = useState<PromptFramework[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [historyVisible, setHistoryVisible] = useState(false)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptVersion | null>(null)
  const [historyPrompt, setHistoryPrompt] = useState<PromptVersion[]>([])
  const [form] = Form.useForm()

  const fetchPrompts = async () => {
    setLoading(true)
    try {
      const data = await promptApi.listPrompts()
      setPrompts(data)
    } catch (error) {
      message.error('获取 Prompt 列表失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchFrameworks = async () => {
    try {
      const data = await promptApi.listFrameworks()
      setFrameworks(data)
    } catch (error) {
      console.error('获取框架列表失败', error)
    }
  }

  useEffect(() => {
    fetchPrompts()
    fetchFrameworks()
  }, [])

  const handleCreate = async (values: any) => {
    try {
      await promptApi.createPrompt(values)
      message.success('创建成功')
      setModalVisible(false)
      form.resetFields()
      fetchPrompts()
    } catch (error) {
      message.error('创建失败')
    }
  }

  const handleUpdate = async (values: any) => {
    if (!selectedPrompt) return
    try {
      await promptApi.updatePrompt(selectedPrompt.id, values)
      message.success('更新成功')
      setModalVisible(false)
      form.resetFields()
      setSelectedPrompt(null)
      fetchPrompts()
    } catch (error) {
      message.error('更新失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await promptApi.deletePrompt(id)
      message.success('删除成功')
      fetchPrompts()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const showHistory = async (id: string) => {
    try {
      const data = await promptApi.getPromptHistory(id)
      setHistoryPrompt(data)
      setHistoryVisible(true)
    } catch (error) {
      message.error('获取历史版本失败')
    }
  }

  const handleEdit = (record: PromptVersion) => {
    setSelectedPrompt(record)
    form.setFieldsValue(record)
    setModalVisible(true)
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
      render: (v: number) => <Tag color="blue">v{v}</Tag>,
    },
    {
      title: '框架',
      dataIndex: 'framework',
      key: 'framework',
      width: 100,
      render: (f: string) => f ? <Tag>{f}</Tag> : '-',
    },
    {
      title: '内容预览',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (c: string) => <Text style={{ maxWidth: 300 }} ellipsis={{ tooltip: c }}>{c}</Text>,
    },
    {
      title: '使用场景',
      dataIndex: 'usage_scenario',
      key: 'usage_scenario',
      width: 100,
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 150,
      render: (tags: string[]) => (
        <>
          {tags?.map((tag, i) => (
            <Tag key={i} color="purple">{tag}</Tag>
          ))}
        </>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (d: string) => new Date(d).toLocaleString(),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: any, record: PromptVersion) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Button type="link" icon={<HistoryOutlined />} onClick={() => showHistory(record.id)}>
            历史
          </Button>
          <Button type="link" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const frameworkOptions = frameworks.map(f => ({
    label: f.display_name,
    value: f.name,
  }))

  return (
    <div>
      <Card
        title="Prompt 管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => {
            setSelectedPrompt(null)
            form.resetFields()
            setModalVisible(true)
          }}>
            新建 Prompt
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={prompts}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Modal
        title={selectedPrompt ? '编辑 Prompt' : '新建 Prompt'}
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false)
          form.resetFields()
          setSelectedPrompt(null)
        }}
        onOk={() => form.submit()}
        width={700}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={selectedPrompt ? handleUpdate : handleCreate}
          initialValues={{
            parameters: {},
            test_cases: [],
            tags: [],
          }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="请输入 Prompt 名称" />
          </Form.Item>

          <Form.Item name="content" label="Prompt 内容" rules={[{ required: true, message: '请输入 Prompt 内容' }]}>
            <TextArea rows={6} placeholder="请输入 Prompt 内容" />
          </Form.Item>

          <Form.Item name="framework" label="使用框架">
            <Select placeholder="选择框架" options={frameworkOptions} allowClear />
          </Form.Item>

          <Form.Item name="usage_scenario" label="使用场景">
            <Select
              placeholder="选择使用场景"
              options={[
                { label: '问答', value: 'qa' },
                { label: '生成', value: 'generation' },
                { label: '分析', value: 'analysis' },
                { label: '其他', value: 'other' },
              ]}
              allowClear
            />
          </Form.Item>

          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              placeholder="输入标签后回车"
            />
          </Form.Item>

          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选描述" />
          </Form.Item>

          <Form.Item name="optimization_notes" label="优化说明">
            <TextArea rows={3} placeholder="记录优化过程中的关键决策" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="版本历史"
        open={historyVisible}
        onCancel={() => setHistoryVisible(false)}
        footer={null}
        width={800}
      >
        <Table
          dataSource={historyPrompt}
          rowKey="id"
          pagination={false}
          columns={[
            {
              title: '版本',
              dataIndex: 'version',
              key: 'version',
              width: 80,
              render: (v: number) => <Tag color="blue">v{v}</Tag>,
            },
            {
              title: '内容',
              dataIndex: 'content',
              key: 'content',
              ellipsis: true,
            },
            {
              title: '修改时间',
              dataIndex: 'created_at',
              key: 'created_at',
              render: (d: string) => new Date(d).toLocaleString(),
            },
          ]}
        />
      </Modal>
    </div>
  )
}

export default Prompts