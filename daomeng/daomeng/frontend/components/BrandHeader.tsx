'use client';

import Link from 'next/link';

export default function BrandHeader() {
  return (
    <>
      <header className="fixed top-0 right-0 left-[var(--app-sidebar-width)] z-30 h-14 bg-white border-b border-gray-200 flex items-center px-4 min-w-0 transition-[left] duration-300">
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity flex-shrink-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 via-sky-500 to-emerald-400 text-sm font-bold text-white shadow-sm">导</div>
          <span className="font-bold text-sm text-gray-800 tracking-tight">
            导梦
          </span>
        </Link>
      </header>
      <div className="h-14 flex-shrink-0" />
    </>
  );
}
