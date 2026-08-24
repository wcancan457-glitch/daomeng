'use client';

import Image from 'next/image';
import {
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Mail,
  Sparkles,
  UserRound,
} from 'lucide-react';
import {
  createContext,
  FormEvent,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  fetchAuthStatus,
  fetchCurrentUser,
  getAccessToken,
  loginAccount,
  onAuthRequired,
  registerAccount,
  type AuthStatus,
  type AuthUser,
} from '@/lib/auth';

type GateState = 'checking' | 'allowed' | 'login' | 'unconfigured' | 'offline';
type FormMode = 'login' | 'register';

type AuthContextValue = {
  status: AuthStatus | null;
  user: AuthUser | null;
};

const AuthContext = createContext<AuthContextValue>({ status: null, user: null });

export function useAuth() {
  return useContext(AuthContext);
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>('checking');
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [formMode, setFormMode] = useState<FormMode>('login');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const check = useCallback(async () => {
    setState('checking');
    setError('');
    try {
      const nextStatus = await fetchAuthStatus();
      setStatus(nextStatus);
      if (!nextStatus.required) {
        setState('allowed');
        return;
      }
      if (!nextStatus.configured) {
        setState('unconfigured');
        return;
      }
      if (nextStatus.mode === 'users') {
        try {
          setUser(await fetchCurrentUser());
          setState('allowed');
        } catch {
          setUser(null);
          setState('login');
        }
        return;
      }
      setState(getAccessToken() ? 'allowed' : 'login');
    } catch (err) {
      setError(err instanceof Error ? err.message : '暂时无法连接后端服务');
      setState('offline');
    }
  }, []);

  useEffect(() => {
    void check();
    return onAuthRequired(() => {
      setUser(null);
      setState('login');
    });
  }, [check]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!status || !password || (status.mode === 'users' && !email.trim())) return;
    if (formMode === 'register' && password.length < 10) {
      setError('密码至少需要 10 个字符。');
      return;
    }
    if (formMode === 'register' && password !== passwordConfirmation) {
      setError('两次输入的密码不一致，请重新确认。');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      if (formMode === 'register') {
        const registeredUser = await registerAccount({
          email: email.trim(),
          password,
          displayName: displayName.trim(),
        });
        setUser(registeredUser);
        window.localStorage.setItem('daomeng.show-welcome', 'true');
      } else {
        setUser(
          await loginAccount({
            mode: status.mode,
            email: status.mode === 'users' ? email.trim() : undefined,
            password,
          }),
        );
      }
      setPassword('');
      setPasswordConfirmation('');
      setState('allowed');
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请稍后再试');
    } finally {
      setSubmitting(false);
    }
  }

  const contextValue = useMemo(() => ({ status, user }), [status, user]);
  if (state === 'allowed') {
    return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>;
  }

  const userMode = status?.mode === 'users';
  const canRegister = userMode && status?.registration_enabled;

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#edf2ff] px-4 py-8 text-slate-950 sm:px-6">
      <div aria-hidden="true" className="absolute -left-24 top-16 h-64 w-64 rounded-full bg-[#dbe6ff]" />
      <div aria-hidden="true" className="absolute -bottom-28 right-[-3rem] h-80 w-80 rounded-full bg-[#d8e3ff]" />
      <section className="relative grid w-full max-w-4xl overflow-hidden rounded-2xl bg-white shadow-[0_28px_80px_-36px_rgba(15,31,74,0.55)] md:grid-cols-[0.92fr_1.08fr]">
        <div className="hidden min-h-[620px] flex-col justify-between bg-[#071735] p-10 text-white md:flex">
          <div className="flex items-center gap-3">
            <Image
              src="/logo.jpg"
              alt="导梦 logo"
              width={52}
              height={52}
              priority
              className="rounded-xl object-cover shadow-[0_12px_28px_-12px_rgba(75,116,255,0.85)]"
            />
            <div>
              <p className="text-xl font-semibold tracking-[-0.02em]">导梦</p>
              <p className="mt-0.5 text-sm text-blue-100">AI 影像创作工作台</p>
            </div>
          </div>

          <div className="max-w-sm">
            <Sparkles className="mb-5 h-7 w-7 text-[#8fb2ff]" />
            <h1 className="text-balance text-4xl font-semibold leading-tight tracking-[-0.035em]">
              从一个想法，走到完整影像。
            </h1>
            <p className="mt-5 max-w-[34ch] text-base leading-7 text-blue-100">
              剧本、角色、分镜、参考图与视频生成，在同一条可回看的创作流程中完成。
            </p>
          </div>

          <p className="text-xs leading-5 text-blue-200/80">你的项目和生成记录仅对当前账号可见。</p>
        </div>

        <div className="flex min-h-[560px] flex-col justify-center p-6 sm:p-10 md:p-12">
          <div className="mb-8 flex items-center gap-3 md:hidden">
            <Image src="/logo.jpg" alt="导梦 logo" width={44} height={44} priority className="rounded-xl object-cover" />
            <div>
              <p className="font-semibold">导梦</p>
              <p className="text-xs text-slate-600">AI 影像创作工作台</p>
            </div>
          </div>

          {state === 'checking' && (
            <div className="flex items-center gap-3 text-sm text-slate-700" role="status">
              <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
              正在确认登录状态…
            </div>
          )}

          {state === 'login' && status && (
            <>
              <div className="mb-7">
                <h2 className="text-3xl font-semibold tracking-[-0.03em]">
                  {formMode === 'register' ? '创建导梦账号' : '欢迎回来'}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {formMode === 'register'
                    ? '注册后即可保存自己的项目、任务和生成内容。'
                    : userMode
                      ? '登录后继续你的影像创作。'
                      : '请输入管理员提供的访问密码。'}
                </p>
              </div>

              {canRegister && (
                <div className="mb-6 grid grid-cols-2 rounded-xl bg-slate-100 p-1" aria-label="账号操作">
                  {(['login', 'register'] as FormMode[]).map(mode => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => {
                        setFormMode(mode);
                        setError('');
                        setPassword('');
                        setPasswordConfirmation('');
                        setShowPassword(false);
                      }}
                      className={`h-10 rounded-lg text-sm font-medium transition ${
                        formMode === mode
                          ? 'bg-white text-slate-950 shadow-[0_5px_16px_-10px_rgba(15,23,42,0.8)]'
                          : 'text-slate-600 hover:text-slate-950'
                      }`}
                      aria-pressed={formMode === mode}
                    >
                      {mode === 'login' ? '登录' : '注册'}
                    </button>
                  ))}
                </div>
              )}

              <form onSubmit={submit} className="space-y-4">
                {userMode && formMode === 'register' && (
                  <label className="block text-sm font-medium text-slate-800" htmlFor="display-name">
                    昵称 <span className="font-normal text-slate-500">（选填）</span>
                    <span className="relative mt-2 block">
                      <UserRound className="pointer-events-none absolute left-3.5 top-1/2 h-4.5 w-4.5 -translate-y-1/2 text-slate-500" />
                      <input
                        id="display-name"
                        value={displayName}
                        onChange={event => setDisplayName(event.target.value)}
                        autoComplete="name"
                        maxLength={80}
                        className="h-12 w-full rounded-xl bg-slate-100 pl-11 pr-4 text-slate-950 outline-none ring-1 ring-transparent transition placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-blue-600"
                        placeholder="怎么称呼你"
                      />
                    </span>
                  </label>
                )}

                {userMode && (
                  <label className="block text-sm font-medium text-slate-800" htmlFor="account-email">
                    邮箱
                    <span className="relative mt-2 block">
                      <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4.5 w-4.5 -translate-y-1/2 text-slate-500" />
                      <input
                        id="account-email"
                        type="email"
                        value={email}
                        onChange={event => setEmail(event.target.value)}
                        autoComplete="email"
                        required
                        className="h-12 w-full rounded-xl bg-slate-100 pl-11 pr-4 text-slate-950 outline-none ring-1 ring-transparent transition placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-blue-600"
                        placeholder="name@example.com"
                      />
                    </span>
                  </label>
                )}

                <label className="block text-sm font-medium text-slate-800" htmlFor="account-password">
                  {userMode ? '密码' : '访问密码'}
                  <span className="relative mt-2 block">
                    <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 h-4.5 w-4.5 -translate-y-1/2 text-slate-500" />
                    <input
                      id="account-password"
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={event => setPassword(event.target.value)}
                      autoComplete={formMode === 'register' ? 'new-password' : 'current-password'}
                      minLength={formMode === 'register' ? 10 : 1}
                      required
                      className="h-12 w-full rounded-xl bg-slate-100 pl-11 pr-12 text-slate-950 outline-none ring-1 ring-transparent transition placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-blue-600"
                      placeholder={formMode === 'register' ? '至少 10 个字符' : '输入密码'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(value => !value)}
                      className="absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-200 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
                      aria-label={showPassword ? '隐藏密码' : '显示密码'}
                    >
                      {showPassword ? <EyeOff className="h-4.5 w-4.5" /> : <Eye className="h-4.5 w-4.5" />}
                    </button>
                  </span>
                </label>

                {userMode && formMode === 'register' && (
                  <label className="block text-sm font-medium text-slate-800" htmlFor="password-confirmation">
                    确认密码
                    <span className="relative mt-2 block">
                      <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 h-4.5 w-4.5 -translate-y-1/2 text-slate-500" />
                      <input
                        id="password-confirmation"
                        type={showPassword ? 'text' : 'password'}
                        value={passwordConfirmation}
                        onChange={event => setPasswordConfirmation(event.target.value)}
                        autoComplete="new-password"
                        minLength={10}
                        required
                        aria-invalid={Boolean(passwordConfirmation && password !== passwordConfirmation)}
                        aria-describedby="password-confirmation-hint"
                        className="h-12 w-full rounded-xl bg-slate-100 pl-11 pr-4 text-slate-950 outline-none ring-1 ring-transparent transition placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-blue-600"
                        placeholder="再次输入密码"
                      />
                    </span>
                    <span id="password-confirmation-hint" className="mt-2 block text-xs leading-5 text-slate-600">
                      {passwordConfirmation && password !== passwordConfirmation
                        ? '两次输入的密码尚不一致'
                        : '密码至少 10 个字符'}
                    </span>
                  </label>
                )}

                {error && (
                  <p className="rounded-xl bg-red-50 px-4 py-3 text-sm leading-5 text-red-800" role="alert">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={
                    submitting ||
                    !password ||
                    (userMode && !email.trim()) ||
                    (formMode === 'register' && (!passwordConfirmation || password !== passwordConfirmation))
                  }
                  className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#0b1d43] font-medium text-white shadow-[0_12px_28px_-16px_rgba(11,29,67,0.95)] transition hover:bg-[#132c5f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? (
                    <>
                      <Loader2 className="h-5 w-5 animate-spin" />
                      {formMode === 'register' ? '正在创建账号' : '正在登录'}
                    </>
                  ) : (
                    <>
                      {formMode === 'register' ? '创建账号' : '进入导梦'}
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>
            </>
          )}

          {state === 'unconfigured' && (
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.025em]">登录服务尚未配置</h2>
              <p className="mt-3 rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900" role="alert">
                后端已启用安全保护，但缺少登录密钥。请管理员完成 AUTH_TOKEN_SECRET 或访问密码配置后重新部署。
              </p>
            </div>
          )}

          {state === 'offline' && (
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.025em]">暂时无法连接服务</h2>
              <p className="mt-3 rounded-xl bg-red-50 p-4 text-sm leading-6 text-red-800" role="alert">{error}</p>
              <button
                type="button"
                onClick={() => void check()}
                className="mt-5 h-11 w-full rounded-xl bg-[#0b1d43] text-sm font-medium text-white hover:bg-[#132c5f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
              >
                重新连接
              </button>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
