import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, InputNumber, message } from 'antd'
import { PlusOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getEvaluations, createEvaluation, startEvaluation, getDatasets, getRAGSystems, getModels } from '@/api'
import type { Evaluation, Dataset, RAGSystem, ModelConfig } from '@/types'

const Evaluations: React.FC = () => {
  const navigate = useNavigate()
  const [evaluations, setEvaluations] = useState<Evaluation[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [llmModels, setLLMModels] = useState<ModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [evalData, datasetData, ragData, modelData] = await Promise.all([
        getEvaluations(),
        getDatasets(),
        getRAGSystems(),
        getModels('llm'),
      ])
      setEvaluations(evalData)
      setDatasets(datasetData)
      setRAGSystems(ragData)
      setLLMModels(modelData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const showCreateDialog = () => {
    form.resetFields()
    form.setFieldsValue({
      batch_size: 10,
    })
    setModalVisible(true)
  }

  const saveEvaluation = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createEvaluation(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
    } finally {
      setSaving(false)
    }
  }

  const handleStartEvaluation = async (evaluation: Evaluation) => {
    try {
      await startEvaluation(evaluation.id)
      message.success('评估任务已启动')
      fetchData()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const getStatusType = (status: string) => {
    const types: Record<string, 'success' | 'warning' | 'processing' | 'error' | 'default'> = {
      completed: 'success',
      running: 'processing',
      pending: 'default',
      failed: 'error',
    }
    return types[status] || 'default'
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
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
      render: (_: unknown, record: Evaluation) => (
        <>
          {record.status === 'pending' && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleStartEvaluation(record)}
            >
              启动
            </Button>
          )}
          <Button type="link" size="small" onClick={() => navigate(`/evaluations/${record.id}`)}>
            详情
          </Button>
        </>
      ),
    },
  ]

  return (
    <Card
      title="评估任务"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新建评估
        </Button>
      }
    >
      <Table dataSource={evaluations} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title="新建评估任务"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveEvaluation}
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
          <Form.Item name="dataset_id" label="数据集" rules={[{ required: true }]}>
            <Select
              placeholder="选择数据集"
              options={datasets.map(d => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item name="rag_system_id" label="RAG系统">
            <Select
              placeholder="选择RAG系统（可选）"
              allowClear
              options={ragSystems.map(r => ({ value: r.id, label: r.name }))}
            />
          </Form.Item>
          <Form.Item name="llm_model_id" label="LLM模型" rules={[{ required: true }]}>
            <Select
              placeholder="选择LLM模型"
              options={llmModels.map(m => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
          <Form.Item name="metrics" label="评估指标" rules={[{ required: true }]}>
            <Select
              mode="multiple"
              placeholder="选择评估指标"
              options={[
                { value: 'faithfulness', label: 'Faithfulness' },
                { value: 'answer_relevance', label: 'Answer Relevance' },
                { value: 'context_precision', label: 'Context Precision' },
                { value: 'context_recall', label: 'Context Recall' },
                { value: 'answer_correctness', label: 'Answer Correctness' },
              ]}
            />
          </Form.Item>
          <Form.Item name="batch_size" label="批次大小">
            <InputNumber min={1} max={100} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Evaluations