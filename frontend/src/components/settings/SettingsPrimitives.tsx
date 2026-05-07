import React from 'react';

export const SectionWrapper: React.FC<{
  title: string;
  desc: string;
  children: React.ReactNode;
}> = ({ title, desc, children }) => (
  <div className="w-full max-w-[1400px] animate-in fade-in slide-in-from-bottom-2 duration-300">
    <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
    <p className="text-[12.5px] text-muted-foreground mt-1 mb-5 leading-relaxed">{desc}</p>
    <div className="space-y-4">{children}</div>
  </div>
);

export const Card: React.FC<{
  title: string;
  desc?: string;
  children: React.ReactNode;
}> = ({ title, desc, children }) => (
  <div className="rounded-xl border border-border bg-card p-[18px]">
    <h2 className="text-[13px] font-medium text-foreground">{title}</h2>
    {desc && <p className="text-[11.5px] text-muted-foreground leading-[1.45] mt-0.5 mb-3">{desc}</p>}
    {!desc && <div className="mb-3" />}
    {children}
  </div>
);

export const SaveRow: React.FC<{
  onSave: () => void;
  disabled?: boolean;
  label?: string;
}> = ({ onSave, disabled, label = 'Save' }) => (
  <div className="flex justify-end mt-[14px]">
    <button
      type="button"
      className="action-button text-sm disabled:opacity-50"
      disabled={disabled}
      onClick={onSave}
    >
      {label}
    </button>
  </div>
);

export const FormGrid: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
);

export const Field: React.FC<{
  label: string;
  hint?: string;
  children: React.ReactNode;
}> = ({ label, hint, children }) => (
  <div>
    <label className="block text-[11px] font-medium text-muted-foreground mb-1">{label}</label>
    {children}
    {hint && <p className="text-[10.5px] text-muted-foreground/60 mt-0.5">{hint}</p>}
  </div>
);

export const ToggleRow: React.FC<{
  label: string;
  desc?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}> = ({ label, desc, checked, onChange }) => (
  <div className="flex items-center justify-between py-[9px] border-b border-border/40 last:border-0">
    <div className="pr-4">
      <p className="text-[12.5px] font-medium text-foreground">{label}</p>
      {desc && <p className="text-[11px] text-muted-foreground mt-0.5">{desc}</p>}
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`
        relative shrink-0 w-[34px] h-[18px] rounded-full transition-colors duration-200
        ${checked ? 'bg-primary' : 'bg-muted-foreground/30'}
      `}
    >
      <span
        className={`
          absolute top-[2px] left-[2px] h-[14px] w-[14px] rounded-full bg-white shadow-sm
          transition-transform duration-200 ${checked ? 'translate-x-[16px]' : 'translate-x-0'}
        `}
      />
    </button>
  </div>
);

export const InfoBanner: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="rounded-xl border border-primary/20 bg-primary/[0.04] px-4 py-3 text-[12px] text-muted-foreground leading-relaxed">
    {children}
  </div>
);
