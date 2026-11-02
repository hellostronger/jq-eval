import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#c36342',
          colorInfo: '#c36342',
          colorSuccess: '#42826a',
          colorWarning: '#b6812c',
          colorError: '#bc5a57',
          colorTextBase: '#242522',
          colorBgBase: '#f7f5f1',
          colorBgLayout: '#f7f5f1',
          colorBorder: '#e5e1da',
          colorBorderSecondary: '#ece8e1',
          borderRadius: 12,
          borderRadiusSM: 8,
          borderRadiusLG: 16,
          controlHeight: 40,
          fontFamily: "'DM Sans', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
        },
        components: {
          Button: {
            borderRadius: 10,
            primaryShadow: '0 4px 12px rgba(195, 99, 66, 0.18)',
          },
          Card: {
            borderRadiusLG: 16,
            headerFontSize: 16,
          },
          Input: {
            activeShadow: '0 0 0 3px rgba(195, 99, 66, 0.1)',
          },
          Menu: {
            itemBg: 'transparent',
            itemColor: '#73736c',
            itemHoverBg: '#f3f0eb',
            itemHoverColor: '#242522',
            itemSelectedBg: '#fbede5',
            itemSelectedColor: '#aa5033',
          },
          Modal: {
            borderRadiusLG: 18,
          },
          Table: {
            headerBg: '#f3f0eb',
            headerColor: '#73736c',
            rowHoverBg: '#faf7f3',
          },
        },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
)