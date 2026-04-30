import React from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
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
  FileTextOutlined,
  GlobalOutlined,
  EditOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import Models from './pages/Models'
import ModelLogs from './pages/ModelLogs'
import RAGSystems from './pages/RAGSystems'
import Datasets from './pages/Datasets'
import DatasetDetail from './pages/DatasetDetail'
import Evaluations from './pages/Evaluations'
import EvaluationDetail from './pages/EvaluationDetail'
import EvaluationCompare from './pages/EvaluationCompare'
import Invocations from './pages/Invocations'
import InvocationDetail from './pages/InvocationDetail'
import Metrics from './pages/Metrics'
import DataSources from './pages/DataSources'
import HotNews from './pages/HotNews'
import LoadTests from './pages/LoadTests'
import DocExplanations from './pages/DocExplanations'
import DocExplanationEvaluations from './pages/DocExplanationEvaluations'
import DocExplanationEvalDetail from './pages/DocExplanationEvalDetail'
import OpenSourceDatasets from './pages/OpenSourceDatasets'
import TrainingDataEvals from './pages/TrainingDataEvals'
import Prompts from './pages/Prompts'
import VibeAgent from './pages/VibeAgent'

const { Sider, Content } = Layout

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/models', icon: <SettingOutlined />, label: '模型配置' },
  { key: '/model-logs', icon: <HistoryOutlined />, label: '模型日志' },
  { key: '/rag-systems', icon: <ApiOutlined />, label: 'RAG系统' },
  { key: '/datasets', icon: <FolderOpenOutlined />, label: '数据集' },
  { key: '/open-source-datasets', icon: <GlobalOutlined />, label: '开源数据集' },
  { key: '/invocations', icon: <ThunderboltOutlined />, label: '调用批次' },
  { key: '/load-tests', icon: <ExperimentOutlined />, label: '性能压测' },
  { key: '/evaluations', icon: <LineChartOutlined />, label: '评估任务' },
  { key: '/training-data-evaluations', icon: <ExperimentOutlined />, label: '训练数据评估' },
  { key: '/doc-explanations', icon: <FileTextOutlined />, label: '文档解释' },
  { key: '/doc-explanation-evaluations', icon: <BarChartOutlined />, label: '解释评估' },
  { key: '/metrics', icon: <BarChartOutlined />, label: '指标市场' },
  { key: '/data-sources', icon: <DatabaseOutlined />, label: '数据源' },
  { key: '/hot-news', icon: <FireOutlined />, label: '热点新闻' },
  { key: '/prompts', icon: <EditOutlined />, label: 'Prompt管理' },
  { key: '/vibe-agent', icon: <ThunderboltOutlined />, label: 'VibeAgent' },
]

const App: React.FC = () => {
  const location = useLocation()

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
          onClick={({ key }) => window.location.href = key}
          style={{ background: '#001529' }}
        />
      </Sider>
      <Content style={{ background: '#f0f2f5', padding: 16, overflow: 'auto' }}>
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
          <Route path="/training-data-evaluations" element={<TrainingDataEvals />} />
          <Route path="/doc-explanations" element={<DocExplanations />} />
          <Route path="/doc-explanation-evaluations" element={<DocExplanationEvaluations />} />
          <Route path="/doc-explanation-evaluations/:id" element={<DocExplanationEvalDetail />} />
          <Route path="/metrics" element={<Metrics />} />
          <Route path="/data-sources" element={<DataSources />} />
          <Route path="/hot-news" element={<HotNews />} />
          <Route path="/prompts" element={<Prompts />} />
          <Route path="/vibe-agent" element={<VibeAgent />} />
        </Routes>
      </Content>
    </Layout>
  )
}

export default App