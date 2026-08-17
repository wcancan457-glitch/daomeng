'use client';

import Link from 'next/link';
import Image from 'next/image';

export default function BrandHeader() {
  return (
    <>
      <header className="fixed top-0 right-0 left-[var(--app-sidebar-width)] z-30 h-14 bg-white border-b border-gray-200 flex items-center px-4 min-w-0 transition-[left] duration-300">
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity flex-shrink-0">
          <Image
            src="/logo.jpg"
            alt=""
            width={32}
            height={32}
            priority
            className="shrink-0 rounded-lg object-cover shadow-sm"
          />
          <span className="font-bold text-sm text-gray-800 tracking-tight">
            导梦
          </span>
        </Link>
      </header>
      <div className="h-14 flex-shrink-0" />
    </>
  );
}
