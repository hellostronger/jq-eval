import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Modal, Form, Input, Select, message, Popconfirm, Tabs, Statistic, Row, Col, Space, Switch, Dropdown } from 'antd'
import { PlusOutlined, SyncOutlined, FireOutlined, LinkOutlined, DeleteOutlined, DownOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getNewsSources, createNewsSource, updateNewsSource, deleteNewsSource, testNewsSource, triggerCrawl, getHotArticles, getNewsStats, getDomains, getSupportedTypes, deleteArticle, batchDeleteArticles } from '@/api'
import type { NewsSource, HotArticle, NewsStats } from '@/types'

const HotNews: React.FC = () => {
  const [sources, setSources] = useState<NewsSource[]>([])
  const [articles, setArticles] = useState<HotArticle[]>([])
  const [stats, setStats] = useState<NewsStats | null>(null)
  const [domains, setDomains] = useState<{ code: string; name: string }[]>([])
  const [types, setTypes] = useState<{ type: string; display_name: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSource, setEditingSource] = useState<NewsSource | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [activeTab, setActiveTab] = useState('sources')
  const [articleFilter, setArticleFilter] = useState<{ domain?: string; source_id?: string }>({})
  const [selectedArticle, setSelectedArticle] = useState<HotArticle | null>(null)
  const [articleDetailVisible, setArticleDetailVisible] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const fetchSources = async () => {
    setLoading(true)
    try {
      const data = await getNewsSources()
      setSources(data)
    } finally {
      setLoading(false)
    }
  }

  const fetchArticles = async () => {
    setLoading(true)
    try {
      const data = await getHotArticles({ ...articleFilter, limit: 100 })
      setArticles(data)
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const data = await getNewsStats()
      setStats(data)
    } catch (e) {
      // ignore
    }
  }

  const fetchDomainsAndTypes = async () => {
    try {
      const [domainsData, typesData] = await Promise.all([getDomains(), getSupportedTypes()])
      setDomains(domainsData)
      setTypes(typesData)
    } catch (e) {
      // ignore
    }
  }

  useEffect(() => {
    fetchDomainsAndTypes()
    fetchStats()
  }, [])

  useEffect(() => {
    if (activeTab === 'sources') fetchSources()
    else if (activeTab === 'articles') fetchArticles()
  }, [activeTab, articleFilter])

  const showCreateDialog = () => {
    setEditingSource(null)
    form.resetFields()
    form.setFieldsValue({
      source_type: 'rss',
      domain: 'tech',
      crawl_frequency: '0 * * * *',
      is_active: true,
      crawl_config: { fetch_full_content: false }
    })
    setModalVisible(true)
  }

  const showEditDialog = (source: NewsSource) => {
    setEditingSource(source)
    form.setFieldsValue({
      ...source,
      crawl_config: source.crawl_config || { fetch_full_content: false }
    })
    setModalVisible(true)
  }

  const saveSource = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingSource) {
        await updateNewsSource(editingSource.id, values)
        message.success('更新成功')
      } else {
        await createNewsSource(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      fetchSources()
      fetchStats()
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async (source: NewsSource) => {
    try {
      const result = await testNewsSource(source.id)
      if (result.success) {
        message.success(`连接成功: ${result.feed_title || 'RSS源可用'}`)
      } else {
        message.error(`连接失败: ${result.error}`)
      }
    } catch (e) {
      // error handled
    }
  }

  const handleCrawl = async (source: NewsSource, forceFull: boolean = false) => {
    try {
      const result = await triggerCrawl(source.id, forceFull)
      message.success(`爬取完成: 发现${result.total_found}篇, 新增${result.new_articles}篇`)
      fetchSources()
      fetchStats()
    } catch (e) {
      // error handled
    }
  }

  const handleDelete = async (source: NewsSource) => {
    try {
      await deleteNewsSource(source.id)
      message.success('删除成功')
      fetchSources()
      fetchStats()
    } catch (e) {
      // error handled
    }
  }

  const handleToggleActive = async (source: NewsSource, active: boolean) => {
    try {
      await updateNewsSource(source.id, { is_active: active })
      message.success(active ? '已启用' : '已禁用')
      fetchSources()
    } catch (e) {
      // error handled
    }
  }

  const showArticleDetail = (article: HotArticle) => {
    setSelectedArticle(article)
    setArticleDetailVisible(true)
  }

  const handleDeleteArticle = async (articleId: string) => {
    try {
      await deleteArticle(articleId)
      message.success('删除成功')
      fetchArticles()
      fetchStats()
      setSelectedRowKeys(prev => prev.filter(key => key !== articleId))
    } catch (e) {
      // error handled
    }
  }

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请选择要删除的文章')
      return
    }
    setLoading(true)
    try {
      const result = await batchDeleteArticles(selectedRowKeys as string[])
      message.success(`成功删除 ${result.deleted_count} 篇文章`)
      setSelectedRowKeys([])
      // 等待数据刷新完成
      const data = await getHotArticles({ ...articleFilter, limit: 100 })
      setArticles(data)
      fetchStats()
    } catch (e) {
      // error handled
    } finally {
      setLoading(false)
    }
  }

  const handleSelectAll = () => {
    setSelectedRowKeys(articles.map(a => a.id))
  }

  const handleClearSelection = () => {
    setSelectedRowKeys([])
  }

  const sourceColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '领域',
      dataIndex: 'domain',
      key: 'domain',
      render: (domain: string) => {
        const d = domains.find(d => d.code === domain)
        return <Tag color="blue">{d?.name || domain}</Tag>
      },
    },
    {
      title: '类型',
      dataIndex: 'source_type',
      key: 'source_type',
      render: (type: string) => <Tag color="green">{type.toUpperCase()}</Tag>,
    },
    { title: 'RSS地址', dataIndex: 'source_url', key: 'source_url', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean, record: NewsSource) => (
        <Switch checked={active} onChange={(val) => handleToggleActive(record, val)} />
      ),
    },
    {
      title: '文章数',
      dataIndex: 'total_articles',
      key: 'total_articles',
    },
    {
      title: '最后爬取',
      dataIndex: 'last_crawl_at',
      key: 'last_crawl_at',
      render: (date?: string) => date ? dayjs(date).format('MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: NewsSource) => (
        <Space>
          <Button type="link" size="small" onClick={() => handleTest(record)}>测试</Button>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'incremental',
                  label: '增量爬取',
                  onClick: () => handleCrawl(record, false),
                },
                {
                  key: 'full',
                  label: '全量爬取',
                  onClick: () => handleCrawl(record, true),
                },
              ],
            }}
          >
            <Button type="link" size="small" icon={<SyncOutlined />}>
              爬取 <DownOutlined />
            </Button>
          </Dropdown>
          <Button type="link" size="small" onClick={() => showEditDialog(record)}>编辑</Button>
          <Popconfirm title="确定删除?" onConfirm={() => handleDelete(record)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const domainOptions = domains.map(d => ({ value: d.code, label: d.name }))
  const sourceOptions = sources.map(s => ({ value: s.id, label: s.name }))

  // 语言映射
  const languageMap: Record<string, string> = {
    zh: '中文',
    en: '英文',
    ja: '日语',
    ko: '韩语',
    fr: '法语',
    de: '德语',
    es: '西班牙语',
    ru: '俄语',
  }

  const articleColumns = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    { title: '作者', dataIndex: 'author', key: 'author', width: 100 },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      render: (cat?: string) => cat ? <Tag>{cat}</Tag> : '-',
    },
    {
      title: '语言',
      dataIndex: 'language',
      key: 'language',
      width: 80,
      render: (lang?: string) => lang ? <Tag color="purple">{languageMap[lang] || lang}</Tag> : '-',
    },
    {
      title: '长度',
      dataIndex: 'content_length',
      key: 'content_length',
      width: 80,
      render: (len?: number) => len ? `${len}字` : '-',
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      key: 'published_at',
      render: (date?: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
    },
    {
      title: '爬取时间',
      dataIndex: 'crawled_at',
      key: 'crawled_at',
      render: (date: string) => dayjs(date).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, record: HotArticle) => (
        <Space>
          {record.source_url && (
            <Button
              type="link"
              size="small"
              icon={<LinkOutlined />}
              href={record.source_url}
              target="_blank"
            >
              原文
            </Button>
          )}
          <Popconfirm title="确定删除?" onConfirm={() => handleDeleteArticle(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'sources',
            label: '新闻源管理',
            icon: <FireOutlined />,
            children: (
              <>
                <div style={{ marginBottom: 16 }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={showCreateDialog}>
                    新增新闻源
                  </Button>
                </div>
                <Table dataSource={sources} columns={sourceColumns} rowKey="id" loading={loading && activeTab === 'sources'} />
              </>
            ),
          },
          {
            key: 'articles',
            label: '文章列表',
            children: (
              <>
                <div style={{ marginBottom: 16 }}>
                  <Space>
                    <Select
                      placeholder="筛选领域"
                      options={domainOptions}
                      allowClear
                      style={{ width: 150 }}
                      onChange={(val) => setArticleFilter({ ...articleFilter, domain: val })}
                    />
                    <Select
                      placeholder="筛选来源"
                      options={sourceOptions}
                      allowClear
                      style={{ width: 200 }}
                      onChange={(val) => setArticleFilter({ ...articleFilter, source_id: val })}
                    />
                    {selectedRowKeys.length > 0 && (
                      <>
                        <Tag color="blue">已选 {selectedRowKeys.length} 篇</Tag>
                        <Button size="small" onClick={handleSelectAll}>全选</Button>
                        <Button size="small" onClick={handleClearSelection}>取消选择</Button>
                        <Popconfirm
                          title={`确定删除选中的 ${selectedRowKeys.length} 篇文章?`}
                          onConfirm={handleBatchDelete}
                        >
                          <Button type="primary" danger size="small" icon={<DeleteOutlined />}>
                            批量删除
                          </Button>
                        </Popconfirm>
                      </>
                    )}
                  </Space>
                </div>
                <Table
                  dataSource={articles}
                  columns={articleColumns}
                  rowKey="id"
                  loading={loading && activeTab === 'articles'}
                  rowSelection={{
                    selectedRowKeys,
                    onChange: setSelectedRowKeys,
                  }}
                  onRow={(record) => ({
                    onClick: (e) => {
                      if ((e.target as HTMLElement).closest('.ant-btn') || (e.target as HTMLElement).closest('.ant-popconfirm')) return
                      showArticleDetail(record)
                    },
                    style: { cursor: 'pointer' },
                  })}
                />
              </>
            ),
          },
          {
            key: 'stats',
            label: '统计概览',
            children: (
              <Row gutter={24}>
                <Col span={6}>
                  <Statistic title="新闻源总数" value={stats?.sources.total || 0} />
                </Col>
                <Col span={6}>
                  <Statistic title="活跃源" value={stats?.sources.active || 0} />
                </Col>
                <Col span={6}>
                  <Statistic title="文章总数" value={stats?.articles.total || 0} />
                </Col>
                <Col span={6}>
                  <Statistic title="今日文章" value={stats?.articles.today || 0} />
                </Col>
              </Row>
            ),
          },
        ]}
      />

      <Modal
        title={editingSource ? '编辑新闻源' : '新增新闻源'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={saveSource}
        confirmLoading={saving}
        width={600}
      >
        <Form form={form} labelCol={{ span: 5 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="新闻源名称" />
          </Form.Item>
          <Form.Item name="domain" label="领域" rules={[{ required: true }]}>
            <Select options={domainOptions} />
          </Form.Item>
          <Form.Item name="source_type" label="类型" rules={[{ required: true }]}>
            <Select options={types.map(t => ({ value: t.type, label: t.display_name }))} />
          </Form.Item>
          <Form.Item name="source_url" label="RSS地址" rules={[{ required: true }]}>
            <Input placeholder="RSS Feed URL" />
          </Form.Item>
          <Form.Item name="crawl_frequency" label="爬取频率">
            <Input placeholder="Cron表达式, 如: 0 * * * *" />
          </Form.Item>
          <Form.Item name={['crawl_config', 'fetch_full_content']} label="获取完整内容" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 文章详情Modal */}
      <Modal
        title={selectedArticle?.title}
        open={articleDetailVisible}
        onCancel={() => setArticleDetailVisible(false)}
        footer={[
          selectedArticle?.source_url && (
            <Button
              key="source"
              icon={<LinkOutlined />}
              href={selectedArticle.source_url}
              target="_blank"
            >
              查看原文
            </Button>
          ),
          <Button key="close" onClick={() => setArticleDetailVisible(false)}>
            关闭
          </Button>,
        ]}
        width={800}
      >
        {selectedArticle && (
          <div>
            <div style={{ marginBottom: 16, color: '#666' }}>
              <Space split={<span>|</span>}>
                {selectedArticle.author && <span>作者: {selectedArticle.author}</span>}
                {selectedArticle.category && <span>分类: {selectedArticle.category}</span>}
                {selectedArticle.language && <span>语言: {languageMap[selectedArticle.language] || selectedArticle.language}</span>}
                {selectedArticle.content_length && <span>长度: {selectedArticle.content_length}字</span>}
                {selectedArticle.published_at && <span>发布: {dayjs(selectedArticle.published_at).format('YYYY-MM-DD')}</span>}
              </Space>
            </div>
            <div style={{ maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
              {selectedArticle.content || '无内容'}
            </div>
          </div>
        )}
      </Modal>
    </Card>
  )
}

export default HotNews