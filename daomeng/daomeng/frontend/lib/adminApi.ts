import { authenticatedFetch } from '@/lib/auth';

export type Usage = { llm: number; image: number; video: number; other: number };

export type AdminTask = {
  task_id: string;
  task_kind: string;
  category: string;
  status: string;
  user_id: string;
  user_email: string;
  title: string;
  pipeline?: string;
  tool?: string;
  model?: string;
  progress: number;
  error: string;
  retry_count: number;
  duration_seconds?: number | null;
  created_at: string;
  updated_at: string;
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  last_login_at?: string | null;
  project_count: number;
  task_count: number;
  usage_today: Usage;
  limits: { llm: number; image: number; video: number };
};

export type AdminOverview = {
  users: { total: number; active: number; new_today: number };
  projects: { total: number };
  tasks: {
    total: number;
    running: number;
    failed: number;
    completed: number;
    success_rate: number | null;
  };
  usage_today: Usage;
  recent_failed_tasks: AdminTask[];
};

export type AdminModels = {
  providers: Array<{
    id: string;
    configured: boolean;
    credential_hint: string;
    credential_source: 'environment' | 'admin' | 'none';
    base_url: string;
  }>;
  assignments: Record<string, string>;
  config_updated_at?: string | null;
};

export type AdminSystem = {
  service: { status: string; version: string };
  database: { status: string };
  authentication: { status: string; mode: string; registration_enabled: boolean };
  queue: { enabled: boolean; running: boolean; concurrency: number; pending: number; active: number };
  storage: { status: string; path: string };
};

export type AuditLog = {
  id: string;
  actor_id: string;
  actor_email: string;
  action: string;
  target_type: string;
  target_id: string;
  details: Record<string, unknown>;
  created_at: string;
};

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(input, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof payload.detail === 'string' ? payload.detail : '管理员数据请求失败');
  }
  return payload as T;
}

export const adminApi = {
  overview: () => requestJson<AdminOverview>('/api/admin/overview'),
  users: (query = '') => requestJson<{ users: AdminUser[] }>(`/api/admin/users${query}`),
  updateUser: (userId: string, values: Record<string, number | boolean>) =>
    requestJson<{ user: AdminUser }>(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    }),
  tasks: (query = '') => requestJson<{ tasks: AdminTask[] }>(`/api/admin/tasks${query}`),
  retryTask: (taskId: string) =>
    requestJson<{ task: AdminTask }>(`/api/admin/tasks/${encodeURIComponent(taskId)}/retry`, {
      method: 'POST',
    }),
  models: () => requestJson<AdminModels>('/api/admin/models'),
  system: () => requestJson<AdminSystem>('/api/admin/system'),
  audit: () => requestJson<{ logs: AuditLog[] }>('/api/admin/audit'),
};
