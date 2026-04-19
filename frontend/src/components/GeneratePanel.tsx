import React, { useState, useEffect } from 'react'
import { Card, Form, Input, Button, Select, Upload, message, Progress, Space, InputNumber, Collapse } from 'antd'
import { UploadOutlined, PlusOutlined, DeleteOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { generateDataset, getGenerateStatus, getCurrentGenerateTask, getModels, uploadDatasetFile } from '@/api'
import type { ModelConfig, GenerateRequest } from '@/types'

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
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([])

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
    const checkCurrentTask = async () => {
      try {
        const result = await getCurrentGenerateTask(datasetId)
        if (result.has_active_task && result.task_id) {
          // 有进行中的任务，先获取 Celery 状态
          const statusResult = await getGenerateStatus(datasetId, result.task_id)
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

    const timer = setInterval(pollStatus, 2000)
    return () => clearInterval(timer)
  }, [taskId, status, datasetId, onGenerateSuccess])

  // 上传文件处理
  const handleUpload = async (file: File) => {
    try {
      const result = await uploadDatasetFile(datasetId, file)
      if (result.object_name || result.file_path) {
        setUploadedFiles([...uploadedFiles, result.object_name || result.file_path])
        message.success('文件上传成功')
      }
    } catch (e) {
      // 错误已在拦截器处理
    }
    return false
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

      if (uploadedFiles.length > 0) {
        sources.push({
          source_type: 'file_upload',
          file_paths: uploadedFiles,
        })
      }

      if (texts.filter(t => t.trim()).length > 0) {
        sources.push({
          source_type: 'text_input',
          texts: texts.filter(t => t.trim()),
        })
      }

      if (sources.length === 0) {
        message.error('请至少添加一个文档源（上传文件或输入文本）')
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

    } catch (e: any) {
      // 表单验证错误由 antd 显示，API 错误由拦截器处理
      if (e?.errorFields) {
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
        {/* 文档源配置 */}
        <Collapse defaultActiveKey={['upload', 'text']}>
          <Collapse.Panel header="上传文件" key="upload">
            <Upload beforeUpload={handleUpload} accept=".pdf,.txt,.md,.docx" showUploadList={false}>
              <Button icon={<UploadOutlined />}>上传文档 (PDF/TXT/MD/DOCX)</Button>
            </Upload>
            {uploadedFiles.length > 0 && (
              <div style={{ marginTop: 8 }}>
                已上传: {uploadedFiles.map(f => f.split('/').pop()).join(', ')}
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
    </Card>
  )
}

export default GeneratePanel