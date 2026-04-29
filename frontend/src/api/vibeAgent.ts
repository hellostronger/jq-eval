import axios from 'axios'

const API_BASE = '/api/v1/vibe-agent'

// ========== Types ==========

export interface Slot {
  slot_id: string
  slot_name: string
  slot_description: string
  required: boolean
  default_value?: string
  options?: string[]
  current_value?: string
  confidence: string
}

export interface VibeAgentSession {
  session_id: string
  status: string
  original_description: string
  collected_info: {
    workflow_type?: string
    slots: Slot[]
    inferred_nodes?: string[]
    inferred_flow?: string
    current_state: string
  }
  conversation_history: ConversationMessage[]
  created_at: string
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  message_type: string
  timestamp: string
}

export interface Workflow {
  id: string
  name: string
  description?: string
  graph_definition: any
  nodes: any[]
  edges: any[]
  python_code: string
  mermaid_diagram: string
  llm_config: any
  status: string
  created_at: string
}

export interface WorkflowVersion {
  id: string
  version: number
  change_type: string
  change_notes?: string
  mermaid_diagram: string
  created_at: string
}

// ========== API Functions ==========

export const vibeAgentApi = {
  // Sessions
  createSession: async (description: string, llmConfig?: any): Promise<{ session_id: string; result: any }> => {
    const response = await axios.post(`${API_BASE}/sessions`, {
      description,
      llm_config: llmConfig,
    })
    return response.data
  },

  getSession: async (sessionId: string): Promise<VibeAgentSession> => {
    const response = await axios.get(`${API_BASE}/sessions/${sessionId}`)
    return response.data
  },

  sendMessage: async (sessionId: string, message: string): Promise<any> => {
    const response = await axios.post(`${API_BASE}/sessions/${sessionId}/messages`, { message })
    return response.data
  },

  generateWorkflow: async (sessionId: string): Promise<any> => {
    const response = await axios.post(`${API_BASE}/sessions/${sessionId}/generate`)
    return response.data
  },

  // Workflows
  listWorkflows: async (): Promise<Workflow[]> => {
    const response = await axios.get(`${API_BASE}/workflows`)
    return response.data
  },

  getWorkflow: async (workflowId: string): Promise<Workflow> => {
    const response = await axios.get(`${API_BASE}/workflows/${workflowId}`)
    return response.data
  },

  saveWorkflow: async (sessionId: string, name: string, description?: string): Promise<{ workflow_id: string }> => {
    const response = await axios.post(`${API_BASE}/workflows`, {
      session_id: sessionId,
      name,
      description,
    })
    return response.data
  },

  updateWorkflowConfig: async (workflowId: string, config: any): Promise<any> => {
    const response = await axios.put(`${API_BASE}/workflows/${workflowId}/config`, config)
    return response.data
  },

  executeWorkflow: async (workflowId: string, inputData: any, versionId?: string): Promise<any> => {
    const response = await axios.post(`${API_BASE}/workflows/${workflowId}/execute`, {
      input_data: inputData,
      workflow_version_id: versionId,
    })
    return response.data
  },

  tuneNode: async (workflowId: string, nodeId: string, feedback: any): Promise<any> => {
    const response = await axios.post(`${API_BASE}/workflows/${workflowId}/tune`, {
      node_id: nodeId,
      feedback,
    })
    return response.data
  },

  getWorkflowVersions: async (workflowId: string): Promise<WorkflowVersion[]> => {
    const response = await axios.get(`${API_BASE}/workflows/${workflowId}/versions`)
    return response.data
  },

  testWorkflow: async (workflowId: string, testCases?: any[]): Promise<any> => {
    const response = await axios.post(`${API_BASE}/workflows/${workflowId}/test`, testCases)
    return response.data
  },
}