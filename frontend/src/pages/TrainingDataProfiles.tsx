// 训练数据画像页面
//
// 目标读者：第一次接触某个数据集的人 —— 打开画像就能看懂
// 「这是什么数据 / 字段怎么分布 / 语言与主题 / 质量如何 / 适合怎么用」。
// 三层信息：1) 规则生成的自然语言摘要（一眼看懂）2) 结构化指标（深入）3) LLM 深度分析（可选）。
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Card, Table, Button, Tag, Modal, Form, Input, Select, message, Space, Progress,
  Tabs, Descriptions, Row, Col, Statistic, Alert, Tooltip, Popconfirm, Drawer, Radio,
} from 'antd'
import {
  PlusOutlined, PlayCircleOutlined, DeleteOutlined, EyeOutlined,
  ReloadOutlined, CloudDownloadOutlined, RobotOutlined,
} from '@ant-design/icons'
import { formatTime } from '@/utils/format'
import {
  getTrainingDataProfiles, createTrainingDataProfile, runTrainingDataProfile,
  deleteTrainingDataProfile, getTrainingDataProfile, getTrainingDataProfileRecords,
  getTrainingDataProfileStatus,
  getUltraDataSamples, importUltraDataSample, getDatasets, getModels,
} from '@/api'
import type { TrainingDataProfile, Dataset, ModelConfig, UltraDataSampleItem } from '@/types'
import { usePollingWhenRunning } from '@/hooks/usePollingWhenRunning'

const LEVEL_COLORS: Record<string, string> = { L1: 'default', L2: 'blue', L3: 'purple', L4: 'gold' }
const GRADE_COLORS: Record<string, string> = {
  excellent: 'green', good: 'blue', acceptable: 'orange', poor: 'red',
}
const GRADE_LABELS: Record<string, string> = {
  excellent: '优秀', good: '良好', acceptable: '一般', poor: '较差',
}
const FORMAT_COLORS: Record<string, string> = {
  sft: 'blue', chat: 'geekblue', preference: 'purple', agent: 'magenta',
  pretrain: 'cyan', qa: 'green', other: 'default',
}

const pct = (v?: number | null) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`)
const num = (v?: number | null) => (v == null ? '-' : v.toLocaleString())

const TrainingDataProfiles: React.FC = () => {
  const [profiles, setProfiles] = useState<TrainingDataProfile[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [llmModels, setLlmModels] = useState<ModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const [detailOpen, setDetailOpen] = useState(false)
  const [detail, setDetail] = useState<TrainingDataProfile | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [records, setRecords] = useState<Array<Record<string, any>>>([])
  const [recordsTotal, setRecordsTotal] = useState(0)
  const [recordsPage, setRecordsPage] = useState(1)
  const [recordsFormat, setRecordsFormat] = useState<string | undefined>()
  const [recordsLoading, setRecordsLoading] = useState(false)

  // UltraData 示例
  const [ultraVisible, setUltraVisible] = useState(false)
  const [ultraSamples, setUltraSamples] = useState<UltraDataSampleItem[]>([])
  const [ultraLoading, setUltraLoading] = useState(false)
  const [importingKey, setImportingKey] = useState<string | null>(null)
  const [ultraLlmMode, setUltraLlmMode] = useState<'off' | 'sample' | 'full'>('off')

  const seqRef = useRef(0)

  const hasRunning = profiles.some(p => p.status === 'running' || p.status === 'pending')

  const fetchProfiles = async () => {
    const seq = ++seqRef.current
    setLoading(true)
    try {
      const data = await getTrainingDataProfiles()
      if (seq === seqRef.current) setProfiles(data)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }

  const fetchMeta = async () => {
    try {
      const [ds, ms] = await Promise.all([getDatasets(), getModels('llm')])
      setDatasets(ds)
      setLlmModels(ms)
    } catch {
      // 元数据加载失败不阻塞列表
    }
  }

  useEffect(() => {
    fetchProfiles()
    fetchMeta()
  }, [])

  usePollingWhenRunning(hasRunning, fetchProfiles, 5000)

  const openDetail = async (id: string) => {
    setDetailOpen(true)
    setDetailLoading(true)
    setRecordsPage(1)
    setRecordsFormat(undefined)
    try {
      const data = await getTrainingDataProfile(id)
      setDetail(data)
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    if (!detail) return
    const load = async () => {
      setRecordsLoading(true)
      try {
        const res = await getTrainingDataProfileRecords(detail.id, {
          skip: (recordsPage - 1) * 20,
          limit: 20,
          format: recordsFormat,
        })
        setRecords(res.records)
        setRecordsTotal(res.total)
      } finally {
        setRecordsLoading(false)
      }
    }
    load()
  }, [detail?.id, recordsPage, recordsFormat])

  usePollingWhenRunning(detail?.status === 'running', async () => {
    if (!detail) return
    const st = await getTrainingDataProfileStatus(detail.id)
    setDetail(d => (d ? { ...d, status: st.status as any, progress: st.progress, error: st.error } : d))
    if (st.status === 'completed') {
      const fresh = await getTrainingDataProfile(detail.id)
      setDetail(fresh)
      fetchProfiles()
    }
  }, 4000, [detail?.id])

  const onCreate = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const profile = await createTrainingDataProfile(values)
      setModalVisible(false)
      form.resetFields()
      message.success('画像已创建' + (profile.llm_mode !== 'off' ? '，LLM 分析进行中' : ''))
      fetchProfiles()
      openDetail(profile.id)
    } finally {
      setSaving(false)
    }
  }

  const onRerun = async (profile: TrainingDataProfile) => {
    await runTrainingDataProfile(profile.id)
    message.success('已重新计算')
    fetchProfiles()
  }

  const onDelete = async (id: string) => {
    await deleteTrainingDataProfile(id)
    message.success('已删除')
    fetchProfiles()
  }

  const openUltra = async () => {
    setUltraVisible(true)
    setUltraLoading(true)
    try {
      const res = await getUltraDataSamples()
      setUltraSamples(res.items)
    } catch {
      message.error('样例清单加载失败')
    } finally {
      setUltraLoading(false)
    }
  }

  const onImportUltra = async (sample: string) => {
    setImportingKey(sample)
    try {
      const res = await importUltraDataSample({ sample, llm_mode: ultraLlmMode })
      message.success(`已导入 ${res.imported} 条并生成画像`)
      fetchProfiles()
      setUltraVisible(false)
      openDetail(res.profile.id as string)
    } finally {
      setImportingKey(null)
    }
  }

  const columns = [
    {
      title: '名称', dataIndex: 'name', key: 'name',
      render: (_: any, p: TrainingDataProfile) => (
        <a onClick={() => openDetail(p.id)}>{p.name}</a>
      ),
    },
    {
      title: '主格式', dataIndex: 'format', key: 'format',
      render: (f?: string) => f ? <Tag color={FORMAT_COLORS[f]}>{f}</Tag> : '-',
    },
    {
      title: '层级', dataIndex: 'level', key: 'level',
      render: (l?: string) => l ? <Tag color={LEVEL_COLORS[l]}>{l}</Tag> : '-',
    },
    { title: '样本数', dataIndex: 'total_samples', key: 'total_samples', render: num },
    {
      title: '重复率', dataIndex: 'duplicate_rate', key: 'duplicate_rate',
      render: (v: number) => pct(v),
    },
    {
      title: '质量', key: 'quality',
      render: (_: any, p: TrainingDataProfile) => {
        const grade = p.quality?.grade
        if (!grade) return '-'
        return <Tag color={GRADE_COLORS[grade]}>{GRADE_LABELS[grade] ?? grade} {p.quality?.score?.toFixed(2)}</Tag>
      },
    },
    {
      title: '状态', key: 'status',
      render: (_: any, p: TrainingDataProfile) => (
        <Space>
          <Tag color={p.status === 'completed' ? 'green' : p.status === 'failed' ? 'red' : 'processing'}>
            {p.status === 'completed' ? '完成' : p.status === 'failed' ? '失败' : p.status === 'running' ? '运行中' : '等待'}
          </Tag>
          {(p.status === 'running' || p.status === 'pending') && (
            <Progress percent={p.progress || 0} size="small" style={{ width: 80 }} />
          )}
          {p.llm_mode !== 'off' && (
            <Tooltip title={`LLM ${p.llm_mode === 'full' ? '逐条' : '抽样'}分析`}>
              <Tag color="orange" icon={<RobotOutlined />}>{p.llm_mode}</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v ? formatTime(v) : '-' },
    {
      title: '操作', key: 'actions',
      render: (_: any, p: TrainingDataProfile) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(p.id)}>详情</Button>
          <Button size="small" icon={<PlayCircleOutlined />} disabled={p.status === 'running'} onClick={() => onRerun(p)}>重算</Button>
          <Popconfirm title="删除该画像？数据集与样本不受影响。" onConfirm={() => onDelete(p.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Card
        title="训练数据画像"
        extra={
          <Space>
            <Button icon={<CloudDownloadOutlined />} onClick={openUltra}>UltraData 示例</Button>
            <Button icon={<ReloadOutlined />} onClick={fetchProfiles}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>生成画像</Button>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="画像 = 规则统计 + 自然语言摘要，一眼看懂数据集；可选 LLM 抽样/逐条深度分析"
          description="数据通过「数据集」页上传导入后，在这里对数据集生成画像。LLM 分析需要模型管理里已配置可用的 LLM。"
        />
        <Table
          rowKey="id"
          loading={loading}
          dataSource={profiles}
          columns={columns}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* 创建画像 */}
      <Modal
        title="为数据集生成画像"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={onCreate}
        confirmLoading={saving}
        width={560}
      >
        <Form form={form} layout="vertical" initialValues={{ llm_mode: 'off', llm_sample_size: 40 }}>
          <Form.Item name="dataset_id" label="数据集" rules={[{ required: true, message: '请选择数据集' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择已导入的数据集"
              options={datasets.map(d => ({ value: d.id, label: `${d.name}（${d.record_count} 条）` }))}
            />
          </Form.Item>
          <Form.Item name="name" label="画像名称（可选）">
            <Input placeholder="默认用数据集名称" />
          </Form.Item>
          <Form.Item name="llm_mode" label="LLM 深度分析">
            <Radio.Group
              options={[
                { value: 'off', label: '关闭（仅规则画像，免费即时）' },
                { value: 'sample', label: '抽样分析（均匀抽 N 条过 LLM，快）' },
                { value: 'full', label: '逐条分析（全量分批过 LLM，准但有成本）' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.llm_mode !== b.llm_mode}>
            {({ getFieldValue }) => getFieldValue('llm_mode') !== 'off' && (
              <>
                <Form.Item name="llm_model_id" label="分析用 LLM（不选则用默认模型）">
                  <Select
                    allowClear
                    placeholder="默认取系统默认 LLM"
                    options={llmModels.map(m => ({ value: m.id, label: m.name }))}
                  />
                </Form.Item>
                <Form.Item name="llm_sample_size" label="抽样条数（仅抽样模式）">
                  <Input type="number" min={5} max={200} />
                </Form.Item>
              </>
            )}
          </Form.Item>
        </Form>
      </Modal>

      {/* UltraData 示例 */}
      <Drawer
        title="UltraData 真实样例（一键导入 + 画像）"
        open={ultraVisible}
        onClose={() => setUltraVisible(false)}
        width={640}
      >
        <Space style={{ marginBottom: 16 }}>
          <span>导入时的 LLM 分析：</span>
          <Select
            value={ultraLlmMode}
            onChange={v => setUltraLlmMode(v)}
            style={{ width: 220 }}
            options={[
              { value: 'off', label: '关闭' },
              { value: 'sample', label: '抽样分析' },
              { value: 'full', label: '逐条分析' },
            ]}
          />
        </Space>
        <Table
          rowKey="key"
          loading={ultraLoading}
          dataSource={ultraSamples}
          pagination={false}
          columns={[
            { title: '数据集', dataIndex: 'title' },
            {
              title: '层级', dataIndex: 'level',
              render: (l: string) => <Tag color={LEVEL_COLORS[l] ?? 'default'}>{l}</Tag>,
            },
            { title: '格式', dataIndex: 'format', render: (f?: string) => f || '-' },
            {
              title: '操作', key: 'actions',
              render: (_: any, s: UltraDataSampleItem) => (
                <Button
                  size="small"
                  type="primary"
                  loading={importingKey === s.key}
                  disabled={!s.available}
                  onClick={() => onImportUltra(s.key)}
                >
                  导入并画像
                </Button>
              ),
            },
          ]}
        />
      </Drawer>

      {/* 画像详情 */}
      <Drawer
        title={detail ? detail.name : '画像详情'}
        open={detailOpen}
        onClose={() => { setDetailOpen(false); setDetail(null) }}
        width={960}
        loading={detailLoading}
      >
        {detail && <ProfileDetail
          profile={detail}
          records={records}
          recordsTotal={recordsTotal}
          recordsPage={recordsPage}
          recordsFormat={recordsFormat}
          recordsLoading={recordsLoading}
          onPage={setRecordsPage}
          onFormat={setRecordsFormat}
        />}
      </Drawer>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 详情内容：摘要 → 指标 → 字段 → 分类 → 质量 → 样本 → LLM → 明细
// ---------------------------------------------------------------------------
interface DetailProps {
  profile: TrainingDataProfile
  records: Array<Record<string, any>>
  recordsTotal: number
  recordsPage: number
  recordsFormat?: string
  recordsLoading: boolean
  onPage: (p: number) => void
  onFormat: (f?: string) => void
}

const ProfileDetail: React.FC<DetailProps> = ({
  profile, records, recordsTotal, recordsPage, recordsFormat, recordsLoading, onPage, onFormat,
}) => {
  const ov = profile.overview
  const cls = profile.classification
  const q = profile.quality
  const llm = profile.llm_analysis

  const formatOptions = useMemo(
    () => (cls?.formats ?? []).map(f => ({ value: f.key, label: f.label })),
    [cls]
  )

  return (
    <Tabs
      items={[
        {
          key: 'overview',
          label: '总览',
          children: (
            <>
              {profile.summary && (
                <Card size="small" title="一眼看懂" style={{ marginBottom: 16 }}>
                  <p style={{ fontSize: 14, lineHeight: 1.9, margin: 0 }}>{profile.summary}</p>
                </Card>
              )}
              {profile.status === 'failed' && (
                <Alert type="error" showIcon message="画像生成失败" description={profile.error} style={{ marginBottom: 16 }} />
              )}
              {profile.sampled && (
                <Alert type="warning" showIcon message="样本量过大，统计基于前若干条抽样" style={{ marginBottom: 16 }} />
              )}
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}><Statistic title="样本总数" value={ov?.total ?? profile.total_samples} /></Col>
                <Col span={6}><Statistic title="去重后" value={ov?.unique ?? profile.unique_samples} /></Col>
                <Col span={6}><Statistic title="重复率" value={pct(ov?.duplicate_rate ?? profile.duplicate_rate)} /></Col>
                <Col span={6}>
                  <Statistic
                    title="层级建议"
                    valueRender={<Tag color={LEVEL_COLORS[profile.level ?? '']}>{profile.level}</Tag> as any}
                  />
                </Col>
              </Row>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}><Statistic title="长度中位数" value={ov ? `${ov.char_length.p50} 字符` : '-'} /></Col>
                <Col span={6}><Statistic title="平均 tokens/条" value={ov ? num(ov.tokens.avg) : '-'} /></Col>
                <Col span={6}><Statistic title="估算总 tokens" value={ov ? num(ov.tokens.total) : '-'} /></Col>
                <Col span={6}>
                  <Statistic
                    title="质量评级"
                    valueRender={<Tag color={GRADE_COLORS[q?.grade ?? '']}>{GRADE_LABELS[q?.grade ?? ''] ?? q?.grade} {q?.score?.toFixed(2)}</Tag> as any}
                  />
                </Col>
              </Row>
              {cls && (
                <Card size="small" title="格式 / 语言 / 主题分布">
                  <div style={{ marginBottom: 8 }}>
                    <strong>格式：</strong>
                    {cls.formats.map(f => (
                      <Tag key={f.key} color={FORMAT_COLORS[f.key]} style={{ marginBottom: 4 }}>
                        {f.label} {f.count.toLocaleString()}（{pct(f.ratio)}）
                      </Tag>
                    ))}
                  </div>
                  <div style={{ marginBottom: 8 }}>
                    <strong>语言：</strong>
                    {cls.languages.map(l => (
                      <Tag key={l.key} style={{ marginBottom: 4 }}>
                        {l.key === 'zh' ? '中文' : l.key === 'en' ? '英文' : l.key === 'mixed' ? '中英混合' : '其他'}
                        {' '}{l.count.toLocaleString()}（{pct(l.ratio)}）
                      </Tag>
                    ))}
                  </div>
                  {(cls.top_domains ?? cls.domains).length > 0 && (
                    <div>
                      <strong>主题：</strong>
                      {(cls.top_domains ?? cls.domains).slice(0, 8).map(d => (
                        <Tag key={d.key} color="geekblue" style={{ marginBottom: 4 }}>
                          {d.key} {pct(d.ratio)}
                        </Tag>
                      ))}
                    </div>
                  )}
                  {cls.level_reason && (
                    <div style={{ marginTop: 8, color: '#666' }}>
                      层级依据：{cls.level_reason}
                    </div>
                  )}
                </Card>
              )}
            </>
          ),
        },
        {
          key: 'schema',
          label: '字段画像',
          children: (
            <Table
              rowKey="name"
              dataSource={profile.schema_profile ?? []}
              pagination={false}
              size="small"
              columns={[
                { title: '字段', dataIndex: 'name', render: (n: string) => <code>{n}</code> },
                {
                  title: '覆盖率', dataIndex: 'coverage', width: 100,
                  render: (v: number) => (
                    <Tooltip title={`${(v * 100).toFixed(1)}% 的样本该字段非空`}>
                      <span>{pct(v)}</span>
                    </Tooltip>
                  ),
                },
                {
                  title: '类型', dataIndex: 'types',
                  render: (t: Record<string, number>) => Object.entries(t).map(([k, c]) => (
                    <Tag key={k}>{k}×{c}</Tag>
                  )),
                },
                {
                  title: '值分布 / 统计', key: 'dist',
                  render: (_: any, f: any) => {
                    if (f.values) {
                      return f.values.slice(0, 5).map((v: any) => (
                        <div key={String(v.value)} style={{ fontSize: 12 }}>
                          <code>{String(v.value).slice(0, 30)}</code> ×{v.count}（{pct(v.ratio)}）
                        </div>
                      ))
                    }
                    const bits: string[] = []
                    if (f.numeric) bits.push(`min ${f.numeric.min} / mean ${f.numeric.mean} / max ${f.numeric.max}`)
                    if (f.text) bits.push(`平均 ${f.text.avg_len} 字符 / 最长 ${f.text.max_len}`)
                    return bits.length ? bits.join('；') : '-'
                  },
                },
                {
                  title: '示例', dataIndex: 'example', ellipsis: true,
                  render: (e?: string) => e ? <span style={{ color: '#888' }}>{e}</span> : '-',
                },
              ]}
            />
          ),
        },
        {
          key: 'quality',
          label: '质量',
          children: q ? (
            <>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}><Statistic title="综合分" value={q.score.toFixed(2)} suffix="/ 1.00" /></Col>
                <Col span={6}><Statistic title="空文本率" value={pct(q.empty_rate)} /></Col>
                <Col span={6}><Statistic title="过长率(>8192字符)" value={pct(q.overlong_rate)} /></Col>
                <Col span={6}><Statistic title="过短率(<16字符)" value={pct(q.too_short_rate)} /></Col>
              </Row>
              {q.score_mean != null && (
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={6}><Statistic title="自带分均值" value={q.score_mean.toFixed(3)} /></Col>
                  <Col span={6}><Statistic title="P50" value={q.score_p50?.toFixed(3) ?? '-'} /></Col>
                  <Col span={6}><Statistic title="Min" value={q.score_min?.toFixed(3) ?? '-'} /></Col>
                  <Col span={6}><Statistic title="Max" value={q.score_max?.toFixed(3) ?? '-'} /></Col>
                </Row>
              )}
              <Card size="small" title="发现的问题">
                {q.issues.map((issue, i) => (
                  <Alert key={i} type={issue.includes('未发现') ? 'success' : 'warning'} message={issue} style={{ marginBottom: 8 }} />
                ))}
              </Card>
            </>
          ) : <Alert type="info" message="尚无质量数据" />,
        },
        {
          key: 'samples',
          label: '样本预览',
          children: (
            <>
              {(profile.samples ?? []).map((s, i) => (
                <Card key={i} size="small" style={{ marginBottom: 8 }} title={`样本 ${i + 1}`}>
                  <Descriptions column={1} size="small">
                    {Object.entries(s).map(([k, v]) => (
                      <Descriptions.Item key={k} label={<code>{k}</code>}>
                        <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{String(v)}</span>
                      </Descriptions.Item>
                    ))}
                  </Descriptions>
                </Card>
              ))}
              {!profile.samples?.length && <Alert type="info" message="无预览样本" />}
            </>
          ),
        },
        {
          key: 'llm',
          label: (
            <span><RobotOutlined /> LLM 分析{profile.llm_mode !== 'off' ? `（${profile.llm_mode}）` : ''}</span>
          ),
          children: (
            <>
              {profile.llm_mode === 'off' && (
                <Alert type="info" showIcon message="未启用 LLM 分析" description="可在列表点「重算」并选择抽样/逐条模式开启。" />
              )}
              {llm?.status === 'skipped' && (
                <Alert type="warning" showIcon message="LLM 分析已跳过" description={llm.reason} />
              )}
              {llm?.status === 'failed' && (
                <Alert type="error" showIcon message="LLM 分析失败" description={llm.error} />
              )}
              {llm?.status === 'completed' && (
                <>
                  <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
                    <Descriptions.Item label="是什么">{llm.what_is_it}</Descriptions.Item>
                    <Descriptions.Item label="内容概述">{llm.content_summary}</Descriptions.Item>
                    <Descriptions.Item label="风格/结构">{llm.style_and_format}</Descriptions.Item>
                    <Descriptions.Item label="质量印象">{llm.quality_impression}</Descriptions.Item>
                    <Descriptions.Item label="优势">
                      {(llm.strengths ?? []).map((s, i) => <Tag key={i} color="green">{s}</Tag>)}
                    </Descriptions.Item>
                    <Descriptions.Item label="不足">
                      {(llm.weaknesses ?? []).map((s, i) => <Tag key={i} color="orange">{s}</Tag>)}
                    </Descriptions.Item>
                    <Descriptions.Item label="建议用途">
                      {(llm.suggested_uses ?? []).map((s, i) => <Tag key={i} color="blue">{s}</Tag>)}
                    </Descriptions.Item>
                    <Descriptions.Item label="风险">
                      {(llm.risks ?? []).length
                        ? (llm.risks ?? []).map((s, i) => <Tag key={i} color="red">{s}</Tag>)
                        : <span>-</span>}
                    </Descriptions.Item>
                    {llm.notes && <Descriptions.Item label="备注">{llm.notes}</Descriptions.Item>}
                    <Descriptions.Item label="分析样本数">
                      {num(llm.analyzed_records)}
                      {llm.truncated && <Tag color="orange" style={{ marginLeft: 8 }}>超出上限已截断</Tag>}
                    </Descriptions.Item>
                  </Descriptions>
                  {llm.topic_counts && Object.keys(llm.topic_counts).length > 0 && (
                    <Card size="small" title="全量标注 · 主题分布" style={{ marginBottom: 16 }}>
                      {Object.entries(llm.topic_counts).map(([topic, count]) => (
                        <Tag key={topic} color="geekblue" style={{ marginBottom: 4 }}>
                          {topic} ×{count}
                        </Tag>
                      ))}
                    </Card>
                  )}
                  {llm.quality_hist && (
                    <Card size="small" title="全量标注 · 质量分分布(1-5)" style={{ marginBottom: 16 }}>
                      <Row gutter={8}>
                        {Object.entries(llm.quality_hist).map(([score, count]) => (
                          <Col span={4} key={score}>
                            <Statistic title={`${score} 分`} value={count} />
                          </Col>
                        ))}
                      </Row>
                    </Card>
                  )}
                  {!!llm.issues?.length && (
                    <Card size="small" title={`标注发现的问题（${llm.issues.length}）`}>
                      {llm.issues.slice(0, 20).map((issue, i) => (
                        <Alert key={i} type="warning" message={issue} style={{ marginBottom: 6 }} />
                      ))}
                    </Card>
                  )}
                </>
              )}
              {profile.llm_mode !== 'off' && !llm && profile.status === 'running' && (
                <Alert type="info" showIcon message="LLM 分析进行中…" />
              )}
            </>
          ),
        },
        {
          key: 'records',
          label: `样本明细（${recordsTotal}）`,
          children: (
            <>
              <Space style={{ marginBottom: 12 }}>
                <Select
                  allowClear
                  placeholder="按格式过滤"
                  style={{ width: 200 }}
                  value={recordsFormat}
                  onChange={v => { onFormat(v); onPage(1) }}
                  options={formatOptions}
                />
              </Space>
              <Table
                rowKey={(r, i) => String(r.seq ?? i)}
                loading={recordsLoading}
                dataSource={records}
                pagination={{
                  current: recordsPage, pageSize: 20, total: recordsTotal,
                  onChange: onPage, showSizeChanger: false,
                }}
                size="small"
                expandable={{
                  expandedRowRender: r => (
                    <pre style={{ maxHeight: 320, overflow: 'auto', fontSize: 12, margin: 0 }}>
                      {JSON.stringify(r.payload ?? r, null, 2)}
                    </pre>
                  ),
                }}
                columns={[
                  { title: '#', dataIndex: 'seq', width: 60 },
                  {
                    title: '格式', dataIndex: 'format', width: 100,
                    render: (f: string) => <Tag color={FORMAT_COLORS[f]}>{f}</Tag>,
                  },
                  { title: '语言', dataIndex: 'language', width: 70 },
                  {
                    title: '标签', dataIndex: 'labels',
                    render: (labels?: string[]) => (labels ?? []).slice(0, 3).map(l => <Tag key={l}>{l}</Tag>),
                  },
                  { title: '长度', dataIndex: 'char_length', width: 80 },
                  {
                    title: '分数', dataIndex: 'score', width: 70,
                    render: (s?: number) => s == null ? '-' : s.toFixed(2),
                  },
                ]}
              />
            </>
          ),
        },
      ]}
    />
  )
}

export default TrainingDataProfiles
