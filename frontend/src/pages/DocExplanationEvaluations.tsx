import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space, Progress } from 'antd'
import { PlusOutlined, PlayCircleOutlined, EyeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getDocExplanationEvaluations, createDocExplanationEvaluation, runDocExplanationEvaluation, getModels, getDocExplanations } from '@/api'
import type { DocExplanationEvaluation, ModelConfig, DocExplanation } from '@/types'

const DocExplanationEvaluations: React.FC = () => {
  const navigate = useNavigate()
  const [evaluations, setEvaluations] = useState<DocExplanationEvaluation[]>([])
  const [models, setModels] = useState<ModelConfig[]>([])
  const [explanations, setExplanations] = useState<DocExplanation[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [evalData, modelData, expData] = await Promise.all([
        getDocExplanationEvaluations(),
        getModels('llm'),
        getDocExplanations(),
      ])
      setEvaluations(evalData)
      setModels(modelData)
      setExplanations(expData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const showCreateModal = () => {
    form.resetFields()
    form.setFieldsValue({
      metrics: ['completeness', 'accuracy', 'info_missing', 'explanation_error'],
      batch_size: 10,
    })
    setModalVisible(true)
  }

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createDocExplanationEvaluation(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
    } finally {
      setSaving(false)
    }
  }

  const handleRun = async (evalId: string) => {
    try {
      await runDocExplanationEvaluation(evalId)
      message.success('评估任务已启动')
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'default',
      running: 'processing',
      completed: 'success',
      failed: 'error',
    }
    return colors[status] || 'default'
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusColor(status)}>{status}</Tag>,
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      render: (progress: number) => <Progress percent={progress} size="small" />,
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
      width: 180,
      render: (_: unknown, record: DocExplanationEvaluation) => (
        <Space>
          {record.status === 'pending' && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleRun(record.id)}
            >
              启动
            </Button>
          )}
          {(record.status === 'completed' || record.status === 'running') && (
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => navigate(`/doc-explanation-evaluations/${record.id}`)}
            >
              详情
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="文档解释评估"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateModal}>
          新建评估
        </Button>
      }
    >
      <Table
        dataSource={evaluations}
        columns={columns}
        rowKey="id"
        loading={loading}
      />

      <Modal
        title="新建文档解释评估"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={handleCreate}
        confirmLoading={saving}
        width={600}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="评估任务名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="评估任务描述" />
          </Form.Item>
          <Form.Item name="llm_model_id" label="LLM模型" rules={[{ required: true }]}>
            <Select
              placeholder="选择LLM模型"
              options={models.map(m => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
          <Form.Item name="doc_ids" label="文档范围" extra="不选择则评估所有有解释的文档">
            <Select
              mode="multiple"
              placeholder="选择文档（可选）"
              allowClear
              options={explanations.map(e => ({ value: e.doc_id, label: e.document_title || e.doc_id }))}
            />
          </Form.Item>
          <Form.Item name="metrics" label="评估维度">
            <Select
              mode="multiple"
              placeholder="选择评估维度"
              options={[
                { value: 'completeness', label: '完整性' },
                { value: 'accuracy', label: '准确性' },
                { value: 'info_missing', label: '信息遗漏' },
                { value: 'explanation_error', label: '解释错误' },
              ]}
            />
          </Form.Item>
          <Form.Item name="batch_size" label="批次大小">
            <Input type="number" min={1} max={100} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default DocExplanationEvaluations