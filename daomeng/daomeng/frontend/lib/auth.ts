const TOKEN_KEY = 'daomeng.access-token';
const AUTH_REQUIRED_EVENT = 'daomeng-auth-required';

export type AuthStatus = {
  required: boolean;
  configured: boolean;
};

function canUseBrowserStorage() {
  return typeof window !== 'undefined';
}

export function getAccessToken(): string {
  if (!canUseBrowserStorage()) return '';
  return window.sessionStorage.getItem(TOKEN_KEY) || '';
}

export function setAccessToken(token: string) {
  if (!canUseBrowserStorage()) return;
  if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
  else window.sessionStorage.removeItem(TOKEN_KEY);
}

export function clearAccessToken() {
  if (!canUseBrowserStorage()) return;
  window.sessionStorage.removeItem(TOKEN_KEY);
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

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const response = await fetch('/api/auth/status', { cache: 'no-store' });
  if (!response.ok) throw new Error('暂时无法连接后端服务');
  return response.json();
}

export async function loginWithPassword(password: string): Promise<void> {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || '登录失败，请稍后再试');
  setAccessToken(payload.access_token || '');
}

export async function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  const token = getAccessToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) notifyAuthRequired();
  return response;
}

export function authenticatedUrl(input: string): string {
  const token = getAccessToken();
  if (!token || typeof window === 'undefined') return input;
  const url = new URL(input, window.location.origin);
  url.searchParams.set('access_token', token);
  return url.toString();
}
