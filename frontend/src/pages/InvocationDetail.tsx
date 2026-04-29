import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Button, Tag, Space, Progress, message, Popconfirm, Modal, Spin, Select, Descriptions, Divider, Alert } from 'antd'
import { ReloadOutlined, PlayCircleOutlined, ArrowLeftOutlined, EyeOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getInvocationBatch,
  getInvocationResults,
  retryInvocationBatch,
  retrySingleResult,
  getDatasets,
  getRAGSystems,
  getModels,
  analyzeSingleCorrection,
  getCorrectionByInvocation,
  confirmCorrection,
} from '@/api'
import type { InvocationBatch, InvocationResult, Dataset, RAGSystem, ModelConfig, AnnotationCorrection } from '@/types'

const InvocationDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [batch, setBatch] = useState<InvocationBatch | null>(null)
  const [results, setResults] = useState<InvocationResult[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [ragSystems, setRagSystems] = useState<RAGSystem[]>([])
  const [llmModels, setLlmModels] = useState<ModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [selectedResult, setSelectedResult] = useState<InvocationResult | null>(null)
  const [correctionModalVisible, setCorrectionModalVisible] = useState(false)
  const [selectedLlmModel, setSelectedLlmModel] = useState<string | undefined>(undefined)
  const [correctionLoading, setCorrectionLoading] = useState(false)
  const [correctionResult, setCorrectionResult] = useState<AnnotationCorrection | null>(null)
  const [correctionDetailVisible, setCorrectionDetailVisible] = useState(false)

  const fetchData = async () => {
    if (!id) return
    setLoading(true)
    try {
      const [batchData, resultsData, datasetData, ragData, llmData] = await Promise.all([
        getInvocationBatch(id),
        getInvocationResults(id, { skip: (page - 1) * pageSize, limit: pageSize, status: statusFilter }),
        getDatasets(),
        getRAGSystems(),
        getModels('llm'),
      ])
      setBatch(batchData)
      setResults(resultsData)
      setDatasets(datasetData)
      setRagSystems(ragData)
      setLlmModels(llmData)
      setTotal(batchData.total_count)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [id, page, pageSize, statusFilter])

  const handleRetryAllFailed = async () => {
    if (!id) return
    try {
      const res = await retryInvocationBatch(id)
      message.success(`重试任务已启动，将重试 ${res.retry_count} 条失败记录`)
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const handleRetrySelected = async () => {
    if (!id || selectedRowKeys.length === 0) return
    try {
      await retryInvocationBatch(id, selectedRowKeys as string[])
      message.success(`重试任务已启动，将重试 ${selectedRowKeys.length} 条记录`)
      setSelectedRowKeys([])
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const handleRetrySingle = async (resultId: string) => {
    if (!id) return
    try {
      await retrySingleResult(id, resultId)
      message.success('重试任务已启动')
      fetchData()
    } catch (e) {
      // 错误已处理
    }
  }

  const handleViewDetail = (result: InvocationResult) => {
    setSelectedResult(result)
    setDetailModalVisible(true)
  }

  const handleOpenCorrection = (result: InvocationResult) => {
    setSelectedResult(result)
    setCorrectionModalVisible(true)
  }

  const handleRunCorrection = async () => {
    if (!selectedResult || !selectedLlmModel) {
      message.error('请选择LLM模型')
      return
    }
    setCorrectionLoading(true)
    try {
      const res = await analyzeSingleCorrection({
        invocation_result_id: selectedResult.id,
        qa_record_id: selectedResult.qa_record_id,
        batch_id: id,
        llm_model_id: selectedLlmModel,
      })
      setCorrectionResult(res)
      setCorrectionModalVisible(false)
      setCorrectionDetailVisible(true)
      message.success('矫正分析完成')
    } catch (e) {
      message.error('矫正分析失败')
    } finally {
      setCorrectionLoading(false)
    }
  }

  const handleConfirmCorrection = async (isDoubtful: boolean) => {
    if (!correctionResult) return
    try {
      await confirmCorrection(correctionResult.id, { is_doubtful: isDoubtful })
      message.success('确认成功')
      setCorrectionDetailVisible(false)
    } catch (e) {
      message.error('确认失败')
    }
  }

  const getStatusType = (status: string) => {
    const types: Record<string, 'success' | 'warning' | 'processing' | 'error' | 'default'> = {
      success: 'success',
      pending: 'warning',
      failed: 'error',
    }
    return types[status] || 'default'
  }

  const datasetName = datasets.find(d => d.id === batch?.dataset_id)?.name || batch?.dataset_id || ''
  const ragSystemName = ragSystems.find(r => r.id === batch?.rag_system_id)?.name || batch?.rag_system_id || ''

  const columns = [
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      ellipsis: true,
      width: 250,
    },
    {
      title: '标准答案',
      dataIndex: 'ground_truth',
      key: 'ground_truth',
      ellipsis: true,
      width: 200,
      render: (truth?: string) => truth ? (truth.length > 50 ? truth.slice(0, 50) + '...' : truth) : '-',
    },
    {
      title: '答案',
      dataIndex: 'answer',
      key: 'answer',
      ellipsis: true,
      width: 300,
      render: (answer?: string) => answer ? (answer.length > 100 ? answer.slice(0, 100) + '...' : answer) : '-',
    },
    {
      title: '耗时(ms)',
      dataIndex: 'latency',
      key: 'latency',
      width: 100,
      render: (latency?: number) => latency ? Math.round(latency * 1000) : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => <Tag color={getStatusType(status)}>{status}</Tag>,
    },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      ellipsis: true,
      width: 200,
      render: (error?: string) => error || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: InvocationResult) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          {record.status === 'success' && (
            <Button
              type="link"
              size="small"
              icon={<ExclamationCircleOutlined />}
              onClick={() => handleOpenCorrection(record)}
            >
              矫正
            </Button>
          )}
          {record.status === 'failed' && (
            <Button
              type="link"
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => handleRetrySingle(record.id)}
            >
              重试
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedKeys)
    },
  }

  if (!batch) {
    return <Spin />
  }

  return (
    <Card
      title={
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/invocations')}>
            返回
          </Button>
          <span>{batch.name}</span>
        </Space>
      }
      extra={
        <Space>
          {batch.failed_count > 0 && (
            <Popconfirm
              title="重试所有失败记录"
              description={`确定重试 ${batch.failed_count} 条失败记录？`}
              onConfirm={handleRetryAllFailed}
            >
              <Button icon={<ReloadOutlined />}>
                重试全部失败 ({batch.failed_count})
              </Button>
            </Popconfirm>
          )}
          {selectedRowKeys.length > 0 && (
            <Popconfirm
              title="重试选中记录"
              onConfirm={handleRetrySelected}
            >
              <Button type="primary" icon={<PlayCircleOutlined />}>
                重试选中 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
        </Space>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <Space size="large">
          <span>数据集: <Tag color="blue">{datasetName}</Tag></span>
          <span>RAG系统: <Tag color="green">{ragSystemName}</Tag></span>
          <span>状态: <Tag color={getStatusType(batch.status)}>{batch.status}</Tag></span>
          <span>进度:
            <Progress
              percent={batch.total_count > 0 ? Math.round((batch.completed_count + batch.failed_count) / batch.total_count * 100) : 0}
              size="small"
              style={{ width: 100, marginLeft: 8 }}
            />
          </span>
          <span>完成: {batch.completed_count}/{batch.total_count}</span>
          {batch.failed_count > 0 && <span><Tag color="error">{batch.failed_count} 失败</Tag></span>}
          {batch.started_at && <span>开始: {dayjs(batch.started_at).format('YYYY-MM-DD HH:mm:ss')}</span>}
          {batch.completed_at && <span>完成: {dayjs(batch.completed_at).format('YYYY-MM-DD HH:mm:ss')}</span>}
        </Space>
      </div>

      <div style={{ marginBottom: 16 }}>
        <Space>
          <span>筛选状态:</span>
          <Tag
            color={statusFilter === undefined ? 'blue' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setStatusFilter(undefined)}
          >
            全部
          </Tag>
          <Tag
            color={statusFilter === 'success' ? 'green' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setStatusFilter('success')}
          >
            成功
          </Tag>
          <Tag
            color={statusFilter === 'failed' ? 'red' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setStatusFilter('failed')}
          >
            失败
          </Tag>
        </Space>
      </div>

      <Table
        dataSource={results}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={rowSelection}
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
        }}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="调用结果详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={800}
      >
        {selectedResult && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <strong>状态:</strong> <Tag color={getStatusType(selectedResult.status)}>{selectedResult.status}</Tag>
              {selectedResult.latency && <span style={{ marginLeft: 16 }}><strong>耗时:</strong> {Math.round(selectedResult.latency * 1000)} ms</span>}
            </div>
            <div style={{ marginBottom: 16 }}>
              <strong>问题:</strong>
              <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                {selectedResult.question}
              </div>
            </div>
            {selectedResult.ground_truth && (
              <div style={{ marginBottom: 16 }}>
                <strong>标准答案:</strong>
                <div style={{ padding: 8, background: '#e6f7ff', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.ground_truth}
                </div>
              </div>
            )}
            {selectedResult.answer && (
              <div style={{ marginBottom: 16 }}>
                <strong>答案:</strong>
                <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.answer}
                </div>
              </div>
            )}
            {selectedResult.contexts && selectedResult.contexts.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <strong>上下文 ({selectedResult.contexts.length} 条):</strong>
                {selectedResult.contexts.map((ctx, idx) => (
                  <div key={idx} style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                    {ctx}
                  </div>
                ))}
              </div>
            )}
            {selectedResult.error && (
              <div style={{ marginBottom: 16 }}>
                <strong>错误信息:</strong>
                <div style={{ padding: 8, background: '#fff2f0', borderRadius: 4, marginTop: 8, color: '#ff4d4f' }}>
                  {selectedResult.error}
                </div>
              </div>
            )}
            {selectedResult.status === 'failed' && (
              <Button type="primary" icon={<ReloadOutlined />} onClick={() => {
                handleRetrySingle(selectedResult.id)
                setDetailModalVisible(false)
              }}>
                重试此条
              </Button>
            )}
            {selectedResult.status === 'success' && selectedResult.ground_truth && (
              <Button icon={<ExclamationCircleOutlined />} onClick={() => {
                setDetailModalVisible(false)
                handleOpenCorrection(selectedResult)
              }}>
                矫正标注
              </Button>
            )}
          </div>
        )}
      </Modal>

      {/* 矫正分析配置Modal */}
      <Modal
        title="矫正标注分析"
        open={correctionModalVisible}
        onCancel={() => setCorrectionModalVisible(false)}
        onOk={handleRunCorrection}
        confirmLoading={correctionLoading}
        okText="开始分析"
      >
        {selectedResult && (
          <div>
            <Alert
              message="矫正标注分析将对比系统回复和标准答案的差异，并验证分片是否支持这些差异"
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
            <div style={{ marginBottom: 16 }}>
              <strong>问题:</strong>
              <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                {selectedResult.question}
              </div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <strong>选择LLM模型:</strong>
              <Select
                style={{ width: '100%', marginTop: 8 }}
                placeholder="选择用于分析差异的LLM模型"
                value={selectedLlmModel}
                onChange={setSelectedLlmModel}
                options={llmModels.map(m => ({ label: m.name, value: m.id }))}
              />
            </div>
          </div>
        )}
      </Modal>

      {/* 矫正结果详情Modal */}
      <Modal
        title="矫正分析结果"
        open={correctionDetailVisible}
        onCancel={() => setCorrectionDetailVisible(false)}
        footer={null}
        width={900}
      >
        {correctionResult && (
          <div>
            {correctionResult.is_doubtful && (
              <Alert
                message="该QA数据存疑"
                description={correctionResult.doubt_reason}
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}
            {!correctionResult.is_doubtful && (
              <Alert
                message="该QA数据正常"
                description={correctionResult.summary}
                type="success"
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}

            <Divider>差异声明</Divider>
            {correctionResult.different_statements.length > 0 ? (
              correctionResult.different_statements.map((diff, idx) => (
                <Card key={idx} size="small" style={{ marginBottom: 8 }}>
                  <Descriptions column={2} size="small">
                    <Descriptions.Item label="声明">{diff.statement}</Descriptions.Item>
                    <Descriptions.Item label="来源">
                      <Tag color={diff.source === 'system' ? 'blue' : 'green'}>
                        {diff.source === 'system' ? '系统回复' : '标准答案'}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="类型">
                      <Tag color={diff.type === 'unique' ? 'orange' : 'red'}>
                        {diff.type === 'unique' ? '独有' : '冲突'}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="证据支持">
                      <Tag color={diff.supported ? 'success' : 'error'}>
                        {diff.supported ? '有证据' : '无证据'}
                      </Tag>
                    </Descriptions.Item>
                  </Descriptions>
                  {diff.verification_question && (
                    <div style={{ marginTop: 8 }}>
                      <strong>验证问题:</strong> {diff.verification_question}
                    </div>
                  )}
                </Card>
              ))
            ) : (
              <div style={{ textAlign: 'center', padding: 16, color: '#999' }}>
                未发现显著差异
              </div>
            )}

            <Divider>证据验证</Divider>
            {correctionResult.evidence_results.length > 0 ? (
              correctionResult.evidence_results.map((evidence, idx) => (
                <Card key={idx} size="small" style={{ marginBottom: 8 }}>
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="声明">{evidence.statement}</Descriptions.Item>
                    <Descriptions.Item label="验证问题">{evidence.question}</Descriptions.Item>
                    <Descriptions.Item label="是否支持">
                      <Tag color={evidence.supported ? 'success' : 'error'}>
                        {evidence.supported ? '支持' : '不支持'}
                      </Tag>
                    </Descriptions.Item>
                  </Descriptions>
                  {evidence.supporting_chunks && evidence.supporting_chunks.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <strong>支持证据 ({evidence.supporting_chunks.length} 条):</strong>
                      {evidence.supporting_chunks.map((chunk, cIdx) => (
                        <div key={cIdx} style={{ padding: 8, background: '#f6ffed', borderRadius: 4, marginTop: 4, border: '1px solid #b7eb8f' }}>
                          {chunk.content}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              ))
            ) : (
              <div style={{ textAlign: 'center', padding: 16, color: '#999' }}>
                无证据验证结果
              </div>
            )}

            <Divider>操作</Divider>
            <Space>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={() => handleConfirmCorrection(true)}
              >
                确认存疑
              </Button>
              <Button
                icon={<CheckCircleOutlined />}
                onClick={() => handleConfirmCorrection(false)}
              >
                标记正常
              </Button>
            </Space>
          </div>
        )}
      </Modal>
    </Card>
  )
}

export default InvocationDetail