const LEGACY_TOKEN_KEY = 'daomeng.shared-access-token';
const AUTH_REQUIRED_EVENT = 'daomeng-auth-required';

export type AuthMode = 'disabled' | 'shared' | 'users';

export type AuthStatus = {
  required: boolean;
  configured: boolean;
  mode: AuthMode;
  registration_enabled: boolean;
};

export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  role: 'admin' | 'user' | string;
  email_verified: boolean;
  created_at: string;
};

type SessionPayload = {
  access_token?: string;
  user?: AuthUser;
};

let accessToken = '';
let refreshPromise: Promise<boolean> | null = null;

function canUseBrowserStorage() {
  return typeof window !== 'undefined';
}

export function getAccessToken(): string {
  if (accessToken) return accessToken;
  if (!canUseBrowserStorage()) return '';
  return window.sessionStorage.getItem(LEGACY_TOKEN_KEY) || '';
}

export function setAccessToken(token: string, persistForSharedMode = false) {
  accessToken = token;
  if (!canUseBrowserStorage()) return;
  if (persistForSharedMode && token) window.sessionStorage.setItem(LEGACY_TOKEN_KEY, token);
  else window.sessionStorage.removeItem(LEGACY_TOKEN_KEY);
}

export function clearAccessToken() {
  accessToken = '';
  if (canUseBrowserStorage()) window.sessionStorage.removeItem(LEGACY_TOKEN_KEY);
}

export function notifyAuthRequired() {
  if (!canUseBrowserStorage()) return;
  clearAccessToken();
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

export function onAuthRequired(listener: () => void) {
  if (!canUseBrowserStorage()) return () => undefined;
  window.addEventListener(AUTH_REQUIRED_EVENT, listener);
  return () => window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
}

async function responseError(response: Response, fallback: string): Promise<Error> {
  const payload = await response.json().catch(() => ({}));
  return new Error(typeof payload.detail === 'string' ? payload.detail : fallback);
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const response = await fetch('/api/auth/status', { cache: 'no-store' });
  if (!response.ok) throw new Error('暂时无法连接后端服务');
  const payload = await response.json();
  return {
    required: Boolean(payload.required),
    configured: Boolean(payload.configured),
    mode: payload.mode || (payload.required ? 'shared' : 'disabled'),
    registration_enabled: Boolean(payload.registration_enabled),
  };
}

export async function loginAccount(values: {
  mode: AuthMode;
  email?: string;
  password: string;
}): Promise<AuthUser | null> {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: values.email || undefined, password: values.password }),
  });
  if (!response.ok) throw await responseError(response, '登录失败，请稍后再试');
  const payload: SessionPayload = await response.json();
  setAccessToken(payload.access_token || '', values.mode === 'shared');
  return payload.user || null;
}

export async function registerAccount(values: {
  email: string;
  password: string;
  displayName: string;
}): Promise<AuthUser> {
  const response = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: values.email,
      password: values.password,
      display_name: values.displayName,
    }),
  });
  if (!response.ok) throw await responseError(response, '注册失败，请稍后再试');
  const payload: SessionPayload = await response.json();
  if (!payload.user) throw new Error('注册成功，但未能读取账号资料，请重新登录');
  setAccessToken(payload.access_token || '');
  return payload.user;
}

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const response = await fetch('/api/auth/refresh', { method: 'POST' });
      if (!response.ok) {
        clearAccessToken();
        return false;
      }
      const payload: SessionPayload = await response.json();
      setAccessToken(payload.access_token || '');
      return Boolean(payload.access_token);
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function isAuthEndpoint(input: RequestInfo | URL): boolean {
  const value = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url;
  return ['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/api/auth/logout']
    .some(path => value.includes(path));
}

export async function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const request = async () => {
    const headers = new Headers(init.headers || {});
    const token = getAccessToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return fetch(input, { ...init, headers });
  };

  let response = await request();
  if (response.status === 401 && !isAuthEndpoint(input)) {
    if (await refreshAccessToken()) response = await request();
    if (response.status === 401) notifyAuthRequired();
  }
  return response;
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await authenticatedFetch('/api/auth/me', { cache: 'no-store' });
  if (!response.ok) throw await responseError(response, '登录已过期，请重新登录');
  const payload = await response.json();
  return payload.user as AuthUser;
}

export async function logoutAccount(): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } finally {
    notifyAuthRequired();
  }
}
