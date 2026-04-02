import React, { useEffect, useState } from 'react'
import { Card, Table, Upload, Button, message, Tabs, Input, Tag } from 'antd'
import { UploadOutlined, PlusOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { getDataset, getQARecords, uploadDatasetFile } from '@/api'
import type { Dataset, QARecord } from '@/types'

const DatasetDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [qaRecords, setQARecords] = useState<QARecord[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const fetchDataset = async () => {
    if (!id) return
    try {
      const data = await getDataset(Number(id))
      setDataset(data)
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const fetchQARecords = async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await getQARecords(Number(id), { page, size: pageSize })
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
      await uploadDatasetFile(Number(id), file)
      message.success('导入成功')
      fetchQARecords()
    } catch (e) {
      // 错误已在拦截器处理
    }
    return false
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
  ]

  const tabItems = [
    {
      key: 'records',
      label: 'QA记录',
      children: (
        <Table
          dataSource={qaRecords}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
            },
          }}
        />
      ),
    },
    {
      key: 'import',
      label: '导入数据',
      children: (
        <Card>
          <Upload
            beforeUpload={handleUpload}
            accept=".json,.jsonl,.csv"
            showUploadList={false}
          >
            <Button icon={<UploadOutlined />}>上传文件导入</Button>
          </Upload>
          <p style={{ marginTop: 8, color: '#666' }}>
            支持 JSON、JSONL、CSV 格式文件
          </p>
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