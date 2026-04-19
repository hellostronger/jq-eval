import React, { useEffect, useState } from 'react'
import { Card, Table, Upload, Button, message, Tabs, Input, Tag, Space, Divider, Popconfirm } from 'antd'
import { UploadOutlined, PlusOutlined, DownloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { getDataset, getQARecords, uploadDatasetFile, downloadTemplate, deleteQARecord, batchDeleteQARecords } from '@/api'
import GeneratePanel from '@/components/GeneratePanel'
import type { Dataset, QARecord } from '@/types'

const DatasetDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [qaRecords, setQARecords] = useState<QARecord[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const fetchDataset = async () => {
    if (!id) return
    try {
      const data = await getDataset(id)
      setDataset(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchQARecords = async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await getQARecords(id, { page, size: pageSize })
      setQARecords(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDataset()
    fetchQARecords()
  }, [id, page, pageSize])

  const handleUpload = async (file: File) => {
    if (!id) return
    try {
      await uploadDatasetFile(id, file)
      message.success('导入成功')
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
    return false
  }

  const handleDeleteRecord = async (recordId: string) => {
    if (!id) return
    try {
      await deleteQARecord(id, recordId)
      message.success('删除成功')
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const handleBatchDelete = async () => {
    if (!id || selectedRowKeys.length === 0) return
    try {
      await batchDeleteQARecords(id, selectedRowKeys as string[])
      message.success(`成功删除 ${selectedRowKeys.length} 条记录`)
      setSelectedRowKeys([])
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      ellipsis: true,
    },
    {
      title: '回答',
      dataIndex: 'answer',
      key: 'answer',
      ellipsis: true,
      render: (v: string) => v || <Tag color="default">无</Tag>,
    },
    {
      title: '参考上下文',
      dataIndex: 'contexts',
      key: 'contexts',
      ellipsis: true,
      render: (contexts: string[]) => {
        if (!contexts || contexts.length === 0) return <Tag color="default">无</Tag>
        return (
          <div style={{ maxWidth: 200 }}>
            {contexts.slice(0, 2).map((c, i) => (
              <div key={i} style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 12,
                color: '#666',
                marginBottom: 2
              }}>
                [{i + 1}] {c.substring(0, 50)}...
              </div>
            ))}
            {contexts.length > 2 && <span style={{ fontSize: 12, color: '#999' }}>+{contexts.length - 2}条</span>}
          </div>
        )
      },
    },
    {
      title: 'Ground Truth',
      dataIndex: 'ground_truth',
      key: 'ground_truth',
      ellipsis: true,
      render: (v: string) => v || <Tag color="default">无</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (date: string) => dayjs(date).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: QARecord) => (
        <Popconfirm
          title="确定删除此记录？"
          onConfirm={() => handleDeleteRecord(record.id)}
        >
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys)
    },
  }

  const tabItems = [
    {
      key: 'records',
      label: 'QA记录',
      children: (
        <div>
          {selectedRowKeys.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <Popconfirm
                title={`确定删除选中的 ${selectedRowKeys.length} 条记录？`}
                onConfirm={handleBatchDelete}
              >
                <Button danger icon={<DeleteOutlined />}>
                  批量删除 ({selectedRowKeys.length})
                </Button>
              </Popconfirm>
            </div>
          )}
          <Table
            dataSource={qaRecords}
            columns={columns}
            rowKey="id"
            loading={loading}
            rowSelection={rowSelection}
            pagination={{
              current: page,
              pageSize,
              total,
              onChange: (p, ps) => {
                setPage(p)
                setPageSize(ps)
                setSelectedRowKeys([]) // 切换页码时清空选择
              },
            }}
          />
        </div>
      ),
    },
    {
      key: 'generate',
      label: '生成数据',
      children: (
        <GeneratePanel
          datasetId={id || ''}
          onGenerateSuccess={fetchQARecords}
        />
      ),
    },
    {
      key: 'import',
      label: '导入数据',
      children: (
        <Card>
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>下载模板</div>
              <Space>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate('json')}
                >
                  JSON 模板
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate('jsonl')}
                >
                  JSONL 模板
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate('csv')}
                >
                  CSV 模板
                </Button>
              </Space>
              <p style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
                选择合适的模板格式下载，按模板格式填写数据后上传导入
              </p>
            </div>

            <Divider />

            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>上传文件</div>
              <Upload
                beforeUpload={handleUpload}
                accept=".json,.jsonl,.csv"
                showUploadList={false}
              >
                <Button icon={<UploadOutlined />}>上传文件导入</Button>
              </Upload>
              <p style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
                支持 JSON、JSONL、CSV 格式文件
              </p>
            </div>
          </Space>
        </Card>
      ),
    },
  ]

  return (
    <Card title={dataset?.name || '数据集详情'}>
      <Tabs items={tabItems} />
    </Card>
  )
}

export default DatasetDetail