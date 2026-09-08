import { useEffect, useRef } from 'react'

/**
 * 轮询运行中的异步任务：有任务运行时按间隔刷新，无任务时自动停止。
 *
 * @param hasRunning 是否存在运行中的任务（running/pending 等）
 * @param poll       轮询回调，每次间隔触发一次；抛错会被吞掉（轮询失败静默忽略）
 * @param intervalMs 轮询间隔，默认 5000
 * @param deps       额外依赖：变化时重建定时器（如查看中的批次 id）
 */
export function usePollingWhenRunning(
  hasRunning: boolean,
  poll: () => void | Promise<void>,
  intervalMs = 5000,
  deps: unknown[] = [],
) {
  const pollRef = useRef(poll)
  pollRef.current = poll

  useEffect(() => {
    if (!hasRunning) return
    const timer = window.setInterval(async () => {
      try {
        await pollRef.current()
      } catch {
        // 轮询失败忽略
      }
    }, intervalMs)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunning, intervalMs, ...deps])
}
