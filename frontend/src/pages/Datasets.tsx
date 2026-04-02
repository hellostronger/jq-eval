import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, message, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { getDatasets, createDataset, deleteDataset } from '@/api'
import type { Dataset } from '@/types'

const Datasets: React.FC = () => {
  const navigate = useNavigate()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const fetchDatasets = async () => {
    setLoading(true)
    try {
      const data = await getDatasets()
      setDatasets(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDatasets()
  }, [])

  const showCreateDialog = () => {
    form.resetFields()
    setModalVisible(true)
  }

  const saveDataset = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await createDataset(values)
      message.success('创建成功')
      setModalVisible(false)
      fetchDatasets()
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteDataset = async (dataset: Dataset) => {
    try {
      await deleteDataset(dataset.id)
      message.success('删除成功')
      fetchDatasets()
    } catch (e) {
      // 错误已在拦截器处理
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description' },
    {
      title: '记录数',
      dataIndex: 'total_records',
      key: 'total_records',
      render: (v: number) => <Tag color="blue">{v}</Tag>,
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
      render: (_: unknown, record: Dataset) => (
        <>
          <Button type="link" size="small" onClick={() => navigate(`/datasets/${record.id}`)}>
            查看
          </Button>
          <Popconfirm title="确定删除此数据集?" onConfirm={() => handleDeleteDataset(record)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </>
      ),
    },
  ]

  return (
    <Card
      title="数据集"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
          新建数据集
        </Button>
      }
    >
      <Table dataSource={datasets} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title="新建数据集"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveDataset}
        confirmLoading={saving}
      >
        <Form form={form} labelCol={{ span: 6 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="数据集名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="数据集描述" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default Datasets