import React from 'react'
import { Result, Button, Typography } from 'antd'

interface Props {
  children: React.ReactNode
  /** 出错时展示的区域名称，便于用户知道是哪一块坏了 */
  area?: string
}

interface State {
  error: Error | null
}

/**
 * 渲染错误兜底。
 *
 * 没有它的时候，任意一个组件渲染抛错（比如表格某个单元格的
 * `null.toFixed()`）会让 React 卸载整棵树：整个应用白屏、
 * 路由和所有状态一起丢失，用户只能刷新。React 自己的报错
 * 也会提示 "Consider adding an error boundary"。
 *
 * 有了它之后，坏掉的只是一块区域，其余部分照常可用。
 */
class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prevProps: Props) {
    // 切换页面/区域后重置，让用户能重新加载那块内容
    if (prevProps.area !== this.props.area && this.state.error) {
      this.setState({ error: null })
    }
  }

  handleReset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return <>{this.props.children}</>

    return (
      <Result
        status="error"
        title={this.props.area ? `${this.props.area}加载失败` : '页面渲染出错'}
        subTitle={
          <Typography.Text type="secondary">
            这一块没能正常显示，其余功能不受影响。错误信息：{error.message}
          </Typography.Text>
        }
        extra={
          <Button type="primary" onClick={this.handleReset}>
            重试
          </Button>
        }
      />
    )
  }
}

export default ErrorBoundary
