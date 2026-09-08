import React, { useState, useEffect } from 'react'
import { Card, Form, Input, Button, Select, message, Progress, Space, InputNumber, Collapse, Table, Modal, Tag } from 'antd'
import { PlusOutlined, DeleteOutlined, PlayCircleOutlined, FileAddOutlined } from '@ant-design/icons'
import { generateDataset, getGenerateStatus, getCurrentGenerateTask, getModels, getDocuments } from '@/api'
import type { ModelConfig, GenerateRequest, DocumentInfo } from '@/types'

// 文档来源标签（解析结果 = 文档解析页 minerU 解析产物）
const SOURCE_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  mineru: { label: '解析结果', color: 'blue' },
  upload: { label: '上传文档', color: 'default' },
  text_input: { label: '输入文本', color: 'default' },
  hot_news: { label: '热点新闻', color: 'default' },
}

interface GeneratePanelProps {
  datasetId: string
  onGenerateSuccess: () => void
}

const GeneratePanel: React.FC<GeneratePanelProps> = ({ datasetId, onGenerateSuccess }) => {
  const [form] = Form.useForm()
  const [llmModels, setLlmModels] = useState<ModelConfig[]>([])
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [progress, setProgress] = useState<number>(0)
  const [status, setStatus] = useState<string>('idle')
  const [texts, setTexts] = useState<string[]>([])
  const [docSelectVisible, setDocSelectVisible] = useState(false)
  const [allDocs, setAllDocs] = useState<DocumentInfo[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [selectedDocIds, setSelectedDocIds] = useState<React.Key[]>([])
  const [existingDocs, setExistingDocs] = useState<DocumentInfo[]>([])

  // 加载模型列表
  useEffect(() => {
    const loadModels = async () => {
      try {
        const llmData = await getModels('llm')
        setLlmModels(llmData)
        const embeddingData = await getModels('embedding')
        setEmbeddingModels(embeddingData)
      } catch (e) {
        // 错误已在拦截器处理
      }
    }
    loadModels()
  }, [])

  // 加载时检查是否有进行中的任务（恢复轮询）
  useEffect(() => {
    let cancelled = false
    const checkCurrentTask = async () => {
      try {
        const result = await getCurrentGenerateTask(datasetId)
        if (cancelled) return
        if (result.has_active_task && result.task_id) {
          // 有进行中的任务，先获取 Celery 状态
          const statusResult = await getGenerateStatus(datasetId, result.task_id)
          if (cancelled) return
          const celeryStatus = statusResult.status

          if (celeryStatus === 'SUCCESS') {
            setProgress(100)
            message.success(`生成完成: ${statusResult.result?.generated_count || 0} 条数据`)
            onGenerateSuccess()
            // 清除本地状态，数据库状态会在轮询 API 中自动清除
            setTaskId(null)
            setStatus('idle')
          } else if (celeryStatus === 'FAILURE') {
            message.error(`生成失败: ${statusResult.result?.error || '未知错误'}`)
            setTaskId(null)
            setStatus('idle')
          } else {
            // PENDING 或 PROGRESS，恢复轮询
            setTaskId(result.task_id)
            setStatus(celeryStatus)
            setProgress(celeryStatus === 'PROGRESS' ? statusResult.progress?.progress || 0 : 0)
          }
        }
      } catch (e) {
        // 错误已在拦截器处理
      }
    }
    checkCurrentTask()
    return () => { cancelled = true }
  }, [datasetId, onGenerateSuccess])

  // 轮询任务状态
  useEffect(() => {
    if (!taskId || status === 'SUCCESS' || status === 'FAILURE') return

    const pollStatus = async () => {
      try {
        const result = await getGenerateStatus(datasetId, taskId)
        setStatus(result.status)

        if (result.status === 'PROGRESS' && result.progress) {
          setProgress(result.progress.progress || 0)
        }

        if (result.status === 'SUCCESS') {
          setProgress(100)
          message.success(`生成完成: ${result.result?.generated_count || 0} 条数据`)
          onGenerateSuccess()
          // 清除本地状态，数据库状态会在 API 中自动清除
          setTaskId(null)
          setStatus('idle')
        }

        if (result.status === 'FAILURE') {
          message.error(`生成失败: ${result.result?.error || '未知错误'}`)
          // 清除本地状态
          setTaskId(null)
          setStatus('idle')
        }
      } catch (e) {
        // 错误已在拦截器处理
      }
    }

    // setInterval 直接持有 async 回调：卸载后已发出的请求仍会 setState，
    // 用 ref 记录最后一次调用，卸载/重建时丢弃过期响应
    let latest = 0
    const timer = setInterval(async () => {
      const seq = ++latest
      await pollStatus()
      if (seq !== latest) return
    }, 2000)
    return () => clearInterval(timer)
  }, [taskId, status, datasetId, onGenerateSuccess])

  // 打开已有文档选择弹窗（只列出归属本数据集的文档与全局文档）
  const openDocSelect = async () => {
    setDocSelectVisible(true)
    setDocsLoading(true)
    try {
      const data = await getDocuments({ dataset_id: datasetId, size: 200 })
      setAllDocs(data.items)
    } catch (e) {
      // 错误已在拦截器处理
    } finally {
      setDocsLoading(false)
    }
  }

  const confirmDocSelect = () => {
    const picked = allDocs.filter(d => selectedDocIds.includes(d.id))
    // 合并去重
    setExistingDocs(prev => {
      const ids = new Set(prev.map(d => d.id))
      return [...prev, ...picked.filter(d => !ids.has(d.id))]
    })
    setSelectedDocIds([])
    setDocSelectVisible(false)
  }

  // 添加文本
  const addText = () => {
    setTexts([...texts, ''])
  }

  // 更新文本
  const updateText = (index: number, value: string) => {
    const newTexts = [...texts]
    newTexts[index] = value
    setTexts(newTexts)
  }

  // 删除文本
  const removeText = (index: number) => {
    setTexts(texts.filter((_, i) => i !== index))
  }

  // 开始生成
  const handleGenerate = async () => {
    try {
      const values = await form.validateFields()

      // 构建源配置
      const sources: GenerateRequest['sources'] = []

      if (texts.filter(t => t.trim()).length > 0) {
        sources.push({
          source_type: 'text_input',
          texts: texts.filter(t => t.trim()),
        })
      }

      if (existingDocs.length > 0) {
        sources.push({
          source_type: 'existing_doc',
          document_ids: existingDocs.map(d => d.id),
        })
      }

      if (sources.length === 0) {
        message.error('请至少添加一个文档源（选择解析结果或输入文本）')
        return
      }

      setLoading(true)
      const result = await generateDataset(datasetId, {
        sources,
        test_size: values.test_size,
        distributions: {
          simple: values.simple_ratio || 0.5,
          reasoning: values.reasoning_ratio || 0.3,
          multi_context: values.multi_context_ratio || 0.2,
        },
        llm_model_id: values.llm_model_id,
        embedding_model_id: values.embedding_model_id,
      })

      setTaskId(result.task_id)
      setStatus('PENDING')
      setProgress(0)
      message.info(result.message)

    } catch (e) {
      // 表单验证错误由 antd 显示，API 错误由拦截器处理
      if ((e as { errorFields?: unknown })?.errorFields) {
        return // 表单验证失败，antd 会自动显示错误
      }
      // 其他错误静默处理（已在拦截器中提示）
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      {taskId && status !== 'idle' && (
        <div style={{ marginBottom: 16 }}>
          <Progress percent={progress} status={status === 'FAILURE' ? 'exception' : 'active'} />
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            {status === 'PENDING' && '任务等待中...'}
            {status === 'PROGRESS' && '正在生成数据...'}
            {status === 'SUCCESS' && '生成完成！'}
            {status === 'FAILURE' && '生成失败'}
          </div>
        </div>
      )}

      <Form form={form} layout="vertical" initialValues={{ test_size: 10, simple_ratio: 0.5, reasoning_ratio: 0.3, multi_context_ratio: 0.2 }}>
        {/* 文档源配置（测试集生成基于解析结果等文档库内容，不涉及文件上传） */}
        <Collapse defaultActiveKey={['existing', 'text']}>
          <Collapse.Panel header="选择解析结果（文档库）" key="existing">
            <div style={{ color: '#999', fontSize: 12, marginBottom: 8 }}>
              来自「文档解析」页 minerU 解析产物或其他已入库文档
            </div>
            <Button icon={<FileAddOutlined />} onClick={openDocSelect}>
              从文档库选择
            </Button>
            {existingDocs.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {existingDocs.map(d => (
                  <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {d.title || d.id}
                    </span>
                    {(() => {
                      const src = SOURCE_TYPE_LABELS[d.source_type || '']
                      return src ? <Tag color={src.color} style={{ marginRight: 0 }}>{src.label}</Tag> : null
                    })()}
                    <Button
                      type="link"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => setExistingDocs(prev => prev.filter(x => x.id !== d.id))}
                    >
                      移除
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Collapse.Panel>

          <Collapse.Panel header="直接输入文本" key="text">
            <Button icon={<PlusOutlined />} onClick={addText} style={{ marginBottom: 8 }}>
              添加文本
            </Button>
            {texts.map((text, index) => (
              <div key={index} style={{ marginBottom: 8 }}>
                <Input.TextArea
                  value={text}
                  onChange={(e) => updateText(index, e.target.value)}
                  placeholder={`文本 ${index + 1}`}
                  rows={3}
                />
                <Button icon={<DeleteOutlined />} onClick={() => removeText(index)} danger size="small" style={{ marginTop: 4 }}>
                  删除
                </Button>
              </div>
            ))}
          </Collapse.Panel>
        </Collapse>

        {/* 模型选择 */}
        <Form.Item name="llm_model_id" label="LLM 模型" rules={[{ required: true, message: '请选择 LLM 模型' }]}>
          <Select placeholder="选择用于生成的 LLM">
            {llmModels.map(m => (
              <Select.Option key={m.id} value={m.id}>{m.name}</Select.Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item name="embedding_model_id" label="Embedding 模型" rules={[{ required: true, message: '请选择 Embedding 模型' }]}>
          <Select placeholder="选择用于生成的 Embedding">
            {embeddingModels.map(m => (
              <Select.Option key={m.id} value={m.id}>{m.name}</Select.Option>
            ))}
          </Select>
        </Form.Item>

        {/* 生成参数 */}
        <Form.Item name="test_size" label="生成数量" rules={[{ required: true }]}>
          <InputNumber min={1} max={100} />
        </Form.Item>

        <Space>
          <Form.Item name="simple_ratio" label="简单问题比例">
            <InputNumber min={0} max={1} step={0.1} />
          </Form.Item>
          <Form.Item name="reasoning_ratio" label="推理问题比例">
            <InputNumber min={0} max={1} step={0.1} />
          </Form.Item>
          <Form.Item name="multi_context_ratio" label="多上下文比例">
            <InputNumber min={0} max={1} step={0.1} />
          </Form.Item>
        </Space>

        <Form.Item>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleGenerate}
            loading={loading}
            disabled={!!taskId && status !== 'SUCCESS' && status !== 'FAILURE'}
          >
            开始生成
          </Button>
        </Form.Item>
      </Form>

      {/* 文档库选择弹窗 */}
      <Modal
        title="从文档库选择（解析结果等已入库文档）"
        open={docSelectVisible}
        onOk={confirmDocSelect}
        onCancel={() => { setDocSelectVisible(false); setSelectedDocIds([]) }}
        width={700}
      >
        <div style={{ color: '#999', fontSize: 12, marginBottom: 8 }}>
          生成测试集基于已入库的文档内容（推荐选择「文档解析」产生的解析结果）
        </div>
        <Table
          dataSource={allDocs}
          columns={[
            { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
            {
              title: '来源',
              dataIndex: 'source_type',
              key: 'source_type',
              width: 90,
              render: (v: string) => {
                const src = SOURCE_TYPE_LABELS[v]
                return src ? <Tag color={src.color}>{src.label}</Tag> : (v || '-')
              },
            },
            { title: '类型', dataIndex: 'file_type', key: 'file_type', width: 80 },
          ]}
          rowKey="id"
          loading={docsLoading}
          pagination={{ pageSize: 8 }}
          rowSelection={{
            selectedRowKeys: selectedDocIds,
            onChange: (keys) => setSelectedDocIds(keys),
          }}
          size="small"
        />
      </Modal>
    </Card>
  )
}

export default GeneratePanel