import React from 'react';

// Minimal, single-weight line icons — replaces emoji/unicode glyphs (🗑, ⚠, ✓,
// ✕, →, ←, ↺, ⛔, ⬚, 📐) used throughout the app previously. Kept deliberately
// plain (1.5px stroke, no fill) so they read as UI chrome, not illustration.

type IconProps = { size?: number; className?: string; style?: React.CSSProperties };
const base = (size = 16) => ({
  width: size, height: size, viewBox: '0 0 20 20', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
});

export const TrashIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M4 6h12M8 6V4.5A1.5 1.5 0 0 1 9.5 3h1A1.5 1.5 0 0 1 12 4.5V6M6 6l.6 9.4A1.5 1.5 0 0 0 8.1 17h3.8a1.5 1.5 0 0 0 1.5-1.6L14 6" />
  </svg>
);

export const WarningIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M10 3.2 17.5 16H2.5L10 3.2Z" />
    <path d="M10 8.3v3.4" />
    <circle cx="10" cy="14" r="0.15" fill="currentColor" stroke="none" />
  </svg>
);

export const CheckIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M4 10.5 8 14.5 16 5.5" />
  </svg>
);

export const CrossIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M5 5l10 10M15 5 5 15" />
  </svg>
);

export const ArrowRightIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M4 10h12M11 5l5 5-5 5" />
  </svg>
);

export const ArrowLeftIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M16 10H4M9 5l-5 5 5 5" />
  </svg>
);

export const RefreshIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M16 10a6 6 0 1 1-2-4.5" />
    <path d="M16 3.5V7h-3.5" />
  </svg>
);

export const BlockedIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <circle cx="10" cy="10" r="7" />
    <path d="M5.3 5.3l9.4 9.4" />
  </svg>
);

export const EmptyIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <rect x="4" y="4" width="12" height="12" rx="2" strokeDasharray="2.5 2.5" />
  </svg>
);

export const UploadIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M10 13V4M6.5 7.5 10 4l3.5 3.5" />
    <path d="M4 15.5h12" />
  </svg>
);

export const DownloadIcon: React.FC<IconProps> = ({ size, className, style }) => (
  <svg {...base(size)} className={className} style={style}>
    <path d="M10 4v9M6.5 9.5 10 13l3.5-3.5" />
    <path d="M4 15.5h12" />
  </svg>
);
