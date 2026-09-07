import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Modal, Form, Input, InputNumber, Select, message, Space,
  Progress, Descriptions, Tabs, Tooltip, Divider, Row, Col, Statistic
} from 'antd'
import {
  PlusOutlined, PlayCircleOutlined, DeleteOutlined, EyeOutlined,
  ReloadOutlined, FileTextOutlined, CheckCircleOutlined, CloseCircleOutlined
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getTrainingDataEvals, createTrainingDataEval, runTrainingDataEval,
  deleteTrainingDataEval, getTrainingDataEvalStatus, getAvailableTrainingDataMetrics,
  getTrainingDataEvalResults, getDatasets, getModels
} from '@/api'
import type { TrainingDataEval, Dataset, TrainingDataMetricDefinition, TrainingDataEvalResult, ModelConfig } from '@/types'
import type { TrainingDataEvalCreateParams } from '@/api'

const { Option } = Select
const { TabPane } = Tabs
const { TextArea } = Input

const DATA_TYPE_OPTIONS = [
  { value: 'llm', label: '大模型训练数据', color: 'blue' },
  { value: 'embedding', label: 'Embedding训练数据', color: 'green' },
  { value: 'reranker', label: 'Reranker训练数据', color: 'purple' },
  { value: 'reward_model', label: '奖励模型训练数据', color: 'orange' },
  { value: 'dpo', label: 'DPO训练数据', color: 'cyan' },
  { value: 'vlm', label: 'VLM训练数据', color: 'magenta' },
  { value: 'vla', label: 'VLA训练数据', color: 'red' },
]

const TrainingDataEvals: React.FC = () => {
  const [evaluations, setEvaluations] = useState<TrainingDataEval[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [llmModels, setLlmModels] = useState<ModelConfig[]>([])
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([])
  const [availableMetrics, setAvailableMetrics] = useState<TrainingDataMetricDefinition[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [selectedEval, setSelectedEval] = useState<TrainingDataEval | null>(null)
  const [saving, setSaving] = useState(false)
  const [results, setResults] = useState<TrainingDataEvalResult[]>([])
  const [resultsLoading, setResultsLoading] = useState(false)
  const [form] = Form.useForm()
  const [pollingIntervals, setPollingIntervals] = useState<Record<string, number>>({})

  const fetchData = async () => {
    setLoading(true)
    try {
      const [evalData, datasetData] = await Promise.all([
        getTrainingDataEvals().catch(() => []),
        getDatasets().catch(() => [])
      ])
      setEvaluations(evalData)
      setDatasets(datasetData)
    } catch (e) {
      console.error('加载数据失败:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    return () => {
      Object.values(pollingIntervals).forEach(interval => clearInterval(interval))
    }
  }, [])

  // 轮询运行中的任务
  useEffect(() => {
    const runningEvals = evaluations.filter(e => e.status === 'running')
    runningEvals.forEach(evalItem => {
      if (!pollingIntervals[evalItem.id]) {
        const interval = window.setInterval(async () => {
          try {
            const status = await getTrainingDataEvalStatus(evalItem.id)
            if (status.status !== 'running') {
              clearInterval(pollingIntervals[evalItem.id])
              setPollingIntervals(prev => {
                const next = { ...prev }
                delete next[evalItem.id]
                return next
              })
              fetchData()
            }
          } catch (e) {
            console.error('轮询状态失败:', e)
          }
        }, 3000)
        setPollingIntervals(prev => ({ ...prev, [evalItem.id]: interval }))
      }
    })
  }, [evaluations])

  const fetchMetrics = async (dataType: string): Promise<TrainingDataMetricDefinition[]> => {
    try {
      const data = await getAvailableTrainingDataMetrics(dataType)
      setAvailableMetrics(data.metrics)
      return data.metrics
    } catch (e) {
      console.error('加载指标失败:', e)
      return []
    }
  }

  // 打开创建弹窗时加载数据集和评估用模型列表
  const loadBaseOptions = async () => {
    if (datasets.length > 0) return
    try {
      const [datasetData, llmData, embeddingData] = await Promise.all([
        getDatasets().catch(() => []),
        getModels('llm').catch(() => []),
        getModels('embedding').catch(() => []),
      ])
      setDatasets(datasetData)
      setLlmModels(llmData)
      setEmbeddingModels(embeddingData)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }


  const showCreateDialog = () => {
    form.resetFields()
    form.setFieldsValue({
      config: { batch_size: 10 },
      metrics: []
    })
    setAvailableMetrics([])
    loadBaseOptions()
    setModalVisible(true)
  }

  const handleDataTypeChange = async (value: string) => {
    // 拉取该类型全部注册指标并自动全选（避免默认指标名与注册表不一致）
    const metricList = await fetchMetrics(value)
    form.setFieldsValue({ metrics: metricList.map(m => m.name) })
  }

  const saveEvaluation = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      // 构指标配置
      const metricConfigs = values.metrics.map((metricName: string) => {
        const metric = availableMetrics.find(m => m.name === metricName)
        return {
          metric_name: metricName,
          metric_type: metric?.category || 'quality',
          enabled: true,
          weight: 1.0,
          params: {}
        }
      })

      const params: TrainingDataEvalCreateParams = {
        name: values.name,
        description: values.description,
        dataset_id: values.dataset_id,
        data_type: values.data_type,
        config: values.config || { batch_size: 10 },
        metrics: values.metrics,
        metric_configs: metricConfigs,
        llm_model_id: values.llm_model_id,
        embedding_model_id: values.embedding_model_id,
      }

      await createTrainingDataEval(params)
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
    } catch (e) {
      console.error('创建失败:', e)
    } finally {
      setSaving(false)
    }
  }

  const handleStartEvaluation = async (evaluation: TrainingDataEval) => {
    try {
      await runTrainingDataEval(evaluation.id)
      message.success('评估任务已启动')
      fetchData()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleDelete = async (evaluation: TrainingDataEval) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除评估任务 "${evaluation.name}" 吗？`,
      onOk: async () => {
        try {
          await deleteTrainingDataEval(evaluation.id)
          message.success('删除成功')
          fetchData()
        } catch (e) {
          // 错误已在拦截器处理
        }
      }
    })
  }

  const showDetail = async (evaluation: TrainingDataEval) => {
    setSelectedEval(evaluation)
    setDetailModalVisible(true)
    if (evaluation.status === 'completed') {
      setResultsLoading(true)
      try {
        const { results: data } = await getTrainingDataEvalResults(evaluation.id)
        setResults(data)
      } finally {
        setResultsLoading(false)
      }
    }
  }

  const getStatusTag = (status: string) => {
    const statusMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
      pending: { color: 'default', text: '待执行', icon: <FileTextOutlined /> },
      running: { color: 'processing', text: '执行中', icon: <ReloadOutlined spin /> },
      completed: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
      failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> }
    }
    const { color, text, icon } = statusMap[status] || { color: 'default', text: status, icon: null }
    return (
      <Tag color={color} icon={icon}>
        {text}
      </Tag>
    )
  }

  const getDataTypeTag = (dataType: string) => {
    const option = DATA_TYPE_OPTIONS.find(o => o.value === dataType)
    return (
      <Tag color={option?.color || 'default'}>
        {option?.label || dataType}
      </Tag>
    )
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: TrainingDataEval) => (
        <a onClick={() => showDetail(record)}>{text}</a>
      )
    },
    {
      title: '数据类型',
      dataIndex: 'data_type',
      key: 'data_type',
      width: 150,
      render: (dataType: string) => getDataTypeTag(dataType)
    },
    {
      title: '数据集',
      dataIndex: 'dataset_id',
      key: 'dataset_id',
      width: 150,
      render: (datasetId: string) => {
        const dataset = datasets.find(d => d.id === datasetId)
        return dataset?.name || datasetId
      }
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => getStatusTag(status)
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 150,
      render: (progress: number, record: TrainingDataEval) => (
        record.status === 'running' ? (
          <Progress percent={progress} size="small" status="active" />
        ) : record.status === 'completed' ? (
          <Progress percent={100} size="small" status="success" />
        ) : (
          <Progress percent={progress} size="small" />
        )
      )
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate',
      key: 'pass_rate',
      width: 100,
      render: (rate: number) => rate !== undefined ? `${(rate * 100).toFixed(1)}%` : '-'
    },
    {
      title: '样本数',
      dataIndex: 'total_samples',
      key: 'total_samples',
      width: 100,
      render: (total: number, record: TrainingDataEval) => (
        <span>{record.passed_samples || 0}/{total || 0}</span>
      )
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm')
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: any, record: TrainingDataEval) => (
        <Space>
          {record.status === 'pending' && (
            <Tooltip title="开始评估">
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => handleStartEvaluation(record)}
              />
            </Tooltip>
          )}
          <Tooltip title="查看详情">
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => showDetail(record)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(record)}
            />
          </Tooltip>
        </Space>
      )
    }
  ]

  return (
    <Card
      title="训练数据评估"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新建评估
        </Button>
      }
    >
      <Table
        columns={columns}
        dataSource={evaluations}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 10 }}
      />

      {/* 创建评估模态框 */}
      <Modal
        title="新建训练数据评估"
        open={modalVisible}
        onOk={saveEvaluation}
        onCancel={() => setModalVisible(false)}
        confirmLoading={saving}
        width={700}
      >
        <Form
          form={form}
          layout="vertical"
          autoComplete="off"
        >
          <Form.Item
            name="name"
            label="评估名称"
            rules={[{ required: true, message: '请输入评估名称' }]}
          >
            <Input placeholder="例如：LLM训练数据质量评估" />
          </Form.Item>

          <Form.Item
            name="data_type"
            label="训练数据类型"
            rules={[{ required: true, message: '请选择数据类型' }]}
          >
            <Select
              placeholder="选择数据类型"
              options={DATA_TYPE_OPTIONS}
              onChange={handleDataTypeChange}
            />
          </Form.Item>

          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true, message: '请选择数据集' }]}
          >
            <Select placeholder="选择数据集">
              {datasets.map(ds => (
                <Option key={ds.id} value={ds.id}>
                  {ds.name} ({ds.record_count}条记录)
                </Option>
              ))}
            </Select>
          </Form.Item>

          {/* 评估用模型：按指标依赖显示 */}
          {availableMetrics.some(m => m.requires_llm) && (
            <Form.Item
              name="llm_model_id"
              label="评估用 LLM 模型"
              rules={[{ required: true, message: '所选指标需要 LLM 模型打分' }]}
              extra="用于评估打分的 LLM（与被评估的数据集无关）"
            >
              <Select
                placeholder="选择评估用 LLM"
                showSearch
                optionFilterProp="label"
                options={llmModels.map(m => ({ value: m.id, label: m.name }))}
              />
            </Form.Item>
          )}

          {availableMetrics.some(m => m.requires_embedding) && (
            <Form.Item
              name="embedding_model_id"
              label="评估用 Embedding 模型"
              rules={[{ required: true, message: '所选指标需要 Embedding 模型' }]}
            >
              <Select
                placeholder="选择评估用 Embedding"
                showSearch
                optionFilterProp="label"
                options={embeddingModels.map(m => ({ value: m.id, label: m.name }))}
              />
            </Form.Item>
          )}

          <Form.Item
            name="metrics"
            label="评估指标"
            rules={[{ required: true, message: '请至少选择一个指标' }]}
          >
            <Select
              mode="multiple"
              placeholder="选择评估指标"
              options={availableMetrics.map(m => ({
                label: `${m.display_name} (${m.category})${m.requires_llm ? ' (LLM)' : m.requires_embedding ? ' (Embedding)' : ''}`,
                value: m.name
              }))}
            />
          </Form.Item>

          <Form.Item
            name={['config', 'batch_size']}
            label="批处理大小"
            initialValue={10}
          >
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="description"
            label="描述"
          >
            <TextArea rows={3} placeholder="可选：描述本次评估的目的" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情模态框 */}
      <Modal
        title="评估详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={900}
      >
        {selectedEval && (
          <Tabs defaultActiveKey="overview">
            <TabPane tab="概览" key="overview">
              <Descriptions bordered column={2}>
                <Descriptions.Item label="名称">{selectedEval.name}</Descriptions.Item>
                <Descriptions.Item label="数据类型">
                  {getDataTypeTag(selectedEval.data_type)}
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  {getStatusTag(selectedEval.status)}
                </Descriptions.Item>
                <Descriptions.Item label="进度">
                  <Progress percent={selectedEval.progress} />
                </Descriptions.Item>
                <Descriptions.Item label="总样本">{selectedEval.total_samples}</Descriptions.Item>
                <Descriptions.Item label="通过样本">{selectedEval.passed_samples}</Descriptions.Item>
                <Descriptions.Item label="失败样本">{selectedEval.failed_samples}</Descriptions.Item>
                <Descriptions.Item label="通过率">
                  {(selectedEval.pass_rate * 100).toFixed(2)}%
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {dayjs(selectedEval.created_at).format('YYYY-MM-DD HH:mm:ss')}
                </Descriptions.Item>
                <Descriptions.Item label="完成时间">
                  {selectedEval.completed_at
                    ? dayjs(selectedEval.completed_at).format('YYYY-MM-DD HH:mm:ss')
                    : '-'}
                </Descriptions.Item>
              </Descriptions>

              {selectedEval.summary && (
                <>
                  <Divider />
                  <h4>评估汇总</h4>
                  <Row gutter={16}>
                    <Col span={6}>
                      <Statistic
                        title="平均分"
                        value={selectedEval.summary.average_score?.toFixed(3) || '-'}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="优秀样本"
                        value={selectedEval.quality_distribution?.excellent || 0}
                        suffix="个"
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="良好样本"
                        value={selectedEval.quality_distribution?.good || 0}
                        suffix="个"
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="较差样本"
                        value={(selectedEval.quality_distribution?.poor || 0) +
                          (selectedEval.quality_distribution?.acceptable || 0)}
                        suffix="个"
                      />
                    </Col>
                  </Row>
                </>
              )}
            </TabPane>

            <TabPane tab="指标详情" key="metrics">
              {selectedEval.summary?.metrics_summary && (
                <Table
                  dataSource={Object.entries(selectedEval.summary.metrics_summary).map(
                    ([name, data]: [string, any]) => ({
                      name,
                      ...data
                    })
                  )}
                  columns={[
                    { title: '指标', dataIndex: 'name', key: 'name' },
                    { title: '平均分', dataIndex: 'mean', key: 'mean', render: (v: number) => v?.toFixed(3) },
                    { title: '标准差', dataIndex: 'std', key: 'std', render: (v: number) => v?.toFixed(3) },
                    { title: '最小值', dataIndex: 'min', key: 'min', render: (v: number) => v?.toFixed(3) },
                    { title: '最大值', dataIndex: 'max', key: 'max', render: (v: number) => v?.toFixed(3) },
                    { title: '样本数', dataIndex: 'count', key: 'count' },
                    { title: '通过率', dataIndex: 'pass_rate', key: 'pass_rate',
                      render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : '-' }
                  ]}
                  pagination={false}
                />
              )}
            </TabPane>

            {selectedEval.status === 'completed' && (
              <TabPane tab="样本结果" key="results">
                <Table
                  loading={resultsLoading}
                  dataSource={results}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  columns={[
                    {
                      title: '问题',
                      dataIndex: 'question',
                      key: 'question',
                      ellipsis: true,
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      key: 'status',
                      width: 90,
                      render: (status: string) => {
                        const color = status === 'passed' ? 'success' : status === 'warning' ? 'warning' : 'error'
                        const text = status === 'passed' ? '通过' : status === 'warning' ? '警告' : '失败'
                        return <Tag color={color}>{text}</Tag>
                      },
                    },
                    {
                      title: '综合得分',
                      dataIndex: 'overall_score',
                      key: 'overall_score',
                      width: 100,
                      render: (score: number) => (score * 100).toFixed(1),
                    },
                    {
                      title: '问题数',
                      key: 'issues',
                      width: 80,
                      render: (_: any, record: TrainingDataEvalResult) => record.issues?.length || 0,
                    },
                  ]}
                />
              </TabPane>
            )}
          </Tabs>
        )}
      </Modal>
    </Card>
  )
}

export default TrainingDataEvals