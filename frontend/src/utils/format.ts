// 通用展示格式化工具
import dayjs from 'dayjs'

// 后端多数端点用 datetime.utcnow() 存 naive UTC，部分直接 .isoformat()
// 序列化（无 Z 后缀）。dayjs/new Date 会把无时区字符串按本地时间解析，
// 导致 UTC+8 环境下全站时间显示早 8 小时。此处统一把 naive ISO 视为 UTC。
const NAIVE_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/
export function toLocalTime(value: string): string {
  return NAIVE_ISO.test(value) ? value + 'Z' : value
}

/** 时间格式化：datetime → "YYYY-MM-DD HH:mm"，空值显示 '-' */
export function formatTime(value?: string | null): string {
  return value ? dayjs(toLocalTime(value)).format('YYYY-MM-DD HH:mm') : '-'
}

/** 时间格式化（含秒）："YYYY-MM-DD HH:mm:ss"，空值显示 '-' */
export function formatTimeFull(value?: string | null): string {
  return value ? dayjs(toLocalTime(value)).format('YYYY-MM-DD HH:mm:ss') : '-'
}

/** 仅日期："YYYY-MM-DD"，空值显示 '-' */
export function formatDate(value?: string | null): string {
  return value ? dayjs(toLocalTime(value)).format('YYYY-MM-DD') : '-'
}

/** 短时间（月-日）："MM-DD HH:mm"，空值显示 '-' */
export function formatShortTime(value?: string | null): string {
  return value ? dayjs(toLocalTime(value)).format('MM-DD HH:mm') : '-'
}
