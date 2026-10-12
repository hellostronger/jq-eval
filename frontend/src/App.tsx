import React, { Suspense, lazy, useState } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Spin } from 'antd'
import type { MenuProps } from 'antd'
import {
  DashboardOutlined,
  SettingOutlined,
  ApiOutlined,
  FolderOpenOutlined,
  LineChartOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  FireOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  GlobalOutlined,
  EditOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import ErrorBoundary from './components/ErrorBoundary'
import {
  SUBMENU_DATA_TYPES,
  TRAINING_DATA_BASE_PATH,
  getDataTypeOption,
  getDataTypePath,
} from './constants/trainingData'

// 路由级代码分割：各页面按需加载，首屏只带仪表盘
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

const { Sider, Content } = Layout

// 子菜单 key 不能与子项路径同名，否则父级和「全部类型」会同时高亮
const TRAINING_DATA_MENU_KEY = 'training-data-evaluations-menu'

// 页面出错时的区域名称（用于错误兜底提示）
const PAGE_LABELS: Record<string, string> = {
  '/dashboard': '仪表盘',
  '/models': '模型配置',
  '/model-logs': '模型日志',
  '/rag-systems': 'RAG系统',
  '/datasets': '数据集',
  '/open-source-datasets': '开源数据集',
  '/invocations': '调用批次',
  '/load-tests': '性能压测',
  '/evaluations': '评估任务',
  '/evaluations/compare': '评估对比',
  [TRAINING_DATA_BASE_PATH]: '训练数据评估',
  '/training-data-profiles': '训练数据画像',
  '/metrics': '指标市场',
  '/data-sources': '数据源',
  '/hot-news': '热点新闻',
  '/prompts': 'Prompt管理',
  '/vibe-agent': 'VibeAgent',
}
SUBMENU_DATA_TYPES.forEach(t => {
  PAGE_LABELS[getDataTypePath(t)] = `${getDataTypeOption(t)?.label ?? t}评估`
})

const menuItems: MenuProps['items'] = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/models', icon: <SettingOutlined />, label: '模型配置' },
  { key: '/model-logs', icon: <HistoryOutlined />, label: '模型日志' },
  { key: '/rag-systems', icon: <ApiOutlined />, label: 'RAG系统' },
  { key: '/datasets', icon: <FolderOpenOutlined />, label: '数据集' },
  { key: '/open-source-datasets', icon: <GlobalOutlined />, label: '开源数据集' },
  { key: '/invocations', icon: <ThunderboltOutlined />, label: '调用批次' },
  { key: '/load-tests', icon: <ExperimentOutlined />, label: '性能压测' },
  { key: '/evaluations', icon: <LineChartOutlined />, label: '评估任务' },
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
  { key: '/metrics', icon: <BarChartOutlined />, label: '指标市场' },
  { key: '/training-data-profiles', icon: <DatabaseOutlined />, label: '训练数据画像' },
  { key: '/data-sources', icon: <DatabaseOutlined />, label: '数据源' },
  { key: '/hot-news', icon: <FireOutlined />, label: '热点新闻' },
  { key: '/prompts', icon: <EditOutlined />, label: 'Prompt管理' },
  { key: '/vibe-agent', icon: <ThunderboltOutlined />, label: 'VibeAgent' },
]

const App: React.FC = () => {
  const location = useLocation()
  const navigate = useNavigate()
  // 受控展开态：子菜单默认展开，进入子页面后不会自动收起
  const [openKeys, setOpenKeys] = useState<string[]>([TRAINING_DATA_MENU_KEY])

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={220} style={{ background: '#001529' }}>
        <div className="logo">
          <h1>JQ-Eval</h1>
          <span>RAG/LLM评估系统</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          openKeys={openKeys}
          onOpenChange={keys => setOpenKeys(keys as string[])}
          onClick={({ key }) => navigate(key)}
          style={{ background: '#001529' }}
        />
      </Sider>
      <Content style={{ background: '#f0f2f5', padding: 16, overflow: 'auto' }}>
        <ErrorBoundary area={PAGE_LABELS[location.pathname]}>
          <Suspense
            fallback={
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
                <Spin size="large" />
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
              {/* 训练数据评估按类型拆分子页面：路由显式枚举，非法路径落到「全部类型」之外的空 Routes */}
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
      </Content>
    </Layout>
  )
}

export default App