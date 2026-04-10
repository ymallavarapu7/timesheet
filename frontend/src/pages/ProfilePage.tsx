import React, { useState } from 'react';

import { Error, Loading } from '@/components';
import { useChangePassword, useMyProfile, useUpdateMyProfile } from '@/hooks';

const PASSWORD_REQUIREMENT_TEXT = 'Minimum 8 chars, including uppercase, lowercase, number, and special character.';

const validatePassword = (password: string): string | null => {
  if (password.length < 8) return 'New password must be at least 8 characters';
  if (!/[A-Z]/.test(password)) return 'New password must include at least one uppercase letter';
  if (!/[a-z]/.test(password)) return 'New password must include at least one lowercase letter';
  if (!/\d/.test(password)) return 'New password must include at least one number';
  if (!/[^A-Za-z0-9]/.test(password)) return 'New password must include at least one special character';
  return null;
};

const getRequestErrorDetail = (error: unknown): string | null => {
  if (typeof error === 'object' && error !== null) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    return typeof detail === 'string' ? detail : null;
  }
  return null;
};

export const ProfilePage: React.FC = () => {
  const { data: profile, isLoading, error } = useMyProfile();
  const changePasswordMutation = useChangePassword();
  const updateProfileMutation = useUpdateMyProfile();

  const [fullName, setFullName] = useState('');
  const [title, setTitle] = useState('');
  const [department, setDepartment] = useState('');
  const [profileError, setProfileError] = useState('');
  const [profileSuccess, setProfileSuccess] = useState('');

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [formError, setFormError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  React.useEffect(() => {
    if (profile) {
      setFullName(profile.full_name);
      setTitle(profile.title ?? '');
      setDepartment(profile.department ?? '');
    }
  }, [profile]);

  const handleProfileSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setProfileError('');
    setProfileSuccess('');
    if (!fullName.trim()) {
      setProfileError('Full name is required');
      return;
    }
    try {
      await updateProfileMutation.mutateAsync({
        full_name: fullName.trim(),
        title: title.trim() || undefined,
        department: department.trim() || undefined,
      });
      setProfileSuccess('Profile updated successfully');
    } catch (err: unknown) {
      const detail = getRequestErrorDetail(err);
      setProfileError(detail ?? 'Unable to update profile');
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');
    setSuccessMessage('');

    if (!currentPassword || !newPassword || !confirmPassword) {
      setFormError('All password fields are required');
      return;
    }

    if (newPassword !== confirmPassword) {
      setFormError('New password and confirmation do not match');
      return;
    }

    const validationError = validatePassword(newPassword);
    if (validationError) {
      setFormError(validationError);
      return;
    }

    try {
      const response = await changePasswordMutation.mutateAsync({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccessMessage(response.message || 'Password updated successfully');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: unknown) {
      const detail = getRequestErrorDetail(err);
      setFormError(typeof detail === 'string' ? detail : 'Unable to update password');
    }
  };

  if (isLoading) return <Loading />;
  if (error || !profile) return <Error message="Failed to load profile" />;

  const roleStyles: Record<string, string> = {
    EMPLOYEE: 'bg-blue-100 text-blue-800',
    MANAGER: 'bg-purple-100 text-purple-800',
    ADMIN: 'bg-red-100 text-red-800',
  };

  return (
    <div>
      <div>
        <h1 className="text-3xl font-bold mb-6">My Profile</h1>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <section className="rounded-xl border bg-card p-6">
            <h2 className="text-xl font-semibold mb-4">Profile Details</h2>
            <form onSubmit={handleProfileSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Full Name</label>
                <input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full px-3 py-2 border rounded"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Not set"
                  className="w-full px-3 py-2 border rounded"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Department</label>
                <input
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  placeholder="Not set"
                  className="w-full px-3 py-2 border rounded"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Role</label>
                <div className="w-full px-3 py-2 border rounded bg-muted/20">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${roleStyles[profile.role] || 'bg-muted text-foreground'}`}>
                    {profile.role}
                  </span>
                </div>
              </div>

              {profileError && <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{profileError}</p>}
              {profileSuccess && <p className="text-sm text-emerald-700 bg-emerald-50 px-3 py-2 rounded">{profileSuccess}</p>}

              <button
                type="submit"
                disabled={updateProfileMutation.isPending}
                className="w-full px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
              >
                {updateProfileMutation.isPending ? 'Saving...' : 'Save Changes'}
              </button>
            </form>
          </section>

          <section className="rounded-xl border bg-card p-6">
            <h2 className="text-xl font-semibold mb-4">Update Password</h2>
            <p className="text-sm text-muted-foreground mb-4">{PASSWORD_REQUIREMENT_TEXT}</p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Current Password</label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  className="w-full px-3 py-2 border rounded"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">New Password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  className="w-full px-3 py-2 border rounded"
                  required
                  minLength={8}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Confirm New Password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  className="w-full px-3 py-2 border rounded"
                  required
                  minLength={8}
                />
              </div>

              {formError && <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{formError}</p>}
              {successMessage && <p className="text-sm text-emerald-700 bg-emerald-50 px-3 py-2 rounded">{successMessage}</p>}

              <button
                type="submit"
                disabled={changePasswordMutation.isPending}
                className="w-full px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
              >
                {changePasswordMutation.isPending ? 'Updating...' : 'Update Password'}
              </button>
            </form>
          </section>

          <section className="rounded-xl border bg-card p-6 xl:col-span-2">
            <h2 className="text-xl font-semibold mb-4">Supervisory Organization</h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="rounded border p-4 bg-muted/10">
                <p className="text-sm font-medium mb-1">Reports To</p>
                {profile.manager_name ? (
                  <p className="text-sm text-foreground">{profile.manager_name}</p>
                ) : (
                  <p className="text-sm text-muted-foreground">No supervisor assigned</p>
                )}
              </div>

              <div className="rounded border p-4 bg-muted/10">
                <p className="text-sm font-medium mb-2">Direct Reports</p>
                {profile.direct_reports.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No direct reports</p>
                ) : (
                  <ul className="space-y-1">
                    {profile.direct_reports.map((user) => (
                      <li key={user.id} className="text-sm text-foreground">{user.full_name}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="rounded border p-4 bg-muted/10 mt-4">
              <p className="text-sm font-medium mb-2">Supervisor Chain</p>
              {profile.supervisor_chain.length === 0 ? (
                <p className="text-sm text-muted-foreground">Top of organization (no supervisors above)</p>
              ) : (
                <ol className="space-y-1 list-decimal list-inside">
                  {profile.supervisor_chain.map((user) => (
                    <li key={user.id} className="text-sm text-foreground">
                      {user.full_name}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
