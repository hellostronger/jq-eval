import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space,
  Popconfirm, Tabs, Statistic, Row, Col, Progress
} from 'antd'
import {
  PlusOutlined, PlayCircleOutlined, EyeOutlined, DeleteOutlined, ReloadOutlined
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import {
  getTrainingDataEvals, createTrainingDataEval, runTrainingDataEval,
  getTrainingDataEvalStatus, deleteTrainingDataEval, getAvailableTrainingDataMetrics,
  getTrainingDataTemplates, getTrainingDataEvalResults
} from '@/api'
import type { TrainingDataEval, TrainingDataMetricDefinition, TrainingDataTemplate, TrainingDataEvalResult } from '@/types'

const { TabPane } = Tabs

const DATA_TYPE_OPTIONS = [
  { label: 'LLM训练数据', value: 'llm' },
  { label: 'Embedding训练数据', value: 'embedding' },
  { label: 'Reranker训练数据', value: 'reranker' },
  { label: '奖励模型训练数据', value: 'reward_model' },
  { label: 'DPO训练数据', value: 'dpo' },
  { label: 'VLM训练数据', value: 'vlm' },
  { label: 'VLA训练数据', value: 'vla' },
]

const DATA_TYPE_MAP: Record<string, string> = {
  llm: 'LLM',
  embedding: 'Embedding',
  reranker: 'Reranker',
  reward_model: '奖励模型',
  dpo: 'DPO',
  vlm: 'VLM',
  vla: 'VLA',
}

const TrainingDataEvaluations: React.FC = () => {
  const navigate = useNavigate()
  const [evaluations, setEvaluations] = useState<TrainingDataEval[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [selectedEval, setSelectedEval] = useState<TrainingDataEval | null>(null)
  const [metrics, setMetrics] = useState<TrainingDataMetricDefinition[]>([])
  const [templates, setTemplates] = useState<TrainingDataTemplate[]>([])
  const [results, setResults] = useState<TrainingDataEvalResult[]>([])
  const [resultsLoading, setResultsLoading] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const data = await getTrainingDataEvals()
      setEvaluations(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleDataTypeChange = async (dataType: string) => {
    const [metricsData, templatesData] = await Promise.all([
      getAvailableTrainingDataMetrics(dataType),
      getTrainingDataTemplates(dataType),
    ])
    setMetrics(metricsData.metrics)
    setTemplates(templatesData.templates)

    // 默认选择所有指标
    if (metricsData.metrics.length > 0) {
      form.setFieldsValue({
        metrics: metricsData.map(m => m.name),
      })
    }
  }

  const showCreateDialog = () => {
    form.resetFields()
    setModalVisible(true)
  }

  const saveEvaluation = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createTrainingDataEval(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchData()
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

  const handleDeleteEvaluation = async (id: string) => {
    try {
      await deleteTrainingDataEval(id)
      message.success('删除成功')
      fetchData()
    } catch (e) {
      // 错误已在拦截器处理
    }
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
    const statusMap: Record<string, { color: string; text: string }> = {
      pending: { color: 'default', text: '待执行' },
      running: { color: 'processing', text: '执行中' },
      completed: { color: 'success', text: '已完成' },
      failed: { color: 'error', text: '失败' },
    }
    const { color, text } = statusMap[status] || { color: 'default', text: status }
    return <Tag color={color}>{text}</Tag>
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '数据类型',
      dataIndex: 'data_type',
      key: 'data_type',
      render: (type: string) => DATA_TYPE_MAP[type] || type,
    },
    {
      title: '样本数',
      dataIndex: 'total_samples',
      key: 'total_samples',
    },
    {
      title: '通过/失败',
      key: 'pass_fail',
      render: (_: any, record: TrainingDataEval) => (
        <span>
          <span style={{ color: '#52c41a' }}>{record.passed_samples}</span>
          {' / '}
          <span style={{ color: '#f5222d' }}>{record.failed_samples}</span>
        </span>
      ),
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate',
      key: 'pass_rate',
      render: (rate: number) => `${(rate * 100).toFixed(1)}%`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: getStatusTag,
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
      render: (_: any, record: TrainingDataEval) => (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            disabled={record.status === 'running'}
            onClick={() => handleStartEvaluation(record)}
          >
            {record.status === 'running' ? '执行中' : '执行'}
          </Button>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => showDetail(record)}
          >
            详情
          </Button>
          <Popconfirm
            title="确认删除"
            onConfirm={() => handleDeleteEvaluation(record.id)}
          >
            <Button danger size="small" icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const resultColumns = [
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
      render: (score: number) => (score * 100).toFixed(1),
    },
    {
      title: '问题数',
      key: 'issues',
      render: (_: any, record: TrainingDataEvalResult) => record.issues?.length || 0,
    },
  ]

  return (
    <div className="page-container">
      <Card
        title="训练数据评估"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
            创建评估任务
          </Button>
        }
      >
        <Table
          loading={loading}
          dataSource={evaluations}
          columns={columns}
          rowKey="id"
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* 创建评估任务弹窗 */}
      <Modal
        title="创建训练数据评估任务"
        open={modalVisible}
        onOk={saveEvaluation}
        onCancel={() => setModalVisible(false)}
        confirmLoading={saving}
        width={700}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="任务名称"
            rules={[{ required: true, message: '请输入任务名称' }]}
          >
            <Input placeholder="请输入任务名称" />
          </Form.Item>

          <Form.Item
            name="data_type"
            label="数据类型"
            rules={[{ required: true, message: '请选择数据类型' }]}
          >
            <Select
              options={DATA_TYPE_OPTIONS}
              onChange={handleDataTypeChange}
              placeholder="请选择数据类型"
            />
          </Form.Item>

          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true, message: '请选择数据集' }]}
          >
            <Select placeholder="请选择数据集">
              {/* TODO: 加载数据集列表 */}
            </Select>
          </Form.Item>

          <Form.Item
            name="metrics"
            label="评估指标"
            rules={[{ required: true, message: '请至少选择一个指标' }]}
          >
            <Select mode="multiple" placeholder="请选择评估指标">
              {metrics.map(m => (
                <Select.Option key={m.name} value={m.name}>
                  {m.display_name}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          {templates.length > 0 && (
            <Form.Item name="template_id" label="使用模板（可选）">
              <Select placeholder="选择预设模板">
                {templates.map(t => (
                  <Select.Option key={t.id} value={t.id}>
                    {t.display_name}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
          )}

          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="请输入任务描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情弹窗 */}
      <Modal
        title="评估详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={1000}
      >
        {selectedEval && (
          <Tabs defaultActiveKey="overview">
            <TabPane tab="概览" key="overview">
              <Row gutter={16} style={{ marginBottom: 24 }}>
                <Col span={6}>
                  <Statistic title="总样本数" value={selectedEval.total_samples} />
                </Col>
                <Col span={6}>
                  <Statistic title="通过数" value={selectedEval.passed_samples} />
                </Col>
                <Col span={6}>
                  <Statistic title="失败数" value={selectedEval.failed_samples} />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="通过率"
                    value={`${(selectedEval.pass_rate * 100).toFixed(1)}%`}
                  />
                </Col>
              </Row>

              {selectedEval.summary && (
                <>
                  <h4>指标统计</h4>
                  <Row gutter={16}>
                    {Object.entries(selectedEval.summary.metrics_summary || {}).map(([name, stats]: [string, any]) => (
                      <Col span={8} key={name}>
                        <Card size="small" title={name}>
                          <p>均值: {(stats.mean * 100).toFixed(1)}%</p>
                          <p>标准差: {(stats.std * 100).toFixed(1)}%</p>
                        </Card>
                      </Col>
                    ))}
                  </Row>

                  <h4 style={{ marginTop: 16 }}>质量分布</h4>
                  {selectedEval.quality_distribution && (
                    <Row>
                      {Object.entries(selectedEval.quality_distribution).map(([level, count]) => (
                        <Col span={6} key={level}>
                          <div style={{ textAlign: 'center' }}>
                            <Progress
                              type="circle"
                              percent={Math.round((count as number) / selectedEval.total_samples * 100)}
                              format={() => count as number}
                              width={80}
                            />
                            <div>
                              {level === 'excellent' && '优秀'}
                              {level === 'good' && '良好'}
                              {level === 'acceptable' && '可接受'}
                              {level === 'poor' && '较差'}
                            </div>
                          </div>
                        </Col>
                      ))}
                    </Row>
                  )}
                </>
              )}
            </TabPane>

            <TabPane tab="评估结果" key="results">
              <Table
                loading={resultsLoading}
                dataSource={results}
                columns={resultColumns}
                rowKey="id"
                pagination={{ pageSize: 10 }}
              />
            </TabPane>
          </Tabs>
        )}
      </Modal>
    </div>
  )
}

export default TrainingDataEvaluations
