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
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import Models from './pages/Models'
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

const { Sider, Content } = Layout

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/models', icon: <SettingOutlined />, label: '模型配置' },
  { key: '/rag-systems', icon: <ApiOutlined />, label: 'RAG系统' },
  { key: '/datasets', icon: <FolderOpenOutlined />, label: '数据集' },
  { key: '/invocations', icon: <ThunderboltOutlined />, label: '调用批次' },
  { key: '/evaluations', icon: <LineChartOutlined />, label: '评估任务' },
  { key: '/metrics', icon: <BarChartOutlined />, label: '指标市场' },
  { key: '/data-sources', icon: <DatabaseOutlined />, label: '数据源' },
  { key: '/hot-news', icon: <FireOutlined />, label: '热点新闻' },
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
          <Route path="/rag-systems" element={<RAGSystems />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/datasets/:id" element={<DatasetDetail />} />
          <Route path="/invocations" element={<Invocations />} />
          <Route path="/invocations/:id" element={<InvocationDetail />} />
          <Route path="/evaluations" element={<Evaluations />} />
          <Route path="/evaluations/compare" element={<EvaluationCompare />} />
          <Route path="/evaluations/:id" element={<EvaluationDetail />} />
          <Route path="/metrics" element={<Metrics />} />
          <Route path="/data-sources" element={<DataSources />} />
          <Route path="/hot-news" element={<HotNews />} />
        </Routes>
      </Content>
    </Layout>
  )
}

export default App