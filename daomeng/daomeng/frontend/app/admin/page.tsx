'use client';

import Link from 'next/link';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  Database,
  FileClock,
  Image as ImageIcon,
  KeyRound,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Video,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import BrandHeader from '@/components/BrandHeader';
import {
  adminApi,
  type AdminModels,
  type AdminOverview,
  type AdminSystem,
  type AdminTask,
  type AdminUser,
  type AuditLog,
} from '@/lib/adminApi';

type Tab = 'overview' | 'users' | 'tasks' | 'models' | 'system' | 'audit';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'overview', label: '总览' },
  { id: 'users', label: '用户' },
  { id: 'tasks', label: '任务' },
  { id: 'models', label: '模型与 API' },
  { id: 'system', label: '系统状态' },
  { id: 'audit', label: '操作记录' },
];

const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  waiting: '待确认',
};

const ACTION_LABELS: Record<string, string> = {
  'user.update': '修改用户',
  'task.retry': '重试任务',
  'config.update': '更新模型配置',
};

const MODEL_LABELS: Record<string, string> = {
  llm: 'LLM 文本模型',
  vlm: 'VLM 视觉理解',
  image_t2i: '文生图',
  image_it2i: '图生图',
  video: '通用视频',
  video_first_frame: '首帧生视频',
  video_start_end: '首尾帧生视频',
  video_reference: '参考图生视频',
};

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  gemini: 'Gemini',
  deepseek: 'DeepSeek',
  siliconflow: '硅基流动',
  dashscope: '阿里云百炼',
  ark: '火山方舟',
  kling: '可灵',
};

function formatDate(value?: string | null) {
  if (!value) return '暂无记录';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function statusClasses(status: string) {
  if (status === 'completed' || status === 'ready') return 'bg-emerald-50 text-emerald-700';
  if (status === 'running' || status === 'pending') return 'bg-blue-50 text-blue-700';
  if (status === 'failed' || status === 'not_ready') return 'bg-red-50 text-red-700';
  return 'bg-slate-100 text-slate-700';
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusClasses(status)}`}>
      {STATUS_LABELS[status] || (status === 'ready' ? '正常' : status === 'not_ready' ? '异常' : status)}
    </span>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-3" role="status" aria-label="正在读取管理员数据">
      {[1, 2, 3].map(item => (
        <div key={item} className="h-16 animate-pulse rounded-xl bg-slate-100" />
      ))}
    </div>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="py-14 text-center">
      <CheckCircle2 className="mx-auto h-7 w-7 text-slate-400" />
      <p className="mt-3 text-sm font-medium text-slate-800">{title}</p>
      <p className="mx-auto mt-1 max-w-[52ch] text-sm leading-6 text-slate-600">{description}</p>
    </div>
  );
}

function OverviewPanel({ data }: { data: AdminOverview }) {
  const metrics = [
    { label: '注册用户', value: data.users.total, note: `今日新增 ${data.users.new_today}` },
    { label: '有效用户', value: data.users.active, note: `${data.users.total - data.users.active} 个已停用` },
    { label: '项目总数', value: data.projects.total, note: '用户创作项目' },
    {
      label: '任务成功率',
      value: data.tasks.success_rate === null ? '暂无' : `${data.tasks.success_rate}%`,
      note: `${data.tasks.running} 个正在执行`,
    },
  ];
  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-2xl bg-[#0b1d43] text-white shadow-[0_20px_52px_-34px_rgba(11,29,67,0.9)]">
        <div className="grid grid-cols-2 lg:grid-cols-4">
          {metrics.map((metric, index) => (
            <div
              key={metric.label}
              className={`px-5 py-5 sm:px-6 ${index >= 2 ? 'border-t border-white/10 lg:border-t-0' : ''} ${index % 2 ? 'border-l border-white/10' : ''} ${index > 1 ? 'lg:border-l' : ''}`}
            >
              <p className="text-sm text-blue-100">{metric.label}</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums tracking-[-0.02em]">{metric.value}</p>
              <p className="mt-1 text-xs text-blue-200">{metric.note}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[0.72fr_1.28fr]">
        <section className="rounded-2xl bg-white p-6 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
          <h2 className="text-lg font-semibold text-slate-950">今日模型任务</h2>
          <p className="mt-1 text-sm text-slate-600">按任务入口统计，不包含失败前未落库的调用。</p>
          <div className="mt-6 space-y-5">
            {[
              { label: '文本与视觉理解', value: data.usage_today.llm, icon: Activity, color: 'text-blue-700 bg-blue-50' },
              { label: '图片生成', value: data.usage_today.image, icon: ImageIcon, color: 'text-violet-700 bg-violet-50' },
              { label: '视频生成', value: data.usage_today.video, icon: Video, color: 'text-amber-700 bg-amber-50' },
            ].map(item => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="flex items-center gap-4">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${item.color}`}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-800">{item.label}</p>
                    <p className="mt-0.5 text-xs text-slate-500">今日已创建</p>
                  </div>
                  <span className="text-xl font-semibold tabular-nums text-slate-950">{item.value}</span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="rounded-2xl bg-white p-6 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">最近失败任务</h2>
              <p className="mt-1 text-sm text-slate-600">优先处理真实用户遇到的生成阻塞。</p>
            </div>
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
          </div>
          {data.recent_failed_tasks.length ? (
            <div className="mt-5 divide-y divide-slate-100">
              {data.recent_failed_tasks.map(task => (
                <div key={task.task_id} className="py-4 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-3">
                    <p className="min-w-0 truncate text-sm font-medium text-slate-900">{task.title}</p>
                    <span className="shrink-0 text-xs text-slate-500">{formatDate(task.updated_at)}</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-600">{task.user_email} · {task.error || '未记录错误详情'}</p>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="暂时没有失败任务" description="新出现的任务错误会在这里集中展示。" />
          )}
        </section>
      </div>
    </div>
  );
}

function UsersPanel({ users, onUpdated }: { users: AdminUser[]; onUpdated: () => Promise<void> }) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { llm: number; image: number; video: number }>>({});
  const visibleUsers = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return users;
    return users.filter(user => `${user.email} ${user.display_name}`.toLowerCase().includes(keyword));
  }, [search, users]);

  const expand = (user: AdminUser) => {
    setExpanded(current => current === user.id ? null : user.id);
    setDrafts(current => ({ ...current, [user.id]: { ...user.limits } }));
  };

  const saveLimits = async (user: AdminUser) => {
    setSaving(user.id);
    setActionError('');
    try {
      const values = drafts[user.id] || user.limits;
      await adminApi.updateUser(user.id, {
        daily_llm_limit: values.llm,
        daily_image_limit: values.image,
        daily_video_limit: values.video,
      });
      await onUpdated();
      setExpanded(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '保存用户额度失败');
    } finally {
      setSaving(null);
    }
  };

  const toggleActive = async (user: AdminUser) => {
    if (user.role === 'admin' && user.is_active) return;
    setSaving(user.id);
    setActionError('');
    try {
      await adminApi.updateUser(user.id, { is_active: !user.is_active });
      await onUpdated();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '更新账号状态失败');
    } finally {
      setSaving(null);
    }
  };

  return (
    <section className="rounded-2xl bg-white shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">用户与测试额度</h2>
          <p className="mt-1 text-sm text-slate-600">管理账号状态，并限制单个用户每天的模型任务数。</p>
        </div>
        <label className="relative block w-full sm:w-72">
          <span className="sr-only">搜索用户</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            className="h-10 w-full rounded-xl bg-slate-100 pl-10 pr-3 text-sm text-slate-900 outline-none transition focus:bg-white focus:ring-2 focus:ring-blue-600"
            placeholder="搜索邮箱或昵称"
          />
        </label>
      </div>
      {actionError && <p className="mx-5 mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{actionError}</p>}
      <div className="overflow-x-auto border-t border-slate-100">
        <table className="w-full min-w-[920px] text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium text-slate-600">
            <tr>
              <th className="px-5 py-3">用户</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3">项目 / 任务</th>
              <th className="px-4 py-3">今日用量</th>
              <th className="px-4 py-3">最近登录</th>
              <th className="px-5 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visibleUsers.map(user => (
              <UserRows
                key={user.id}
                user={user}
                expanded={expanded === user.id}
                saving={saving === user.id}
                draft={drafts[user.id] || user.limits}
                onExpand={() => expand(user)}
                onToggleActive={() => void toggleActive(user)}
                onDraftChange={(key, value) => setDrafts(current => ({
                  ...current,
                  [user.id]: { ...(current[user.id] || user.limits), [key]: Math.max(0, Number(value) || 0) },
                }))}
                onSave={() => void saveLimits(user)}
              />
            ))}
          </tbody>
        </table>
        {!visibleUsers.length && <EmptyState title="没有匹配的用户" description="清除搜索词后可以查看全部测试用户。" />}
      </div>
    </section>
  );
}

function UserRows({
  user,
  expanded,
  saving,
  draft,
  onExpand,
  onToggleActive,
  onDraftChange,
  onSave,
}: {
  user: AdminUser;
  expanded: boolean;
  saving: boolean;
  draft: { llm: number; image: number; video: number };
  onExpand: () => void;
  onToggleActive: () => void;
  onDraftChange: (key: 'llm' | 'image' | 'video', value: string) => void;
  onSave: () => void;
}) {
  const accountStatusClasses = user.is_active
    ? 'bg-emerald-50 text-emerald-700'
    : 'bg-slate-100 text-slate-700';
  return (
    <>
      <tr className="align-middle hover:bg-slate-50/70">
        <td className="px-5 py-4">
          <p className="max-w-[260px] truncate font-medium text-slate-900">{user.display_name || user.email}</p>
          <p className="mt-1 max-w-[260px] truncate text-xs text-slate-500">{user.email}</p>
        </td>
        <td className="px-4 py-4">
          <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${accountStatusClasses}`}>
            {user.role === 'admin' ? '管理员' : user.is_active ? '正常' : '已停用'}
          </span>
        </td>
        <td className="px-4 py-4 tabular-nums text-slate-700">{user.project_count} / {user.task_count}</td>
        <td className="px-4 py-4 text-xs text-slate-600">
          文 {user.usage_today.llm} · 图 {user.usage_today.image} · 视频 {user.usage_today.video}
        </td>
        <td className="px-4 py-4 text-xs text-slate-600">{formatDate(user.last_login_at)}</td>
        <td className="px-5 py-4">
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onExpand}
              className="inline-flex h-9 items-center gap-1 rounded-lg px-3 text-xs font-medium text-blue-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600"
            >
              额度
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              disabled={saving || user.role === 'admin'}
              onClick={onToggleActive}
              className="h-9 rounded-lg px-3 text-xs font-medium text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-slate-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {user.is_active ? '停用' : '恢复'}
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-blue-50/45">
          <td colSpan={6} className="px-5 py-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div className="grid gap-3 sm:grid-cols-3">
                {([
                  ['llm', '文本 / VLM 每日次数'],
                  ['image', '图片生成每日次数'],
                  ['video', '视频生成每日次数'],
                ] as const).map(([key, label]) => (
                  <label key={key} className="text-xs font-medium text-slate-700">
                    {label}
                    <input
                      type="number"
                      min={0}
                      max={key === 'video' ? 1000 : 10000}
                      value={draft[key]}
                      onChange={event => onDraftChange(key, event.target.value)}
                      className="mt-2 h-10 w-full rounded-lg bg-white px-3 text-sm tabular-nums text-slate-900 outline-none ring-1 ring-slate-200 focus:ring-2 focus:ring-blue-600"
                    />
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={onSave}
                disabled={saving}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-[#0b1d43] px-5 text-sm font-medium text-white hover:bg-[#132c5f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                保存额度
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function TasksPanel({ tasks, onRetried }: { tasks: AdminTask[]; onRetried: () => Promise<void> }) {
  const [status, setStatus] = useState('all');
  const [retrying, setRetrying] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const visibleTasks = status === 'all' ? tasks : tasks.filter(task => task.status === status);
  const retry = async (task: AdminTask) => {
    setRetrying(task.task_id);
    setActionError('');
    try {
      await adminApi.retryTask(task.task_id);
      await onRetried();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '任务重新排队失败');
    } finally {
      setRetrying(null);
    }
  };
  return (
    <section className="rounded-2xl bg-white shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">生成任务</h2>
          <p className="mt-1 text-sm text-slate-600">只展示排障需要的元数据，不暴露用户完整提示词和生成内容。</p>
        </div>
        <label className="text-sm text-slate-700">
          <span className="sr-only">任务状态筛选</span>
          <select
            value={status}
            onChange={event => setStatus(event.target.value)}
            className="h-10 rounded-xl bg-slate-100 px-3 text-sm outline-none focus:ring-2 focus:ring-blue-600"
          >
            <option value="all">全部状态</option>
            <option value="pending">等待中</option>
            <option value="running">执行中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
          </select>
        </label>
      </div>
      {actionError && <p className="mx-5 mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{actionError}</p>}
      <div className="overflow-x-auto border-t border-slate-100">
        <table className="w-full min-w-[980px] text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium text-slate-600">
            <tr>
              <th className="px-5 py-3">任务</th>
              <th className="px-4 py-3">用户</th>
              <th className="px-4 py-3">类型 / 模型</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3">错误</th>
              <th className="px-5 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visibleTasks.map(task => (
              <tr key={task.task_id} className="align-top hover:bg-slate-50/70">
                <td className="px-5 py-4">
                  <p className="max-w-[260px] truncate font-medium text-slate-900">{task.title}</p>
                  <p className="mt-1 text-xs text-slate-500">{formatDate(task.created_at)} · 重试 {task.retry_count}</p>
                </td>
                <td className="px-4 py-4"><p className="max-w-[220px] truncate text-xs text-slate-700">{task.user_email}</p></td>
                <td className="px-4 py-4 text-xs text-slate-600">
                  <p>{task.pipeline || task.tool || task.task_kind}</p>
                  <p className="mt-1 max-w-[180px] truncate">{task.model || task.category}</p>
                </td>
                <td className="px-4 py-4"><StatusBadge status={task.status} /></td>
                <td className="px-4 py-4"><p className="max-w-[260px] break-words text-xs leading-5 text-red-700">{task.error || '—'}</p></td>
                <td className="px-5 py-4 text-right">
                  {task.status === 'failed' && task.task_kind === 'pipeline' ? (
                    <button
                      type="button"
                      onClick={() => void retry(task)}
                      disabled={retrying === task.task_id}
                      className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-xs font-medium text-blue-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50"
                    >
                      {retrying === task.task_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                      重新排队
                    </button>
                  ) : <span className="text-xs text-slate-400">无需操作</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!visibleTasks.length && <EmptyState title="当前筛选下没有任务" description="切换状态筛选可以查看其他任务。" />}
      </div>
    </section>
  );
}

function ModelsPanel({ data }: { data: AdminModels }) {
  return (
    <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <section className="rounded-2xl bg-white p-6 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">服务商凭据</h2>
            <p className="mt-1 text-sm text-slate-600">密钥只显示末四位，完整内容不会返回浏览器。</p>
          </div>
          <KeyRound className="h-5 w-5 text-blue-700" />
        </div>
        <div className="mt-5 divide-y divide-slate-100">
          {data.providers.map(provider => (
            <div key={provider.id} className="flex items-center gap-4 py-4 first:pt-0 last:pb-0">
              <div className={`h-2.5 w-2.5 shrink-0 rounded-full ${provider.configured ? 'bg-emerald-500' : 'bg-slate-300'}`} />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-slate-900">{PROVIDER_LABELS[provider.id] || provider.id}</p>
                <p className="mt-1 truncate text-xs text-slate-500">{provider.base_url}</p>
              </div>
              <div className="text-right">
                <p className="text-xs font-medium text-slate-700">{provider.configured ? provider.credential_hint : '未配置'}</p>
                <p className="mt-1 text-[11px] text-slate-500">
                  {provider.credential_source === 'environment' ? '环境变量' : provider.credential_source === 'admin' ? '管理端保存' : '等待配置'}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl bg-white p-6 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Agent 模型分配</h2>
            <p className="mt-1 text-sm text-slate-600">最近配置：{formatDate(data.config_updated_at)}</p>
          </div>
          <Link
            href="/settings"
            className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-[#0b1d43] px-4 text-sm font-medium text-white hover:bg-[#132c5f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            <Settings className="h-4 w-4" />
            配置与连接测试
          </Link>
        </div>
        <div className="mt-6 grid gap-x-8 gap-y-5 sm:grid-cols-2">
          {Object.entries(data.assignments).map(([key, model]) => (
            <div key={key} className="min-w-0 border-b border-slate-100 pb-4">
              <p className="text-xs font-medium text-slate-500">{MODEL_LABELS[key] || key}</p>
              <p className="mt-1 truncate text-sm font-medium text-slate-900" title={model}>{model || '未选择'}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SystemPanel({ data }: { data: AdminSystem }) {
  const items = [
    { label: 'API 服务', detail: `版本 ${data.service.version}`, status: data.service.status, icon: Server },
    { label: 'PostgreSQL 数据库', detail: '用户、任务和配置持久化', status: data.database.status, icon: Database },
    { label: '用户认证', detail: `${data.authentication.mode} · ${data.authentication.registration_enabled ? '开放注册' : '关闭注册'}`, status: data.authentication.status, icon: ShieldCheck },
    { label: '任务队列', detail: `${data.queue.active} 执行中 · ${data.queue.pending} 等待 · 并发 ${data.queue.concurrency}`, status: data.queue.running || !data.queue.enabled ? 'ready' : 'not_ready', icon: Clock3 },
    { label: '运行存储', detail: data.storage.path, status: data.storage.status, icon: FileClock },
  ];
  return (
    <section className="rounded-2xl bg-white p-6 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
      <h2 className="text-lg font-semibold text-slate-950">服务健康状态</h2>
      <p className="mt-1 text-sm text-slate-600">用于判断故障来自认证、数据库、队列还是运行存储。</p>
      <div className="mt-6 divide-y divide-slate-100">
        {items.map(item => {
          const Icon = item.icon;
          const healthy = item.status === 'ready';
          return (
            <div key={item.label} className="flex items-center gap-4 py-5 first:pt-0 last:pb-0">
              <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${healthy ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-slate-900">{item.label}</p>
                <p className="mt-1 truncate text-sm text-slate-600" title={item.detail}>{item.detail}</p>
              </div>
              {healthy ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" /> : <XCircle className="h-5 w-5 shrink-0 text-red-600" />}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AuditPanel({ logs }: { logs: AuditLog[] }) {
  return (
    <section className="rounded-2xl bg-white p-6 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.65)]">
      <h2 className="text-lg font-semibold text-slate-950">管理员操作记录</h2>
      <p className="mt-1 text-sm text-slate-600">记录配置变更、用户调整和任务重试，日志不可在后台修改。</p>
      {logs.length ? (
        <div className="mt-6 divide-y divide-slate-100">
          {logs.map(log => (
            <div key={log.id} className="grid gap-2 py-4 first:pt-0 last:pb-0 sm:grid-cols-[170px_1fr_auto] sm:items-center">
              <div>
                <p className="text-xs font-medium text-slate-700">{log.actor_email}</p>
                <p className="mt-1 text-xs text-slate-500">{formatDate(log.created_at)}</p>
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">{ACTION_LABELS[log.action] || log.action}</p>
                <p className="mt-1 truncate text-xs text-slate-500">{log.target_type} · {log.target_id || '全局配置'}</p>
              </div>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">已记录</span>
            </div>
          ))}
        </div>
      ) : <EmptyState title="还没有管理员操作" description="首次修改用户、任务或模型配置后，这里会留下审计记录。" />}
    </section>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>('overview');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [tasks, setTasks] = useState<AdminTask[]>([]);
  const [models, setModels] = useState<AdminModels | null>(null);
  const [system, setSystem] = useState<AdminSystem | null>(null);
  const [audit, setAudit] = useState<AuditLog[]>([]);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError('');
    try {
      const [nextOverview, nextUsers, nextTasks, nextModels, nextSystem, nextAudit] = await Promise.all([
        adminApi.overview(),
        adminApi.users(),
        adminApi.tasks(),
        adminApi.models(),
        adminApi.system(),
        adminApi.audit(),
      ]);
      setOverview(nextOverview);
      setUsers(nextUsers.users);
      setTasks(nextTasks.tasks);
      setModels(nextModels);
      setSystem(nextSystem);
      setAudit(nextAudit.logs);
    } catch (err) {
      setError(err instanceof Error ? err.message : '管理员数据读取失败，请稍后重试。');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { void load(true); }, [load]);

  const reloadAfterAction = useCallback(async () => {
    await load(false);
  }, [load]);

  return (
    <div className="min-h-screen bg-[#f4f7fb]">
      <BrandHeader />
      <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.025em] text-slate-950">把用户、任务和模型成本控制在可见范围内</h1>
            <p className="mt-2 max-w-[72ch] text-sm leading-6 text-slate-600">
              这里只提供测试运营必需的控制：账号状态、每日额度、失败任务、模型凭据状态和管理员审计。
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load(false)}
            disabled={refreshing}
            className="inline-flex h-10 items-center justify-center gap-2 self-start rounded-xl bg-white px-4 text-sm font-medium text-slate-700 shadow-[0_8px_24px_-18px_rgba(15,23,42,0.8)] hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50 lg:self-auto"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            刷新数据
          </button>
        </div>

        <div className="mt-7 overflow-x-auto border-b border-slate-200">
          <nav className="flex min-w-max gap-6" aria-label="管理员模块">
            {TABS.map(item => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={`relative h-11 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-blue-600 ${tab === item.id ? 'text-blue-700' : 'text-slate-600 hover:text-slate-950'}`}
                aria-current={tab === item.id ? 'page' : undefined}
              >
                {item.label}
                {tab === item.id && <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-blue-600" />}
              </button>
            ))}
          </nav>
        </div>

        {error && (
          <div className="mt-6 flex items-start gap-3 rounded-2xl bg-red-50 p-4 text-sm text-red-800" role="alert">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
            <div className="flex-1">
              <p className="font-medium">管理员数据暂时不可用</p>
              <p className="mt-1 leading-6">{error}</p>
            </div>
            <button type="button" onClick={() => void load(false)} className="font-medium underline decoration-red-300 underline-offset-4">重试</button>
          </div>
        )}

        <div className="mt-6">
          {loading ? <LoadingRows /> : (
            <>
              {tab === 'overview' && overview && <OverviewPanel data={overview} />}
              {tab === 'users' && <UsersPanel users={users} onUpdated={reloadAfterAction} />}
              {tab === 'tasks' && <TasksPanel tasks={tasks} onRetried={reloadAfterAction} />}
              {tab === 'models' && models && <ModelsPanel data={models} />}
              {tab === 'system' && system && <SystemPanel data={system} />}
              {tab === 'audit' && <AuditPanel logs={audit} />}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
