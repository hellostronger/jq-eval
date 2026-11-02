import React, { Suspense, lazy, useState } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Button, Drawer, Layout, Menu, Spin } from 'antd'
import type { MenuProps } from 'antd'
import {
  ApiOutlined,
  ArrowRightOutlined,
  BarChartOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  EditOutlined,
  ExperimentOutlined,
  FireOutlined,
  FolderOpenOutlined,
  GlobalOutlined,
  HistoryOutlined,
  LineChartOutlined,
  MenuOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import ErrorBoundary from './components/ErrorBoundary'
import {
  SUBMENU_DATA_TYPES,
  TRAINING_DATA_BASE_PATH,
  getDataTypeOption,
  getDataTypePath,
} from './constants/trainingData'

const Models = lazy(() => import('./pages/Models'))
const ModelLogs = lazy(() => import('./pages/ModelLogs'))
const RAGSystems = lazy(() => import('./pages/RAGSystems'))
const Datasets = lazy(() => import('./pages/Datasets'))
const DatasetDetail = lazy(() => import('./pages/DatasetDetail'))
const Evaluations = lazy(() => import('./pages/Evaluations'))
const EvaluationDetail = lazy(() => import('./pages/EvaluationDetail'))
const EvaluationCompare = lazy(() => import('./pages/EvaluationCompare'))
const Invocations = lazy(() => import('./pages/Invocations'))
const InvocationDetail = lazy(() => import('./pages/InvocationDetail'))
const Metrics = lazy(() => import('./pages/Metrics'))
const DataSources = lazy(() => import('./pages/DataSources'))
const HotNews = lazy(() => import('./pages/HotNews'))
const LoadTests = lazy(() => import('./pages/LoadTests'))
const OpenSourceDatasets = lazy(() => import('./pages/OpenSourceDatasets'))
const TrainingDataEvals = lazy(() => import('./pages/TrainingDataEvals'))
const TrainingDataProfiles = lazy(() => import('./pages/TrainingDataProfiles'))
const Prompts = lazy(() => import('./pages/Prompts'))
const VibeAgent = lazy(() => import('./pages/VibeAgent'))

const { Sider, Header, Content } = Layout
const TRAINING_DATA_MENU_KEY = 'training-data-evaluations-menu'

const PAGE_META: Record<string, { title: string; description: string; section: string }> = {
  '/dashboard': { title: '评测工作台', description: '掌握资源概况、评估进展与系统运行状态', section: '总览' },
  '/models': { title: '模型配置', description: '集中管理生成、向量、重排与文档解析模型', section: '资源管理' },
  '/model-logs': { title: '模型日志', description: '追踪模型调用记录、延迟与异常信息', section: '可观测性' },
  '/rag-systems': { title: 'RAG 系统', description: '接入并管理待评测的 RAG 与知识库系统', section: '资源管理' },
  '/datasets': { title: '数据集', description: '构建、同步并维护高质量评估数据', section: '资源管理' },
  '/open-source-datasets': { title: '开源数据集', description: '发现可复用的公开评估数据集', section: '资源管理' },
  '/invocations': { title: '调用批次', description: '运行并留存可复用的 RAG 调用结果', section: '评测流程' },
  '/load-tests': { title: '性能压测', description: '测量系统吞吐、响应延迟与稳定性', section: '评测流程' },
  '/evaluations': { title: '评估任务', description: '创建评估、跟踪进度并比较实验结果', section: '评测流程' },
  '/evaluations/compare': { title: '评估对比', description: '横向比较不同实验的指标表现', section: '评测流程' },
  [TRAINING_DATA_BASE_PATH]: { title: '训练数据评估', description: '评估训练数据质量与分布特征', section: '数据洞察' },
  '/training-data-profiles': { title: '训练数据画像', description: '查看训练数据的结构与质量画像', section: '数据洞察' },
  '/metrics': { title: '指标市场', description: '浏览适用于不同任务与模态的评估指标', section: '资源管理' },
  '/data-sources': { title: '数据源', description: '管理数据库与外部系统的数据连接', section: '数据洞察' },
  '/hot-news': { title: '热点新闻', description: '跟踪 AI 与评估生态的最新动态', section: '探索' },
  '/prompts': { title: 'Prompt 管理', description: '维护评估与分析使用的提示词模板', section: '资源管理' },
  '/vibe-agent': { title: 'VibeAgent', description: '通过智能代理辅助完成评估工作', section: '探索' },
}

SUBMENU_DATA_TYPES.forEach(t => {
  PAGE_META[getDataTypePath(t)] = {
    title: `${getDataTypeOption(t)?.label ?? t}评估`,
    description: '查看训练数据质量评估结果与明细',
    section: '数据洞察',
  }
})

const menuItems: MenuProps['items'] = [
  {
    type: 'group',
    label: '工作区',
    children: [
      { key: '/dashboard', icon: <DashboardOutlined />, label: '评测工作台' },
    ],
  },
  {
    type: 'group',
    label: '评测流程',
    children: [
      { key: '/invocations', icon: <ThunderboltOutlined />, label: '调用批次' },
      { key: '/evaluations', icon: <LineChartOutlined />, label: '评估任务' },
      { key: '/load-tests', icon: <ExperimentOutlined />, label: '性能压测' },
    ],
  },
  {
    type: 'group',
    label: '资源管理',
    children: [
      { key: '/datasets', icon: <FolderOpenOutlined />, label: '数据集' },
      { key: '/rag-systems', icon: <ApiOutlined />, label: 'RAG 系统' },
      { key: '/models', icon: <SettingOutlined />, label: '模型配置' },
      { key: '/metrics', icon: <BarChartOutlined />, label: '指标市场' },
      { key: '/open-source-datasets', icon: <GlobalOutlined />, label: '开源数据集' },
      { key: '/prompts', icon: <EditOutlined />, label: 'Prompt 管理' },
    ],
  },
  {
    type: 'group',
    label: '数据与洞察',
    children: [
      {
        key: TRAINING_DATA_MENU_KEY,
        icon: <ExperimentOutlined />,
        label: '训练数据评估',
        children: [
          { key: TRAINING_DATA_BASE_PATH, label: '全部类型' },
          ...SUBMENU_DATA_TYPES.map(t => ({
            key: getDataTypePath(t),
            label: getDataTypeOption(t)?.menuLabel ?? t,
          })),
        ],
      },
      { key: '/training-data-profiles', icon: <DatabaseOutlined />, label: '训练数据画像' },
      { key: '/data-sources', icon: <DatabaseOutlined />, label: '数据源' },
      { key: '/model-logs', icon: <HistoryOutlined />, label: '模型日志' },
    ],
  },
  {
    type: 'group',
    label: '探索',
    children: [
      { key: '/hot-news', icon: <FireOutlined />, label: '热点新闻' },
      { key: '/vibe-agent', icon: <ThunderboltOutlined />, label: 'VibeAgent' },
    ],
  },
]

interface SidebarProps {
  selectedPath: string
  openKeys: string[]
  onOpenChange: (keys: string[]) => void
  onNavigate: (key: string) => void
}

const Sidebar: React.FC<SidebarProps> = ({ selectedPath, openKeys, onOpenChange, onNavigate }) => (
  <div className="sidebar-inner">
    <div className="brand">
      <div className="brand-mark"><span>J</span><span>Q</span></div>
      <div className="brand-copy">
        <strong>JQ Eval</strong>
        <span>EVALUATION STUDIO</span>
      </div>
    </div>
    <div className="workspace-card">
      <div className="workspace-avatar">R</div>
      <div>
        <strong>RAG 质量实验室</strong>
        <span>个人工作区</span>
      </div>
    </div>
    <Menu
      theme="light"
      mode="inline"
      className="app-menu"
      selectedKeys={[selectedPath]}
      items={menuItems}
      openKeys={openKeys}
      onOpenChange={keys => onOpenChange(keys as string[])}
      onClick={({ key }) => onNavigate(key)}
    />
    <div className="sidebar-footer">
      <div className="sidebar-footer-icon"><BarChartOutlined /></div>
      <div>
        <strong>让评估驱动迭代</strong>
        <span>Measure · Compare · Improve</span>
      </div>
    </div>
  </div>
)

const App: React.FC = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const [openKeys, setOpenKeys] = useState<string[]>([TRAINING_DATA_MENU_KEY])
  const [mobileOpen, setMobileOpen] = useState(false)

  const selectedPath = location.pathname.startsWith('/datasets/')
    ? '/datasets'
    : location.pathname.startsWith('/invocations/')
      ? '/invocations'
      : location.pathname.startsWith('/evaluations/')
        ? '/evaluations'
        : location.pathname
  const meta = PAGE_META[location.pathname] ?? PAGE_META[selectedPath] ?? {
    title: '详情',
    description: '查看完整数据与评估信息',
    section: '工作区',
  }
  const sidebar = (
    <Sidebar
      selectedPath={selectedPath}
      openKeys={openKeys}
      onOpenChange={setOpenKeys}
      onNavigate={key => {
        navigate(key)
        setMobileOpen(false)
      }}
    />
  )

  return (
    <Layout className="app-layout">
      <Sider width={256} className="app-sider" breakpoint="lg" collapsedWidth="0" trigger={null}>
        {sidebar}
      </Sider>
      <Drawer
        className="app-drawer"
        placement="left"
        width={288}
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        closable={false}
        styles={{ body: { padding: 0 } }}
      >
        {sidebar}
      </Drawer>
      <Layout className="app-main">
        <Header className="app-header">
          <div className="app-header-title">
            <Button
              className="mobile-menu-button"
              type="text"
              icon={<MenuOutlined />}
              aria-label="打开导航"
              onClick={() => setMobileOpen(true)}
            />
            <div>
              <div className="page-eyebrow">{meta.section}<span>/</span>JQ Eval</div>
              <h1>{meta.title}</h1>
              <p>{meta.description}</p>
            </div>
          </div>
          <div className="app-header-actions">
            <div className="environment-pill"><span />本地工作区</div>
            <Button type="primary" onClick={() => navigate('/evaluations')}>
              开始评估<ArrowRightOutlined />
            </Button>
          </div>
        </Header>
        <Content className="app-content">
          <div className="page-container">
            <ErrorBoundary area={meta.title}>
              <Suspense
                fallback={
                  <div className="page-loading">
                    <Spin size="large" />
                    <span>正在加载工作区</span>
                  </div>
                }
              >
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/models" element={<Models />} />
                  <Route path="/model-logs" element={<ModelLogs />} />
                  <Route path="/rag-systems" element={<RAGSystems />} />
                  <Route path="/datasets" element={<Datasets />} />
                  <Route path="/datasets/:id" element={<DatasetDetail />} />
                  <Route path="/open-source-datasets" element={<OpenSourceDatasets />} />
                  <Route path="/invocations" element={<Invocations />} />
                  <Route path="/invocations/:id" element={<InvocationDetail />} />
                  <Route path="/load-tests" element={<LoadTests />} />
                  <Route path="/evaluations" element={<Evaluations />} />
                  <Route path="/evaluations/compare" element={<EvaluationCompare />} />
                  <Route path="/evaluations/:id" element={<EvaluationDetail />} />
                  <Route path={TRAINING_DATA_BASE_PATH} element={<TrainingDataEvals />} />
                  <Route path="/training-data-evaluations/embedding" element={<TrainingDataEvals dataType="embedding" />} />
                  <Route path="/training-data-evaluations/reranker" element={<TrainingDataEvals dataType="reranker" />} />
                  <Route path="/training-data-evaluations/llm" element={<TrainingDataEvals dataType="llm" />} />
                  <Route path="/training-data-evaluations/vlm" element={<TrainingDataEvals dataType="vlm" />} />
                  <Route path="/training-data-profiles" element={<TrainingDataProfiles />} />
                  <Route path="/metrics" element={<Metrics />} />
                  <Route path="/data-sources" element={<DataSources />} />
                  <Route path="/hot-news" element={<HotNews />} />
                  <Route path="/prompts" element={<Prompts />} />
                  <Route path="/vibe-agent" element={<VibeAgent />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}

export default App
