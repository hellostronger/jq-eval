import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Button, Tag, Space, Progress, Statistic, Row, Col, Spin, Modal } from 'antd'
import { ArrowLeftOutlined, EyeOutlined } from '@ant-design/icons'
import { getDocExplanationEvaluation, getDocExplanationEvalResults } from '@/api'
import type { DocExplanationEvaluation, DocExplanationEvalResult } from '@/types'

const DocExplanationEvalDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [evaluation, setEvaluation] = useState<DocExplanationEvaluation | null>(null)
  const [results, setResults] = useState<DocExplanationEvalResult[]>([])
  const [loading, setLoading] = useState(false)
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [selectedResult, setSelectedResult] = useState<DocExplanationEvalResult | null>(null)

  const fetchData = async () => {
    if (!id) return
    setLoading(true)
    try {
      const [evalData, resultsData] = await Promise.all([
        getDocExplanationEvaluation(id),
        getDocExplanationEvalResults(id),
      ])
      setEvaluation(evalData)
      setResults(resultsData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [id])

  const handleViewDetail = (result: DocExplanationEvalResult) => {
    setSelectedResult(result)
    setDetailModalVisible(true)
  }

  const getScoreColor = (score: number) => {
    if (score >= 8) return 'success'
    if (score >= 5) return 'warning'
    return 'error'
  }

  const formatScore = (score: string | number | undefined, decimals: number = 1): string => {
    if (score === undefined || score === null) return '-'
    const num = typeof score === 'string' ? parseFloat(score) : score
    if (isNaN(num)) return '-'
    return num.toFixed(decimals)
  }

  const columns = [
    {
      title: '文档标题',
      dataIndex: 'document_title',
      key: 'document_title',
      ellipsis: true,
    },
    {
      title: '解释内容',
      dataIndex: 'explanation',
      key: 'explanation',
      ellipsis: true,
      width: 200,
      render: (text: string) => text?.slice(0, 50) + (text?.length > 50 ? '...' : ''),
    },
    {
      title: '完整性',
      dataIndex: ['scores', 'completeness'],
      key: 'completeness',
      render: (score: string | number) => (
        <Tag color={getScoreColor(typeof score === 'string' ? parseFloat(score) : score)}>
          {formatScore(score)}
        </Tag>
      ),
    },
    {
      title: '准确性',
      dataIndex: ['scores', 'accuracy'],
      key: 'accuracy',
      render: (score: string | number) => (
        <Tag color={getScoreColor(typeof score === 'string' ? parseFloat(score) : score)}>
          {formatScore(score)}
        </Tag>
      ),
    },
    {
      title: '信息遗漏',
      dataIndex: ['scores', 'info_missing'],
      key: 'info_missing',
      render: (score: string | number) => (
        <Tag color={getScoreColor(typeof score === 'string' ? parseFloat(score) : score)}>
          {formatScore(score)}
        </Tag>
      ),
    },
    {
      title: '解释错误',
      dataIndex: ['scores', 'explanation_error'],
      key: 'explanation_error',
      render: (score: string | number) => (
        <Tag color={getScoreColor(typeof score === 'string' ? parseFloat(score) : score)}>
          {formatScore(score)}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: DocExplanationEvalResult) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => handleViewDetail(record)}
        >
          详情
        </Button>
      ),
    },
  ]

  if (!evaluation) {
    return <Spin />
  }

  const summary = evaluation.summary || {}

  return (
    <Card
      title={
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/doc-explanation-evaluations')}>
            返回
          </Button>
          <span>{evaluation.name}</span>
          <Tag color={evaluation.status === 'completed' ? 'success' : 'processing'}>
            {evaluation.status}
          </Tag>
          <Progress
            percent={evaluation.progress}
            size="small"
            style={{ width: 100 }}
          />
        </Space>
      }
    >
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Statistic
            title="总体得分"
            value={formatScore(summary.overall_score, 2)}
            suffix="/ 10"
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="完整性均值"
            value={formatScore(summary.completeness?.mean, 2)}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="准确性均值"
            value={formatScore(summary.accuracy?.mean, 2)}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="信息遗漏均值"
            value={formatScore(summary.info_missing?.mean, 2)}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="解释错误均值"
            value={formatScore(summary.explanation_error?.mean, 2)}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="评估数量"
            value={results.length}
          />
        </Col>
      </Row>

      <Table
        dataSource={results}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="评估结果详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={800}
      >
        {selectedResult && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <strong>文档标题:</strong>
              <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                {selectedResult.document_title}
              </div>
            </div>
            {selectedResult.document_content && (
              <div style={{ marginBottom: 16 }}>
                <strong>文档内容:</strong>
                <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.document_content}
                </div>
              </div>
            )}
            {selectedResult.explanation && (
              <div style={{ marginBottom: 16 }}>
                <strong>解释内容:</strong>
                <div style={{ padding: 8, background: '#e6f7ff', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.explanation}
                </div>
              </div>
            )}
            <div style={{ marginBottom: 16 }}>
              <strong>评估得分:</strong>
              <Row gutter={8} style={{ marginTop: 8 }}>
                <Col span={6}>
                  <Statistic
                    title="完整性"
                    value={formatScore(selectedResult.scores?.completeness)}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="准确性"
                    value={formatScore(selectedResult.scores?.accuracy)}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="信息遗漏"
                    value={formatScore(selectedResult.scores?.info_missing)}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="解释错误"
                    value={formatScore(selectedResult.scores?.explanation_error)}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
              </Row>
            </div>
            {selectedResult.scores?.analysis && (
              <div style={{ marginBottom: 16 }}>
                <strong>分析说明:</strong>
                <div style={{ padding: 8, background: '#fff2e8', borderRadius: 4, marginTop: 8 }}>
                  {selectedResult.scores.analysis}
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </Card>
  )
}

export default DocExplanationEvalDetail