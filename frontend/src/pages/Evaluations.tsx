import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, InputNumber, message, Space, Switch, Divider } from 'antd'
import { PlusOutlined, PlayCircleOutlined, SwitcherOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getEvaluations, createEvaluation, startEvaluation, getDatasets, getRAGSystems, getModels, getInvocationBatches } from '@/api'
import type { Evaluation, Dataset, RAGSystem, ModelConfig, InvocationBatch } from '@/types'

const Evaluations: React.FC = () => {
  const navigate = useNavigate()
  const [evaluations, setEvaluations] = useState<Evaluation[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [ragSystems, setRAGSystems] = useState<RAGSystem[]>([])
  const [llmModels, setLLMModels] = useState<ModelConfig[]>([])
  const [invocationBatches, setInvocationBatches] = useState<InvocationBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      // 独立请求，避免某个失败导致整体失败
      const [evalData, datasetData, ragData, modelData, batchData] = await Promise.all([
        getEvaluations().catch((e) => { console.error('getEvaluations failed:', e); return [] }),
        getDatasets().catch((e) => { console.error('getDatasets failed:', e); return [] }),
        getRAGSystems().catch((e) => { console.error('getRAGSystems failed:', e); return [] }),
        getModels('llm').catch((e) => { console.error('getModels failed:', e); return [] }),
        getInvocationBatches({ status: 'completed' }).catch((e) => { console.error('getInvocationBatches failed:', e); return [] }),
      ])
      console.log('Loaded data:', { evalData, datasetData, ragData, modelData, batchData })
      setEvaluations(evalData)
      setDatasets(datasetData)
      setRAGSystems(ragData)
      setLLMModels(modelData)
      setInvocationBatches(batchData)
    } catch (e) {
      console.error('加载数据失败:', e)
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
      reuse_invocation: true,
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

  const handleCompare = () => {
    // 只允许对比已完成的评估任务
    const selectedEvals = evaluations.filter(e => selectedRowKeys.includes(e.id))
    const completedEvals = selectedEvals.filter(e => e.status === 'completed')
    if (completedEvals.length < 2) {
      message.warning('请至少选择2个已完成的评估任务进行对比')
      return
    }
    const ids = completedEvals.map(e => e.id).join(',')
    navigate(`/evaluations/compare?ids=${ids}`)
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
      title: '调用批次',
      dataIndex: 'invocation_batch_id',
      key: 'invocation_batch_id',
      render: (id?: string) => {
        if (!id) return '-'
        const batch = invocationBatches.find(b => b.id === id)
        return batch ? <Tag color="blue">{batch.name}</Tag> : id
      },
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

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys)
    },
    getCheckboxProps: (record: Evaluation) => ({
      disabled: record.status !== 'completed',
    }),
  }

  return (
    <Card
      title="评估任务"
      extra={
        <Space>
          <Button
            type="default"
            icon={<SwitcherOutlined />}
            onClick={handleCompare}
            disabled={selectedRowKeys.length < 2}
          >
            对比 ({selectedRowKeys.filter(k => evaluations.find(e => e.id === k)?.status === 'completed').length})
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
            新建评估
          </Button>
        </Space>
      }
    >
      <Table
        dataSource={evaluations}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={rowSelection}
      />

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
          <Form.Item name="dataset_id" label="数据集" extra="可选。如果不选择，则使用调用批次关联的数据集">
            <Select
              placeholder="选择数据集（可选）"
              allowClear
              options={datasets.map(d => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Divider>调用结果设置</Divider>
          <Form.Item name="invocation_batch_id" label="调用批次" extra="选择已完成的调用批次，将使用其调用结果进行评估">
            <Select
              placeholder="选择调用批次"
              allowClear
              options={invocationBatches.map(b => {
                const datasetName = datasets.find(d => d.id === b.dataset_id)?.name || ''
                return {
                  value: b.id,
                  label: `${b.name} - ${datasetName} (${b.completed_count}/${b.total_count})`
                }
              })}
            />
          </Form.Item>
          <Form.Item name="reuse_invocation" label="复用调用结果" valuePropName="checked" extra="开启后将使用存量调用结果进行评估，关闭则重新调用RAG系统">
            <Switch />
          </Form.Item>
          <Divider>评估配置</Divider>
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
                { value: 'answer_relevancy', label: 'Answer Relevance' },
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