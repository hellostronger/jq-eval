import type { TrainingDataType } from '@/types'

export interface DataTypeOption {
  value: TrainingDataType
  /** 完整名称，用于页面标题与标签 */
  label: string
  /** 侧边栏子菜单短名称 */
  menuLabel: string
  color: string
  /** 子页面一句话说明 */
  description: string
}

export const DATA_TYPE_OPTIONS: DataTypeOption[] = [
  {
    value: 'embedding',
    label: 'Embedding训练数据',
    menuLabel: 'Embedding训练数据',
    color: 'green',
    description: '对 (query, 正例, 负例) 形式的向量检索训练数据做质量评估：正例与查询的语义相关性、文本长度适配度、噪声与多样性。',
  },
  {
    value: 'reranker',
    label: 'Reranker训练数据',
    menuLabel: 'Reranker训练数据',
    color: 'purple',
    description: '对排序模型训练数据做质量评估：正负例对的可分性、标签一致性、难负例质量与文档长度均衡性。',
  },
  {
    value: 'llm',
    label: '大模型训练数据',
    menuLabel: 'LLM训练数据',
    color: 'blue',
    description: '对 SFT 指令数据做质量评估：回答质量、连贯性、有用性、长度、幻觉与指令遵循度（由 LLM 打分）。',
  },
  {
    value: 'vlm',
    label: 'VLM训练数据',
    menuLabel: 'VLM训练数据',
    color: 'magenta',
    description: '对多模态（图文）训练数据做质量评估：图文对齐度、问题相关性、答案完整性与幻觉检测。',
  },
  {
    value: 'reward_model',
    label: '奖励模型训练数据',
    menuLabel: '奖励模型训练数据',
    color: 'orange',
    description: '对奖励模型训练数据做质量评估：偏好对质量、标注置信度、偏好分布与排序一致性。',
  },
  {
    value: 'dpo',
    label: 'DPO训练数据',
    menuLabel: 'DPO训练数据',
    color: 'cyan',
    description: '对 DPO 偏好数据做质量评估：chosen/rejected 对质量、偏好强度、指令遵循与安全性。',
  },
  {
    value: 'vla',
    label: 'VLA训练数据',
    menuLabel: 'VLA训练数据',
    color: 'red',
    description: '对具身智能（视觉-语言-动作）训练数据做质量评估：动作推理、指令清晰度与数据集平衡性。',
  },
]

/** 侧边栏「训练数据评估」下拆分出的子页面（其余类型走「全部类型」页） */
export const SUBMENU_DATA_TYPES: TrainingDataType[] = ['embedding', 'reranker', 'llm', 'vlm']

export const TRAINING_DATA_BASE_PATH = '/training-data-evaluations'

export function getDataTypeOption(value?: string | null): DataTypeOption | undefined {
  return DATA_TYPE_OPTIONS.find(o => o.value === value)
}

export function getDataTypePath(value: TrainingDataType): string {
  return `${TRAINING_DATA_BASE_PATH}/${value}`
}