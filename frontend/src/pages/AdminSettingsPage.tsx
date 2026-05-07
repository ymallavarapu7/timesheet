import React, { useState } from 'react';
import { SettingsSidebar, SettingsContent } from '@/components/settings';

export const AdminSettingsPage: React.FC = () => {
  const [activeSection, setActiveSection] = useState(() => {
    const hash = window.location.hash.replace('#', '');
    return hash || 'time-entry';
  });

  const handleChange = (key: string) => {
    setActiveSection(key);
    window.location.hash = key;
  };

  return (
    <>
      <div className="fixed inset-x-0 bottom-0 top-[60px] flex bg-background z-10 border-t border-border/50">
        <SettingsSidebar activeSection={activeSection} onChange={handleChange} />
        <SettingsContent activeSection={activeSection} />
      </div>
    </>
  );
};
