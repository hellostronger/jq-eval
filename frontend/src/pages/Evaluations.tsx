import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, InputNumber, message, Space, Switch, Divider } from 'antd'
import { PlusOutlined, PlayCircleOutlined, SwitcherOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { formatTime } from '@/utils/format'
import { usePollingWhenRunning } from '@/hooks/usePollingWhenRunning'
import { getEvaluations, createEvaluation, startEvaluation, getDatasets, getModels, getInvocationBatches, getMetrics } from '@/api'
import type { Evaluation, Dataset, ModelConfig, InvocationBatch, MetricDefinition } from '@/types'

const Evaluations: React.FC = () => {
  const navigate = useNavigate()
  const [evaluations, setEvaluations] = useState<Evaluation[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [llmModels, setLLMModels] = useState<ModelConfig[]>([])
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([])
  const [invocationBatches, setInvocationBatches] = useState<InvocationBatch[]>([])
  const [metricDefs, setMetricDefs] = useState<MetricDefinition[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      // 独立请求，避免某个失败导致整体失败
      const [evalData, datasetData, llmData, embData, batchData, metricData] = await Promise.all([
        getEvaluations().catch((e) => { console.error('getEvaluations failed:', e); return [] }),
        getDatasets().catch((e) => { console.error('getDatasets failed:', e); return [] }),
        getModels('llm').catch((e) => { console.error('getModels llm failed:', e); return [] }),
        getModels('embedding').catch((e) => { console.error('getModels embedding failed:', e); return [] }),
        getInvocationBatches({ status: 'completed' }).catch((e) => { console.error('getInvocationBatches failed:', e); return [] }),
        getMetrics().catch((e) => { console.error('getMetrics failed:', e); return [] }),
      ])
      setEvaluations(evalData)
      setDatasets(datasetData)
      setLLMModels(llmData)
      setEmbeddingModels(embData)
      setInvocationBatches(batchData)
      setMetricDefs(metricData)
    } catch (e) {
      console.error('加载数据失败:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  // 有评估运行中时自动轮询刷新状态，全部结束后停止（与 LoadTests 页一致）
  usePollingWhenRunning(
    evaluations.some((e) => e.status === 'running' || e.status === 'pending'),
    fetchData,
    5000,
  )

  const showCreateDialog = () => {
    form.resetFields()
    form.setFieldsValue({
      batch_size: 10,
      reuse_invocation: true,
    })
    setModalVisible(true)
  }

  // 指标下拉按后端指标定义分组，而不是在前端另抄一份名单：
  // 之前两边各写一份，名字已经开始打架（前端「上下文精确率」vs 指标市场「上下文精确度」），
  // 而且 BLEU / ROUGE-L / 语义相似度这些后端支持的指标在前端根本选不到。
  // 分组以 requires_llm 为准：context_precision/context_recall 虽然属于检索阶段，
  // 但要用 LLM 裁判打分，不能被归进「无需 LLM」那一组。
  const metricOptionGroups = React.useMemo(() => {
    if (metricDefs.length === 0) return []
    const toOption = (m: MetricDefinition) => ({
      value: m.name,
      label: `${m.display_name}（${m.name}）`,
    })
    return [
      {
        label: '检索阶段指标（无需 LLM）',
        options: metricDefs.filter((m) => m.category === 'retrieval' && !m.requires_llm).map(toOption),
      },
      {
        label: '生成阶段指标（确定性，无需 LLM）',
        options: metricDefs.filter((m) => m.category !== 'retrieval' && !m.requires_llm).map(toOption),
      },
      {
        label: '需要 LLM/Embedding 判定',
        options: metricDefs.filter((m) => m.requires_llm).map(toOption),
      },
    ].filter((g) => g.options.length > 0)
  }, [metricDefs])

  // 是否必须配 LLM：直接读后端声明的 requires_llm，不再维护一份硬编码名单
  const llmFreeMetricNames = React.useMemo(
    () => new Set(metricDefs.filter((m) => !m.requires_llm).map((m) => m.name)),
    [metricDefs]
  )

  // 指标名单还没加载出来时返回 false，宁可多要求一次 LLM 也不要放过校验
  const needsLLM = (metrics: string[]) =>
    llmFreeMetricNames.size === 0 || metrics.some((m) => !llmFreeMetricNames.has(m))

  const saveEvaluation = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      // 解耦评测：仅选无需 LLM 的指标时，LLM/Embedding 模型可省略（提交前置空）
      const metrics = (values.metrics || []) as string[]
      const payload = { ...values }
      if (!needsLLM(metrics)) {
        payload.llm_model_id = undefined
        payload.embedding_model_id = undefined
      }
      await createEvaluation(payload)
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
      cancelled: 'warning',
    }
    return types[status] || 'default'
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
    },
    {
      title: '调用批次', dataIndex: 'invocation_batch_id', key: 'invocation_batch_id',
      render: (id?: string) => {
        if (!id) return '-'
        const batch = invocationBatches.find(b => b.id === id)
        return batch ? <Tag color="blue">{batch.name}</Tag> : id
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at',
      render: (date: string) => formatTime(date),
    },
    {
      title: '操作', key: 'action',
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
          <Form.Item
            name="llm_model_id"
            label="LLM模型"
            rules={[{
              validator: (_, value) => {
                const metrics: string[] = form.getFieldValue('metrics') || []
                if (needsLLM(metrics) && !value) {
                  return Promise.reject('选择了需要 LLM 判定的指标时必须选择LLM模型')
                }
                return Promise.resolve()
              }
            }]}
            extra="仅选择无需 LLM 的指标（检索类 MRR/HitRate/Recall@K、确定性指标）时可省略"
          >
            <Select
              placeholder="选择LLM模型"
              options={llmModels.map(m => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
          <Form.Item name="embedding_model_id" label="Embedding模型" extra="部分评估指标需要（如answer_relevancy）">
            <Select
              placeholder="选择Embedding模型（可选）"
              allowClear
              options={embeddingModels.map(m => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
          <Form.Item
            name="metrics"
            label="评估指标"
            rules={[{ required: true }]}
            extra="需要 LLM/Embedding 判定的指标请同时选择对应模型；检索类指标仅需调用结果中的 retrieval_ids 与数据集标注的 target_chunk_ids（候选池基准如 StratRAG）"
          >
            <Select
              mode="multiple"
              placeholder="选择评估指标"
              loading={loading}
              options={metricOptionGroups}
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