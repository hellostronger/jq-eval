import React, { useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Collapse, Descriptions, Form, Input, InputNumber, Modal, Progress,
  Radio, Select, Space, Switch, Tag, Typography, Upload, message,
} from 'antd'
import { InboxOutlined, LinkOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import {
  getIngestCapabilities, getRemoteKnowledgeBases, getModels,
  startApiIngest, getApiIngestTask,
} from '@/api'
import type { IngestCapabilities, ApiIngestTask } from '@/api'
import type { ModelConfig, RAGSystem } from '@/types'

const { Text, Link } = Typography

interface Props {
  system: RAGSystem | null
  open: boolean
  onClose: () => void
  onCompleted?: () => void
}

const STAGE_TEXT: Record<string, string> = {
  queued: '排队中',
  ensuring_knowledge_base: '准备知识库',
  uploading: '上传原始文档',
  triggering_parse: '触发解析',
  parsing: '等待解析完成',
  fetching_chunks: '拉取远端分片',
  building_questions: '生成/导入问答',
  dispatching_invocation: '发起调用批次',
  completed: '完成',
}

const ApiIngestModal: React.FC<Props> = ({ system, open, onClose, onCompleted }) => {
  const [caps, setCaps] = useState<IngestCapabilities | null>(null)
  const [capsLoading, setCapsLoading] = useState(false)
  const [kbs, setKbs] = useState<{ id: string; name: string }[]>([])
  const [kbMode, setKbMode] = useState<'existing' | 'new' | 'manual'>('existing')
  const [llmModels, setLlmModels] = useState<ModelConfig[]>([])
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([])
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [task, setTask] = useState<ApiIngestTask | null>(null)
  const [form] = Form.useForm()
  const timerRef = useRef<number | null>(null)

  const stopPolling = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  const loadSystem = async () => {
    if (!system) return
    setCapsLoading(true)
    try {
      const info = await getIngestCapabilities(system.id)
      setCaps(info.capabilities)
      if (info.capabilities.list_knowledge_bases) {
        try {
          const data = await getRemoteKnowledgeBases(system.id)
          setKbs(data.items)
        } catch {
          setKbs([])
        }
      }
      setKbMode(info.capabilities.list_knowledge_bases ? 'existing' : 'manual')
      form.setFieldsValue({
        dataset_name: `${system.name} API 入库`,
        test_size: 10,
        auto_generate: true,
        auto_invoke: false,
        kb_id: undefined,
        new_kb_name: undefined,
        space_id: system.connection_config?.space_id || '',
      })
    } finally {
      setCapsLoading(false)
    }
  }

  useEffect(() => {
    if (!open) {
      stopPolling()
      return
    }
    setTask(null)
    setFileList([])
    setKbs([])
    form.resetFields()
    loadSystem()
    getModels('llm').then(setLlmModels).catch(() => setLlmModels([]))
    getModels('embedding').then(setEmbeddingModels).catch(() => setEmbeddingModels([]))
    return stopPolling
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, system?.id])

  const poll = (taskId: string) => {
    stopPolling()
    timerRef.current = window.setInterval(async () => {
      try {
        const latest = await getApiIngestTask(taskId)
        setTask(latest)
        if (latest.status === 'completed' || latest.status === 'failed') {
          stopPolling()
          if (latest.status === 'completed') {
            message.success('入库完成，评测数据集已生成')
            onCompleted?.()
          } else {
            message.error(latest.error || '入库失败')
          }
        }
      } catch {
        // 错误已由拦截器提示；保持轮询，避免一次网络抖动就断掉
      }
    }, 2500)
  }

  const submit = async () => {
    if (!system) return
    if (fileList.length === 0) {
      message.warning('请至少选择一个文件')
      return
    }
    const values = await form.validateFields()
    if (kbMode === 'existing' && !values.kb_id) {
      message.warning('请选择知识库，或切换为新建')
      return
    }
    if (kbMode === 'new' && !values.new_kb_name) {
      message.warning('请填写新知识库名称')
      return
    }
    if (kbMode === 'manual' && !values.kb_id) {
      message.warning('请输入被测系统的知识库 ID')
      return
    }

    const formData = new FormData()
    fileList.forEach((file) => {
      if (file.originFileObj) formData.append('files', file.originFileObj)
    })
    if (values.dataset_name) formData.append('dataset_name', values.dataset_name)
    if (kbMode === 'existing' || kbMode === 'manual') {
      formData.append('kb_id', values.kb_id)
    }
    if (kbMode === 'new') {
      formData.append('new_kb_name', values.new_kb_name)
    }
    if (values.space_id) formData.append('space_id', values.space_id)
    formData.append('test_size', String(values.test_size ?? 10))
    formData.append('auto_generate', String(Boolean(values.auto_generate)))
    formData.append('auto_invoke', String(Boolean(values.auto_invoke)))
    if (values.llm_model_id) formData.append('llm_model_id', values.llm_model_id)
    if (values.embedding_model_id) formData.append('embedding_model_id', values.embedding_model_id)

    setSubmitting(true)
    try {
      const created = await startApiIngest(system.id, formData)
      setTask(created)
      poll(created.id)
      message.success('入库任务已提交')
    } catch {
      // 错误已由拦截器提示
    } finally {
      setSubmitting(false)
    }
  }

  const running = task?.status === 'pending' || task?.status === 'running'
  const canListKb = Boolean(caps?.list_knowledge_bases)
  const canCreateKb = Boolean(caps?.create_knowledge_base)

  return (
    <Modal
      title={`API 全链路入库 - ${system?.connection_config?.display_name || system?.name || ''}`}
      open={open}
      onCancel={() => { stopPolling(); onClose() }}
      width={760}
      footer={[
        <Button key="close" onClick={() => { stopPolling(); onClose() }}>关闭</Button>,
        <Button key="submit" type="primary" loading={submitting} disabled={running} onClick={submit}>
          开始入库
        </Button>,
      ]}
    >
      {caps && (
        <Alert
          type={caps.verified ? 'success' : 'warning'}
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <Space>
              <span>{caps.verified ? '已在本地部署实测' : '按官方文档实现，尚未实测'}</span>
              {caps.docs_url && (
                <Link href={caps.docs_url} target="_blank">
                  <LinkOutlined /> 接口文档
                </Link>
              )}
            </Space>
          }
          description={
            <div>
              <div>{caps.notes}</div>
              <Space size={4} wrap style={{ marginTop: 6 }}>
                <Tag color={caps.upload_documents ? 'green' : 'default'}>上传</Tag>
                <Tag color={caps.parse_documents ? 'green' : 'default'}>触发解析</Tag>
                <Tag color={caps.list_chunks ? 'green' : 'default'}>拉取分片</Tag>
                <Tag color={caps.create_chat ? 'green' : 'default'}>建会话</Tag>
                <Tag color={caps.ask ? 'green' : 'default'}>问答</Tag>
              </Space>
            </div>
          }
        />
      )}

      {!task && (
        <Form form={form} labelCol={{ span: 5 }} disabled={capsLoading}>
          {canListKb && (
            <Form.Item label="知识库">
              <Radio.Group value={kbMode} onChange={(e) => setKbMode(e.target.value)}>
                <Radio.Button value="existing">使用已有</Radio.Button>
                {canCreateKb && <Radio.Button value="new">新建</Radio.Button>}
              </Radio.Group>
            </Form.Item>
          )}

          {kbMode === 'existing' && canListKb && (
            <Form.Item name="kb_id" label="选择知识库" rules={[{ required: true, message: '请选择知识库' }]}>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择被测系统中的知识库"
                options={kbs.map((kb) => ({ value: kb.id, label: `${kb.name} (${kb.id})` }))}
              />
            </Form.Item>
          )}

          {kbMode === 'new' && canCreateKb && (
            <>
              <Form.Item name="new_kb_name" label="新知识库名称" rules={[{ required: true }]}>
                <Input placeholder="例如：jq-eval 评测知识库" />
              </Form.Item>
              {system?.system_type === 'coze' && (
                <Form.Item name="space_id" label="Coze Space ID" rules={[{ required: true, message: 'Coze 建库需要 space_id' }]}>
                  <Input placeholder="空间 URL /w/{space_id}" />
                </Form.Item>
              )}
            </>
          )}

          {kbMode === 'manual' && (
            <Form.Item name="kb_id" label="知识库 ID" rules={[{ required: true, message: '请填写知识库 ID' }]}>
              <Input placeholder="被测系统的 dataset_id / 知识库 ID" />
            </Form.Item>
          )}

          <Form.Item label="原始文档" required>
            <Upload.Dragger
              multiple
              fileList={fileList}
              beforeUpload={() => false}
              onChange={({ fileList: next }) => setFileList(next)}
              accept=".pdf,.docx,.doc,.txt,.md,.html,.csv,.xlsx,.xls"
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽文件到此处</p>
              <p className="ant-upload-hint">
                jq-eval 会先把原始文件传到被测系统，等它完成解析后再拉取真实分片生成问答。
              </p>
            </Upload.Dragger>
          </Form.Item>

          <Collapse
            size="small"
            items={[{
              key: 'advanced',
              label: '评测数据集与问答生成',
              children: (
                <>
                  <Form.Item name="dataset_name" label="数据集名称">
                    <Input placeholder="留空自动生成" />
                  </Form.Item>
                  <Form.Item name="auto_generate" label="生成问答" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="llm_model_id"
                    label="生成用 LLM"
                    tooltip="关闭「生成问答」时可不填"
                  >
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      options={llmModels.map((m) => ({
                        value: m.id,
                        label: `${m.name} (${m.provider || ''} ${m.model_name || ''})`,
                      }))}
                    />
                  </Form.Item>
                  <Form.Item name="embedding_model_id" label="Embedding 模型">
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      options={embeddingModels.map((m) => ({
                        value: m.id,
                        label: `${m.name} (${m.model_name || ''})`,
                      }))}
                    />
                  </Form.Item>
                  <Form.Item name="test_size" label="问题数量">
                    <InputNumber min={1} max={500} style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item
                    name="auto_invoke"
                    label="自动调用"
                    valuePropName="checked"
                    tooltip="入库完成后立即用该 RAG 系统跑一遍问答，方便直接进入评估"
                  >
                    <Switch />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </Form>
      )}

      {task && (
        <div>
          <Progress
            percent={task.progress}
            status={task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : 'active'}
          />
          <Descriptions size="small" column={2} style={{ marginTop: 12 }}>
            <Descriptions.Item label="状态">
              <Tag color={task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : 'blue'}>
                {task.status === 'completed' ? '完成' : task.status === 'failed' ? '失败' : '进行中'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="阶段">
              {task.stage ? (STAGE_TEXT[task.stage] || task.stage) : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="知识库">{task.remote_kb_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="数据集">{task.dataset_id || '-'}</Descriptions.Item>
          </Descriptions>
          {task.error && <Alert type="error" showIcon style={{ marginTop: 8 }} message={task.error} />}
          <div style={{ marginTop: 12 }}>
            {task.files.map((file) => (
              <div key={file.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
                <Text ellipsis style={{ maxWidth: 420 }}>{file.name}</Text>
                <Space>
                  {typeof file.chunk_count === 'number' && <Text type="secondary">{file.chunk_count} 分片</Text>}
                  <Tag color={file.status === 'done' ? 'green' : file.status === 'failed' ? 'red' : 'blue'}>
                    {file.status || 'pending'}
                  </Tag>
                </Space>
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  )
}

export default ApiIngestModal
