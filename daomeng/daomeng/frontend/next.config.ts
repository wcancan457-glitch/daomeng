import type { NextConfig } from "next";

const apiBase =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  'http://127.0.0.1:8000';

const nextConfig: NextConfig = {
  agentRules: false,
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'same-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: '/code/:path*',
        destination: `${apiBase}/code/:path*`,
      },
      {
        source: '/api/sessions',
        destination: `${apiBase}/api/sessions`,
      },
      {
        source: '/api/sessions/:path*',
        destination: `${apiBase}/api/sessions/:path*`,
      },
      // 工作流 API
      {
        source: '/api/project/:path*',
        destination: `${apiBase}/api/project/:path*`,
      },
      {
        source: '/api/stages',
        destination: `${apiBase}/api/stages`,
      },
      {
        source: '/api/upload_media',
        destination: `${apiBase}/api/upload_media`,
      },
      {
        source: '/api/models',
        destination: `${apiBase}/api/models`,
      },
      {
        source: '/api/auth/:path*',
        destination: `${apiBase}/api/auth/:path*`,
      },
      {
        source: '/api/config',
        destination: `${apiBase}/api/config`,
      },
      {
        source: '/api/cache/:path*',
        destination: `${apiBase}/api/cache/:path*`,
      },
      // 一键 pipeline API
      {
        source: '/api/pipelines',
        destination: `${apiBase}/api/pipelines`,
      },
      {
        source: '/api/pipelines/:path*',
        destination: `${apiBase}/api/pipelines/:path*`,
      },
      {
        source: '/api/tasks',
        destination: `${apiBase}/api/tasks`,
      },
      {
        source: '/api/tasks/:path*',
        destination: `${apiBase}/api/tasks/:path*`,
      },
      // 临时工作台 API
      {
        source: '/api/sandbox/:path*',
        destination: `${apiBase}/api/sandbox/:path*`,
      },
    ];
  },
};

export default nextConfig;
