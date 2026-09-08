// 通用展示格式化工具
import dayjs from 'dayjs'

/** 时间格式化：datetime → "YYYY-MM-DD HH:mm"，空值显示 '-' */
export function formatTime(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'
}

/** 时间格式化（含秒）："YYYY-MM-DD HH:mm:ss"，空值显示 '-' */
export function formatTimeFull(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'
}

/** 仅日期："YYYY-MM-DD"，空值显示 '-' */
export function formatDate(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD') : '-'
}

/** 短时间（月-日）："MM-DD HH:mm"，空值显示 '-' */
export function formatShortTime(value?: string | null): string {
  return value ? dayjs(value).format('MM-DD HH:mm') : '-'
}
