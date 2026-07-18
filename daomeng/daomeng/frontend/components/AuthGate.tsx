'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { KeyRound, Loader2, LockKeyhole } from 'lucide-react';
import {
  fetchAuthStatus,
  getAccessToken,
  loginWithPassword,
  onAuthRequired,
  type AuthStatus,
} from '@/lib/auth';

type GateState = 'checking' | 'allowed' | 'login' | 'unconfigured' | 'offline';

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>('checking');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const check = useCallback(async () => {
    setState('checking');
    setError('');
    try {
      const status: AuthStatus = await fetchAuthStatus();
      if (!status.required) setState('allowed');
      else if (!status.configured) setState('unconfigured');
      else setState(getAccessToken() ? 'allowed' : 'login');
    } catch (err) {
      setError(err instanceof Error ? err.message : '暂时无法连接后端服务');
      setState('offline');
    }
  }, []);

  useEffect(() => {
    void check();
    return onAuthRequired(() => setState('login'));
  }, [check]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      await loginWithPassword(password);
      setPassword('');
      setState('allowed');
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后再试');
    } finally {
      setSubmitting(false);
    }
  }

  if (state === 'allowed') return children;

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-5 py-12 text-slate-900">
      <section className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-8 shadow-xl shadow-slate-200/50">
        <div className="mb-7 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 text-xl font-bold text-white shadow-lg shadow-blue-200">
            导
          </div>
          <div>
            <h1 className="text-2xl font-bold">导梦</h1>
            <p className="mt-0.5 text-sm text-slate-500">AI 影像创作工作台</p>
          </div>
        </div>

        {state === 'checking' && (
          <div className="flex items-center gap-3 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
            <Loader2 className="h-5 w-5 animate-spin" /> 正在连接服务…
          </div>
        )}

        {state === 'login' && (
          <form onSubmit={submit}>
            <div className="mb-5 flex items-start gap-3 rounded-2xl bg-blue-50 p-4 text-sm text-blue-900">
              <LockKeyhole className="mt-0.5 h-5 w-5 shrink-0" />
              <p>这是受保护的测试版本。请输入产品管理员提供的访问密码。</p>
            </div>
            <label className="mb-2 block text-sm font-medium" htmlFor="access-password">访问密码</label>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                id="access-password"
                autoFocus
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-12 w-full rounded-xl border border-slate-300 bg-white pl-11 pr-3 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                placeholder="请输入访问密码"
              />
            </div>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={submitting || !password.trim()}
              className="mt-5 flex h-12 w-full items-center justify-center rounded-xl bg-slate-900 font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : '进入导梦'}
            </button>
          </form>
        )}

        {state === 'unconfigured' && (
          <div className="rounded-2xl bg-amber-50 p-4 text-sm text-amber-900">
            后端安全保护已启用，但 Render 还没有设置访问密码。请管理员添加 APP_ACCESS_PASSWORD 后重新部署。
          </div>
        )}

        {state === 'offline' && (
          <div>
            <div className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">{error}</div>
            <button onClick={() => void check()} className="mt-4 h-11 w-full rounded-xl border border-slate-300 font-medium hover:bg-slate-50">
              重新连接
            </button>
          </div>
        )}
      </section>
    </main>
  );
}
