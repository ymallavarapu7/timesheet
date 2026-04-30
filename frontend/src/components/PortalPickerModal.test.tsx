import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PortalPickerModal } from './PortalPickerModal';

describe('PortalPickerModal', () => {
  it('does not render when isOpen is false', () => {
    const { container } = render(
      <PortalPickerModal isOpen={false} roles={['ADMIN', 'MANAGER']} onPick={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders one button per role with friendly labels', () => {
    render(
      <PortalPickerModal isOpen roles={['ADMIN', 'MANAGER']} onPick={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: /continue as admin/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue as manager/i })).toBeInTheDocument();
  });

  it('calls onPick with the chosen role', () => {
    const onPick = vi.fn();
    render(
      <PortalPickerModal isOpen roles={['ADMIN', 'MANAGER']} onPick={onPick} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /continue as manager/i }));
    expect(onPick).toHaveBeenCalledWith('MANAGER');
  });

  it('marks the current role as last used', () => {
    render(
      <PortalPickerModal isOpen roles={['ADMIN', 'MANAGER']} currentRole="ADMIN" onPick={vi.fn()} />,
    );
    const adminBtn = screen.getByRole('button', { name: /continue as admin/i });
    expect(adminBtn).toHaveTextContent(/last used/i);
    const managerBtn = screen.getByRole('button', { name: /continue as manager/i });
    expect(managerBtn).not.toHaveTextContent(/last used/i);
  });

  it('disables buttons when pending is true', () => {
    render(
      <PortalPickerModal isOpen roles={['ADMIN', 'MANAGER']} onPick={vi.fn()} pending />,
    );
    expect(screen.getByRole('button', { name: /continue as admin/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /continue as manager/i })).toBeDisabled();
  });
});
