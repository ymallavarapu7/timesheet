import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Loading, Error, EmptyState, Modal, TimeEntryRow, DateRangePickerCalendar, SearchInput } from '@/components';
import { useAuth, useTimeEntries, useCreateTimeEntry, useParseNaturalTimeEntry, useSubmitTimeEntries, useProjects, useTasks, useUpdateTimeEntry, useNotifications, useWeeklySubmitStatus, useCreateTask, useMarkNotificationRead } from '@/hooks';
import { timeentriesAPI } from '@/api/endpoints';
import { Project, Task, TimeEntry, TimeEntryStatus } from '@/types';
import { addDays, endOfWeek, format, parseISO, startOfWeek, startOfYear, subDays } from 'date-fns';
import { ArrowDown, ArrowUp, Search, Sparkles, X } from 'lucide-react';

type EntryFormData = {
  project_id: number;
  task_id: number;
  entry_date: string;
  hours: number;
  description: string;
  is_billable: boolean;
  edit_reason?: string;
  history_summary?: string;
};

type GridRow = {
  id: number;
  projectId: number;
  taskId: number;
  hours: Record<string, string>;
  description: string;
  isBillable: boolean;
};

const TIME_OFF_PREFIX_REGEX = /^\[(SICK_DAY|PTO|HALF_DAY|HOURLY_PERMISSION|OTHER_LEAVE)\]/;
const WEEK_DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MAX_HOURS_PER_DAY = 24;

export const MyTimePage: React.FC = () => {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const deepLinkEntryId = Number(searchParams.get('entryId') || 0) || null;
  const deepLinkDate = searchParams.get('date') || '';
  const deepLinkMode = searchParams.get('mode') || '';

  const [editingId, setEditingId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<'ALL' | TimeEntryStatus>('ALL');
  const [pendingNotificationTarget, setPendingNotificationTarget] = useState<TimeEntryStatus | null>(null);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'entry_date' | 'created_at' | 'hours' | 'status'>('entry_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [startDate, setStartDate] = useState(deepLinkDate || '');
  const [endDate, setEndDate] = useState(deepLinkDate || '');
  const [weekAnchorDate, setWeekAnchorDate] = useState<Date>(new Date());
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState('');
  const [gridProjectId, setGridProjectId] = useState<number>(0);
  const [gridTaskId, setGridTaskId] = useState<number>(0);
  const [gridDescription, setGridDescription] = useState('');
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [newTaskName, setNewTaskName] = useState('');
  const [newTaskCode, setNewTaskCode] = useState('');
  const [newTaskDescription, setNewTaskDescription] = useState('');

  // ── Natural Language entry ──
  const [nlInput, setNlInput] = useState('');
  const [nlResult, setNlResult] = useState<{
    entries: Array<{
      project_id: number | null;
      project_name: string;
      task_id: number | null;
      task_name: string;
      client_name: string;
      client_id: number | null;
      entry_date: string;
      hours: number | null;
      description: string;
      is_billable: boolean;
      error: string | null;
      alternatives: Array<{ project_id: number; project_name: string; task_id: number; task_name: string }>;
    }>;
    error?: string;
  } | null>(null);
  const parseMutation = useParseNaturalTimeEntry();

  const queryParams = useMemo(
    () => ({
      status: statusFilter === 'ALL' ? undefined : statusFilter,
      search: search.trim() || undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      limit: 500,
    }),
    [statusFilter, search, sortBy, sortOrder, startDate, endDate]
  );

  const { data: entries, isLoading, error } = useTimeEntries(queryParams);
  const { data: projects } = useProjects({ active_only: true });

  const searchSuggestions = useMemo(() => {
    const set = new Set<string>();
    (projects ?? []).forEach((p: Project) => set.add(p.name));
    (entries ?? []).forEach((e: TimeEntry) => { if (e.description) set.add(e.description); });
    return Array.from(set).filter(Boolean).sort();
  }, [projects, entries]);
  const { data: allTasks } = useTasks({ active_only: true, limit: 1000 });
  const { data: notifications } = useNotifications();
  const { data: weeklySubmitStatus } = useWeeklySubmitStatus();
  const createMutation = useCreateTimeEntry();
  const createTaskMutation = useCreateTask();
  const submitMutation = useSubmitTimeEntries();
  const updateMutation = useUpdateTimeEntry(editingId || 0);
  const markNotificationReadMutation = useMarkNotificationRead();

  const [gridRows, setGridRows] = useState<GridRow[]>([
    { id: 1, projectId: 0, taskId: 0, hours: {}, description: '', isBillable: true },
  ]);

  const [editFormData, setEditFormData] = useState<EntryFormData | null>(null);
  const historySectionRef = useRef<HTMLDivElement | null>(null);
  const projectsSectionRef = useRef<HTMLElement | null>(null);
  const { data: editTasks } = useTasks({ project_id: editFormData?.project_id || 0, active_only: true, limit: 500 });

  useEffect(() => {
    if (!deepLinkEntryId || !entries || entries.length === 0) return;
    const target = document.getElementById(`time-entry-${deepLinkEntryId}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [deepLinkEntryId, entries]);

  useEffect(() => {
    if (!deepLinkEntryId || deepLinkMode !== 'edit' || !entries || entries.length === 0) return;
    if (editingId === deepLinkEntryId) return;

    const targetEntry = entries.find((entry: TimeEntry) => entry.id === deepLinkEntryId);
    if (!targetEntry || targetEntry.status !== 'DRAFT') return;

    setEditingId(targetEntry.id);
    setEditFormData({
      project_id: targetEntry.project_id,
      task_id: targetEntry.task_id || 0,
      entry_date: targetEntry.entry_date,
      hours: typeof targetEntry.hours === 'string' ? parseFloat(targetEntry.hours) : targetEntry.hours,
      description: targetEntry.description,
      is_billable: targetEntry.is_billable ?? true,
      edit_reason: '',
      history_summary: '',
    });
  }, [deepLinkEntryId, deepLinkMode, entries, editingId]);

  useEffect(() => {
    if (!isPickerOpen) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsPickerOpen(false);
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isPickerOpen]);

  const regularEntries = entries?.filter((entry: TimeEntry) => !TIME_OFF_PREFIX_REGEX.test(entry.description)) || [];
  const draftEntries = regularEntries.filter((e: TimeEntry) => e.status === 'DRAFT');
  const historyEntries = regularEntries.filter((e: TimeEntry) => e.status !== 'DRAFT');
  const hasHistoryRange = Boolean((startDate && endDate) || statusFilter !== 'ALL' || search.trim());
  const myTimeNotifications = (notifications?.items ?? []).filter(
    (item) => item.route === '/my-time' && item.id !== 'draft-time-entries'
  );

  useEffect(() => {
    if (!pendingNotificationTarget || statusFilter !== pendingNotificationTarget) return;

    if (pendingNotificationTarget === 'DRAFT') {
      projectsSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setPendingNotificationTarget(null);
      return;
    }

    if (pendingNotificationTarget === 'REJECTED') {
      historySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setPendingNotificationTarget(null);
    }
  }, [pendingNotificationTarget, statusFilter, historyEntries.length]);

  const weekStart = startOfWeek(weekAnchorDate, { weekStartsOn: 0 });
  const weekEnd = endOfWeek(weekAnchorDate, { weekStartsOn: 0 });
  const weekDates = Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
  const weekStartKey = format(weekStart, 'yyyy-MM-dd');
  const weekEndKey = format(weekEnd, 'yyyy-MM-dd');

  const weeklyGridQueryParams = useMemo(
    () => ({
      sort_by: 'entry_date',
      sort_order: 'asc',
      start_date: weekStartKey,
      end_date: weekEndKey,
      limit: 1000,
    }),
    [weekStartKey, weekEndKey]
  );

  const { data: weeklyGridEntries } = useTimeEntries(weeklyGridQueryParams);
  const regularWeeklyGridEntries = useMemo(
    () => (weeklyGridEntries ?? []).filter((entry: TimeEntry) => !TIME_OFF_PREFIX_REGEX.test(entry.description)),
    [weeklyGridEntries]
  );

  useEffect(() => {
    const entryRows = new Map<string, GridRow>();
    let nextId = 1;

    (regularWeeklyGridEntries ?? []).forEach((entry: TimeEntry) => {
      const dateKey = entry.entry_date;
      const rowKey = `${entry.project_id}|${entry.task_id || 0}|${entry.is_billable ? '1' : '0'}`;
      const existing = entryRows.get(rowKey);
      const entryHours = typeof entry.hours === 'string' ? parseFloat(entry.hours) : entry.hours;

      if (!existing) {
        entryRows.set(rowKey, {
          id: nextId++,
          projectId: entry.project_id,
          taskId: entry.task_id || 0,
          hours: {
            [dateKey]: (entryHours || 0).toString(),
          },
          description: '',
          isBillable: entry.is_billable ?? true,
        });
        return;
      }

      const existingHours = parseFloat(existing.hours[dateKey] || '0') || 0;
      existing.hours[dateKey] = (existingHours + (entryHours || 0)).toString();
    });

    const hydratedRows = Array.from(entryRows.values());
    if (hydratedRows.length > 0) {
      setGridRows(hydratedRows);
      return;
    }

    setGridRows([{ id: 1, projectId: 0, taskId: 0, hours: {}, description: '', isBillable: true }]);
  }, [weekStartKey, weekEndKey, regularWeeklyGridEntries]);


  const selectableProjects = useMemo(() => {
    const baseProjects = projects ?? [];
    if (!user || user.role === 'ADMIN' || user.role === 'PLATFORM_ADMIN') {
      return baseProjects;
    }

    const assignedProjectIds = user.project_ids ?? [];
    if (assignedProjectIds.length === 0) {
      return baseProjects;
    }

    const assignedSet = new Set(assignedProjectIds);
    return baseProjects.filter((project: Project) => assignedSet.has(project.id));
  }, [projects, user]);

  const mergedTasks = useMemo(() => {
    const byId = new Map<number, Task>();
    (allTasks ?? []).forEach((task: Task) => {
      byId.set(task.id, task);
    });
    regularWeeklyGridEntries.forEach((entry: TimeEntry) => {
      if (entry.task && !byId.has(entry.task.id)) {
        byId.set(entry.task.id, entry.task as Task);
      }
    });
    return Array.from(byId.values());
  }, [allTasks, regularWeeklyGridEntries]);

  const tasksByProject = useMemo(() => {
    const selectableProjectIds = new Set(selectableProjects.map((project: Project) => project.id));
    const bucket = new Map<number, Task[]>();
    mergedTasks.forEach((task: Task) => {
      if (!selectableProjectIds.has(task.project_id)) return;
      const existing = bucket.get(task.project_id) ?? [];
      existing.push(task);
      bucket.set(task.project_id, existing);
    });
    return bucket;
  }, [mergedTasks, selectableProjects]);

  const projectList = useMemo(() => {
    const searchValue = projectSearch.trim().toLowerCase();
    return selectableProjects.filter((project: Project) => {
      if (!searchValue) return true;
      return project.name.toLowerCase().includes(searchValue);
    });
  }, [selectableProjects, projectSearch]);

  const selectedProject = selectableProjects.find((project: Project) => project.id === gridProjectId);
  const selectedProjectTasks = selectedProject ? tasksByProject.get(selectedProject.id) ?? [] : [];
  const canCreateTasks = user?.role === 'ADMIN' || user?.role === 'PLATFORM_ADMIN';

  if (isLoading && !entries) return <Loading />;
  if (error) return <Error message="Failed to load time entries" />;

  const getWeekDateKey = (day: Date) => format(day, 'yyyy-MM-dd');

  const handleSelectProject = (projectId: number) => {
    setGridProjectId(projectId);
    setGridTaskId(0);
    setShowTaskForm(false);
  };

  const closePicker = () => {
    setIsPickerOpen(false);
    setShowTaskForm(false);
  };

  const handleSelectTask = (projectId: number, taskId: number) => {
    setGridProjectId(projectId);
    setGridTaskId(taskId);
    closePicker();
  };

  const handleUseProjectOnly = (projectId: number) => {
    setGridProjectId(projectId);
    setGridTaskId(0);
    closePicker();
  };

  const handleCreateTask = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!gridProjectId || !newTaskName.trim()) {
      return;
    }

    try {
      const task = await createTaskMutation.mutateAsync({
        project_id: gridProjectId,
        name: newTaskName.trim(),
        code: newTaskCode.trim() || undefined,
        description: newTaskDescription.trim() || undefined,
        is_active: true,
      });

      setGridTaskId(task.id);
      setNewTaskName('');
      setNewTaskCode('');
      setNewTaskDescription('');
      closePicker();
    } catch (err) {
      console.error('Error creating task:', err);
      alert('Unable to create task right now.');
    }
  };


  const handleGridRowChange = (rowId: number, field: 'projectId' | 'taskId' | 'description', value: number | string) => {
    setGridRows((current) =>
      current.map((row) => {
        if (row.id !== rowId) return row;
        if (field === 'projectId') {
          return {
            ...row,
            projectId: value as number,
            taskId: 0,
          };
        }
        return {
          ...row,
          [field]: value,
        };
      })
    );
  };

  const handleGridRowHourChange = (rowId: number, dateKey: string, value: string) => {
    setGridRows((current) =>
      current.map((row) => {
        if (row.id !== rowId) return row;
        return {
          ...row,
          hours: {
            ...row.hours,
            [dateKey]: value,
          },
        };
      })
    );
  };

  // ── NL Parse handler ──
  const handleNlParse = async () => {
    if (!nlInput.trim()) return;
    setNlResult(null);
    try {
      const result = await parseMutation.mutateAsync(nlInput.trim());
      if (result.error) {
        setNlResult({ entries: [], error: result.error });
        return;
      }
      setNlResult(result);
    } catch {
      setNlResult({ entries: [], error: 'Failed to parse. Please try again.' });
    }
  };

  const handleNlApplyEntry = (entry: NonNullable<typeof nlResult>['entries'][number]) => {
    if (entry.error || !entry.project_id || !entry.hours) return;

    // Find the date key for the grid
    const dateKey = entry.entry_date;

    // Navigate the grid to the week containing this entry date
    const entryDate = parseISO(dateKey);
    const entryWeekStart = startOfWeek(entryDate, { weekStartsOn: 0 });
    const currentWeekStart = startOfWeek(weekAnchorDate, { weekStartsOn: 0 });
    if (entryWeekStart.getTime() !== currentWeekStart.getTime()) {
      setWeekAnchorDate(entryDate);
    }

    // Check if this project/task already has a row in the grid
    const existingRowIdx = gridRows.findIndex(
      (r) => r.projectId === entry.project_id && r.taskId === (entry.task_id || 0),
    );

    if (existingRowIdx >= 0) {
      // Update existing row's hours for this date
      setGridRows((rows) =>
        rows.map((r, idx) =>
          idx === existingRowIdx
            ? { ...r, hours: { ...r.hours, [dateKey]: String(entry.hours) }, description: entry.description || r.description }
            : r,
        ),
      );
    } else {
      // Add a new row
      const newId = Math.max(...gridRows.map((r) => r.id), 0) + 1;
      setGridRows((rows) => [
        ...rows,
        {
          id: newId,
          projectId: entry.project_id!,
          taskId: entry.task_id || 0,
          hours: { [dateKey]: String(entry.hours) },
          description: entry.description || '',
          isBillable: entry.is_billable,
        },
      ]);
    }
  };

  const handleNlApplyAll = () => {
    if (!nlResult) return;
    const validEntries = nlResult.entries.filter((e) => !e.error && e.project_id && e.hours);
    for (const entry of validEntries) {
      handleNlApplyEntry(entry);
    }
    setNlInput('');
    setNlResult(null);
  };

  const handleAddGridRow = () => {
    const newId = Math.max(...gridRows.map((r) => r.id), 0) + 1;
    setGridRows((current) => [
      ...current,
      { id: newId, projectId: 0, taskId: 0, hours: {}, description: '', isBillable: true },
    ]);
  };

  const handleGridRowBillableToggle = (rowId: number) => {
    setGridRows((current) =>
      current.map((row) => (row.id !== rowId ? row : { ...row, isBillable: !row.isBillable }))
    );
  };

  const handleRemoveGridRow = (rowId: number) => {
    setGridRows((current) => {
      if (current.length <= 1) return current;
      return current.filter((row) => row.id !== rowId);
    });
  };

  const handleSaveGridRows = async () => {
    const existingHoursByKey = new Map<string, number>();
    const draftEntriesByKey = new Map<string, TimeEntry[]>();
    regularWeeklyGridEntries.forEach((entry: TimeEntry) => {
      const entryKey = `${entry.project_id}|${entry.task_id || 0}|${entry.entry_date}|${entry.is_billable ? '1' : '0'}`;
      const entryHours = typeof entry.hours === 'string' ? parseFloat(entry.hours) : entry.hours;
      const previous = existingHoursByKey.get(entryKey) ?? 0;
      existingHoursByKey.set(entryKey, previous + (entryHours || 0));

      if (entry.status === 'DRAFT') {
        const draftEntries = draftEntriesByKey.get(entryKey) ?? [];
        draftEntries.push(entry);
        draftEntriesByKey.set(entryKey, draftEntries);
      }
    });

    const allCreates: { row: GridRow; dateKey: string; dayHours: number }[] = [];
    const updateOps: Promise<unknown>[] = [];
    const deleteOps: Promise<unknown>[] = [];
    let hasAnyEnteredHours = false;
    let hasImmutableReductionAttempt = false;
    for (const row of gridRows) {
      if (!row.projectId) continue;
      for (const day of weekDates) {
        const dateKey = getWeekDateKey(day);
        const dayHours = parseFloat(row.hours[dateKey] || '0');
        if (dayHours > 0) {
          hasAnyEnteredHours = true;
        }
        const entryKey = `${row.projectId}|${row.taskId || 0}|${dateKey}|${row.isBillable ? '1' : '0'}`;
        if (dayHours <= 0) continue;

        const existingHours = existingHoursByKey.get(entryKey) ?? 0;
        const deltaHours = dayHours - existingHours;

        if (deltaHours > 0) {
          allCreates.push({ row, dateKey, dayHours: deltaHours });
          continue;
        }

        if (deltaHours < 0) {
          const draftEntries = draftEntriesByKey.get(entryKey) ?? [];
          const draftTotal = draftEntries.reduce((sum, entry) => {
            const value = typeof entry.hours === 'string' ? parseFloat(entry.hours) : entry.hours;
            return sum + (value || 0);
          }, 0);
          const immutableTotal = existingHours - draftTotal;

          if (dayHours < immutableTotal) {
            hasImmutableReductionAttempt = true;
            continue;
          }

          let reductionRemaining = existingHours - dayHours;
          const sortedDrafts = [...draftEntries].sort((a, b) => b.id - a.id);
          for (const draftEntry of sortedDrafts) {
            if (reductionRemaining <= 0) break;
            const entryHours = typeof draftEntry.hours === 'string' ? parseFloat(draftEntry.hours) : draftEntry.hours;
            const currentHours = entryHours || 0;

            if (currentHours <= reductionRemaining + 0.0001) {
              deleteOps.push(timeentriesAPI.delete(draftEntry.id));
              reductionRemaining -= currentHours;
              continue;
            }

            const nextHours = Number((currentHours - reductionRemaining).toFixed(2));
            updateOps.push(
              timeentriesAPI.update(draftEntry.id, {
                hours: nextHours,
                edit_reason: 'Adjusted from weekly grid',
                history_summary: 'Updated hours via weekly time entry section',
              })
            );
            reductionRemaining = 0;
          }
        }
      }
    }

    if (allCreates.length === 0 && updateOps.length === 0 && deleteOps.length === 0) {
      if (!hasAnyEnteredHours) {
        alert('Enter hours for at least one day before saving.');
        return;
      }

      if (hasImmutableReductionAttempt) {
        alert('Some entered values are lower than already submitted/approved hours. Only draft hours can be reduced from this section.');
        return;
      }

      alert('No new changes to save.');
      return;
    }

    const rowsMissingProject = gridRows.some((r) => {
      const hasAnyHours = weekDates.some((d) => parseFloat(r.hours[getWeekDateKey(d)] || '0') > 0);
      return hasAnyHours && !r.projectId;
    });
    if (rowsMissingProject) {
      alert('Please select a project for every row that has hours entered.');
      return;
    }

    try {
      const mutationResults = await Promise.allSettled([
        ...deleteOps,
        ...updateOps,
        ...allCreates.map(({ row, dateKey, dayHours }) =>
          createMutation.mutateAsync({
            project_id: row.projectId,
            task_id: row.taskId || null,
            entry_date: dateKey,
            hours: dayHours,
            description: row.description.trim() || gridDescription.trim() || 'Worked on project tasks',
            is_billable: row.isBillable,
          })
        ),
      ]);

      const failures = mutationResults.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
      const successes = mutationResults.length - failures.length;

      if (failures.length === 0) {
        setGridRows([{ id: 1, projectId: 0, taskId: 0, hours: {}, description: '', isBillable: true }]);
        setGridDescription('');
        await queryClient.invalidateQueries({ queryKey: ['timeentries'] });
        await queryClient.invalidateQueries({ queryKey: ['notifications'] });
        return;
      }

      const firstError = failures[0].reason;
      const detail =
        typeof firstError === 'object' &&
        firstError !== null &&
        'response' in firstError &&
        typeof (firstError as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (firstError as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'Failed to create one or more entries.';

      if (successes > 0) {
        alert(`${successes} entr${successes === 1 ? 'y was' : 'ies were'} saved, but ${failures.length} failed. ${detail}`);
        await queryClient.invalidateQueries({ queryKey: ['timeentries'] });
        await queryClient.invalidateQueries({ queryKey: ['notifications'] });
      } else {
        alert(detail);
      }
    } catch (err) {
      console.error('Failed to save grid entries', err);
      const detail =
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'Failed to create one or more entries.';
      alert(detail);
    }
  };

  const handleEditEntry = (entry: TimeEntry) => {
    setEditingId(entry.id);
    setEditFormData({
      project_id: entry.project_id,
      task_id: entry.task_id || 0,
      entry_date: entry.entry_date,
      hours: typeof entry.hours === 'string' ? parseFloat(entry.hours) : entry.hours,
      description: entry.description,
      is_billable: entry.is_billable ?? true,
      edit_reason: '',
      history_summary: '',
    });
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingId || !editFormData) return;

    if (!editFormData.edit_reason?.trim()) {
      alert('Edit reason is required before saving.');
      return;
    }
    if (!editFormData.history_summary?.trim()) {
      alert('History summary is required before saving.');
      return;
    }

    try {
      await updateMutation.mutateAsync({
        project_id: editFormData.project_id,
        task_id: editFormData.task_id || null,
        entry_date: editFormData.entry_date,
        hours: editFormData.hours,
        description: editFormData.description,
        is_billable: editFormData.is_billable,
        edit_reason: editFormData.edit_reason,
        history_summary: editFormData.history_summary,
      });
      setEditingId(null);
      setEditFormData(null);
    } catch (err) {
      console.error('Error updating entry:', err);
    }
  };


  const handleSubmitEntry = async (ids: number[]) => {
    try {
      await submitMutation.mutateAsync(ids);
    } catch (err) {
      const detail =
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      alert(detail ?? 'Unable to submit entries.');
    }
  };

  const handleSubmitWeek = async () => {
    const dueDate = new Date(weeklySubmitStatus?.due_date ?? new Date());
    const candidateIds = draftEntries
      .filter((entry: TimeEntry) => new Date(entry.entry_date) <= dueDate)
      .map((entry: TimeEntry) => entry.id);

    if (candidateIds.length === 0) {
      alert('No draft entries available for this submission window.');
      return;
    }

    await handleSubmitEntry(candidateIds);
  };

  const handleNotificationClick = (notificationId: string) => {
    markNotificationReadMutation.mutate(notificationId);

    if (notificationId === 'rejected-time-entries') {
      const today = new Date();
      setStartDate(format(startOfYear(today), 'yyyy-MM-dd'));
      setEndDate(format(today, 'yyyy-MM-dd'));
      setPendingNotificationTarget('REJECTED');
      setStatusFilter('REJECTED');
      return;
    }

    if (notificationId === 'missing-previous-day-entry') {
      const yesterday = subDays(new Date(), 1);
      setWeekAnchorDate(yesterday);
      setStatusFilter('DRAFT');
      projectsSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    if (notificationId === 'weekly-timesheet-reminder') {
      setWeekAnchorDate(new Date());
      setStatusFilter('DRAFT');
      projectsSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    setPendingNotificationTarget(null);
    setStatusFilter('ALL');
  };

  return (
    <div>
      <div>
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-3xl font-bold">My Time Entries</h1>
        </div>

        {myTimeNotifications.length > 0 && (
          <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-4">
            <h2 className="text-sm font-semibold text-amber-900">Action needed in My Time</h2>
            <div className="mt-2 space-y-2">
              {myTimeNotifications.slice(0, 3).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => handleNotificationClick(item.id)}
                  className="w-full flex items-start justify-between gap-3 rounded-lg border border-amber-100 bg-white/70 px-3 py-2 text-left transition hover:bg-white"
                >
                  <div>
                    <p className="text-sm font-medium text-amber-950">{item.title}</p>
                    <p className="text-xs text-amber-800">{item.message}</p>
                  </div>
                  <span className="rounded-full bg-amber-600 px-2 py-0.5 text-[11px] font-semibold text-white">
                    {item.count > 99 ? '99+' : item.count}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="mb-4 rounded-lg border bg-card p-3 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <p className="text-sm text-muted-foreground">
            {weeklySubmitStatus?.reason ?? `Weekly entry submission due on ${weeklySubmitStatus?.due_date ?? '-'}`}
          </p>
          <button
            onClick={handleSubmitWeek}
            disabled={!weeklySubmitStatus?.can_submit || submitMutation.isPending}
            className="px-3 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
          >
            {submitMutation.isPending ? 'Submitting...' : 'Submit Weekly Entries'}
          </button>
        </div>

        {/* ── Natural Language Input ── */}
        <section className="mb-6 rounded-lg border bg-card">
          <div className="border-b px-4 py-3 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-muted-foreground">Quick Entry — Describe your work</h2>
          </div>
          <div className="p-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={nlInput}
                onChange={(e) => setNlInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleNlParse(); } }}
                placeholder='e.g. "Worked on API integration in Project Alpha from 9 AM to 3 PM yesterday"'
                className="field-input flex-1"
                disabled={parseMutation.isPending}
              />
              <button
                type="button"
                onClick={handleNlParse}
                disabled={parseMutation.isPending || !nlInput.trim()}
                className="action-button whitespace-nowrap"
              >
                {parseMutation.isPending ? 'Processing...' : 'Go'}
              </button>
            </div>

            {/* Error message */}
            {nlResult?.error && (
              <div className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {nlResult.error}
              </div>
            )}

            {/* Parsed entries */}
            {nlResult && nlResult.entries.length > 0 && (
              <div className="mt-3 space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Parsed entries — review and apply to your grid:</p>
                {nlResult.entries.map((entry, idx) => (
                  <div
                    key={idx}
                    className={`rounded-lg border p-3 text-sm ${entry.error ? 'border-destructive/30 bg-destructive/5' : 'border-primary/20 bg-primary/5'}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 space-y-1">
                        {entry.error ? (
                          <p className="font-medium text-destructive">{entry.error}</p>
                        ) : (
                          <>
                            <p className="font-medium text-foreground">
                              {entry.client_name} → {entry.project_name} → {entry.task_name}
                            </p>
                            <p className="text-muted-foreground">
                              {entry.entry_date} · {entry.hours}h · {entry.is_billable ? 'Billable' : 'Non-billable'}
                            </p>
                            {entry.description && (
                              <p className="text-muted-foreground italic">"{entry.description}"</p>
                            )}
                          </>
                        )}
                        {entry.alternatives && entry.alternatives.length > 0 && (
                          <div className="mt-1">
                            <p className="text-xs text-muted-foreground">Did you mean:</p>
                            {entry.alternatives.map((alt, ai) => (
                              <span key={ai} className="mr-2 text-xs text-primary">{alt.project_name} → {alt.task_name}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      {!entry.error && entry.project_id && entry.hours && (
                        <button
                          type="button"
                          onClick={() => handleNlApplyEntry(entry)}
                          className="action-button-secondary text-xs px-2 py-1 h-auto"
                        >
                          Apply
                        </button>
                      )}
                    </div>
                  </div>
                ))}
                {nlResult.entries.some((e) => !e.error && e.project_id && e.hours) && (
                  <div className="flex gap-2">
                    <button type="button" onClick={handleNlApplyAll} className="action-button text-xs px-3 py-1.5 h-auto">
                      Apply All Valid Entries
                    </button>
                    <button type="button" onClick={() => { setNlResult(null); setNlInput(''); }} className="action-button-secondary text-xs px-3 py-1.5 h-auto">
                      Dismiss
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        <section ref={projectsSectionRef} className="mb-6 rounded-lg border bg-card">
          <div className="border-b px-4 py-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground">Projects</h2>
            <div className="flex items-center gap-2 text-sm">
              <button
                className="h-7 w-7 rounded border hover:bg-muted"
                onClick={() => setWeekAnchorDate((current) => addDays(current, -7))}
                aria-label="Previous week"
              >
                {'<'}
              </button>
              <span>{format(weekStart, 'MMM d')} - {format(weekEnd, 'MMM d')}</span>
              <button
                className="h-7 w-7 rounded border hover:bg-muted"
                onClick={() => setWeekAnchorDate((current) => addDays(current, 7))}
                aria-label="Next week"
              >
                {'>'}
              </button>
            </div>
          </div>

          <div className="p-4 overflow-x-auto overflow-y-visible pb-6">
            <div className="w-full">
              <div className="grid grid-cols-[minmax(280px,2.2fr)_repeat(7,minmax(64px,0.8fr))_minmax(70px,0.7fr)_minmax(80px,0.9fr)] items-center gap-2 text-xs text-muted-foreground mb-3 px-2">
                <div>Project / Task</div>
                {weekDates.map((day, index) => (
                  <div key={getWeekDateKey(day)} className="text-center">{WEEK_DAYS[index]}, {format(day, 'MMM d')}</div>
                ))}
                <div className="text-center">Total</div>
                <div className="text-right mr-1">Action</div>
              </div>

              <div className="space-y-2">
                {gridRows.map((row) => {
                  const rowTasks = row.projectId ? tasksByProject.get(row.projectId) ?? [] : [];

                  return (
                    <div key={row.id} className="space-y-1">
                      <div className="grid grid-cols-[minmax(280px,2.2fr)_repeat(7,minmax(64px,0.8fr))_minmax(70px,0.7fr)_minmax(80px,0.9fr)] items-center gap-2 border rounded-md p-2">
                        <div className="flex flex-col gap-2">
                          <select
                            value={row.projectId}
                            onChange={(e) => handleGridRowChange(row.id, 'projectId', parseInt(e.target.value))}
                            className="w-full rounded border px-2 py-1.5 text-sm"
                          >
                            <option value={0}>Select a project</option>
                            {selectableProjects.map((p: Project) => (
                              <option key={p.id} value={p.id}>
                                {p.name}
                              </option>
                            ))}
                          </select>
                          <select
                            value={row.taskId}
                            onChange={(e) => handleGridRowChange(row.id, 'taskId', parseInt(e.target.value))}
                            className="w-full rounded border px-2 py-1.5 text-sm"
                            disabled={row.projectId === 0}
                          >
                            <option value={0}>No task</option>
                            {rowTasks.map((t: Task) => (
                              <option key={t.id} value={t.id}>
                                {t.name}
                              </option>
                            ))}
                          </select>
                          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={row.isBillable}
                              onChange={() => handleGridRowBillableToggle(row.id)}
                              className="rounded"
                            />
                            <span className={row.isBillable ? 'text-green-700 font-medium' : 'text-muted-foreground'}>
                              {row.isBillable ? 'Billable' : 'Non-billable'}
                            </span>
                          </label>
                        </div>

                        {weekDates.map((day) => {
                          const dateKey = getWeekDateKey(day);
                          return (
                            <input
                              key={dateKey}
                              type="number"
                              min="0"
                              step="0.25"
                              value={row.hours[dateKey] || ''}
                              onChange={(event) => handleGridRowHourChange(row.id, dateKey, event.target.value)}
                              className="w-full rounded border px-2 py-1.5 text-center"
                              placeholder="0"
                            />
                          );
                        })}

                        <div className="text-center text-muted-foreground text-xs"></div>

                        <div className="flex justify-end gap-1">
                          {gridRows.length > 1 && (
                            <button
                              type="button"
                              onClick={() => handleRemoveGridRow(row.id)}
                              className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="grid grid-cols-[minmax(280px,2.2fr)_repeat(7,minmax(64px,0.8fr))_minmax(70px,0.7fr)_minmax(80px,0.9fr)] items-center gap-2 px-2 text-xs text-muted-foreground">
                        <div></div>
                        {weekDates.map((day) => {
                          const dateKey = getWeekDateKey(day);
                          const dayValue = parseFloat(row.hours[dateKey] || '0') || 0;
                          return (
                            <div key={dateKey} className="text-center">
                              {dayValue > 0 ? dayValue.toFixed(2) : ''}
                            </div>
                          );
                        })}
                        <div></div>
                        <div></div>
                      </div>
                    </div>
                  );
                })}

                <div className="grid grid-cols-[minmax(280px,2.2fr)_repeat(7,minmax(64px,0.8fr))_minmax(70px,0.7fr)_minmax(80px,0.9fr)] items-center gap-2 border-t-2 border-primary pt-2 px-2 font-semibold text-sm">
                  <div className="text-right">Daily Totals:</div>
                  {weekDates.map((day) => {
                    const dateKey = getWeekDateKey(day);
                    const dailyTotal = gridRows.reduce(
                      (sum, row) => sum + (parseFloat(row.hours[dateKey] || '0') || 0),
                      0
                    );
                    return (
                      <div key={dateKey} className="text-center">
                        {dailyTotal > 0 ? dailyTotal.toFixed(2) : '-'}
                      </div>
                    );
                  })}
                  <div className="text-center">
                    {gridRows.reduce(
                      (sum, row) => sum + weekDates.reduce((daySum, day) => daySum + (parseFloat(row.hours[getWeekDateKey(day)] || '0') || 0), 0),
                      0
                    ).toFixed(2)}
                  </div>
                  <div></div>
                </div>
              </div>

              <div className="mt-4 flex flex-col gap-3">
                <button
                  type="button"
                  onClick={handleAddGridRow}
                  className="px-3 py-2 border rounded hover:bg-muted text-sm w-full"
                >
                  Add another project/task
                </button>

                <textarea
                  value={gridDescription}
                  onChange={(event) => setGridDescription(event.target.value)}
                  placeholder="Description for created entries"
                  className="w-full border rounded px-3 py-2 text-sm"
                  rows={2}
                />

                <button
                  onClick={handleSaveGridRows}
                  disabled={createMutation.isPending}
                  className="w-full px-3 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Saving...' : 'Save Week'}
                </button>
              </div>

            </div>
          </div>
        </section>

        <section aria-label="Time entry history" className="mb-2">
          <h2 className="text-xl font-bold mb-3">Time Entry History</h2>
          <p className="text-sm text-muted-foreground mb-4">Use the filters and date range below to view your history entries.</p>
        </section>

        <div className="bg-card border rounded-lg p-4 mb-4 grid grid-cols-1 md:grid-cols-3 gap-3">
          <SearchInput
            value={search}
            onChange={setSearch}
            suggestions={searchSuggestions}
            placeholder="Search description/project"
            className="px-3 py-2 border rounded w-full"
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as 'ALL' | TimeEntryStatus)}
            className="px-3 py-2 border rounded"
          >
            <option value="ALL">All Status</option>
            <option value="SUBMITTED">Submitted</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
          </select>
          <DateRangePickerCalendar
            startDate={startDate}
            endDate={endDate}
            onStartDateChange={setStartDate}
            onEndDateChange={setEndDate}
          />
        </div>

        <div className="mb-6 flex items-center justify-end gap-2">
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as 'entry_date' | 'created_at' | 'hours' | 'status')}
            className="h-9 w-40 rounded border bg-card px-2 text-xs"
          >
            <option value="entry_date">Entry Date</option>
            <option value="created_at">Created</option>
            <option value="hours">Hours</option>
            <option value="status">Status</option>
          </select>
          <button
            onClick={() => setSortOrder((value) => (value === 'asc' ? 'desc' : 'asc'))}
            className="h-9 w-9 rounded border hover:bg-muted flex items-center justify-center"
            aria-label={sortOrder === 'asc' ? 'Sort ascending' : 'Sort descending'}
            title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
          >
            {sortOrder === 'asc' ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
          </button>
        </div>



        {hasHistoryRange && historyEntries.length > 0 && (
          <div className="mb-8" ref={historySectionRef}>
            <h2 className="text-xl font-bold mb-4">History Entries</h2>
            <div className="space-y-4">
              {historyEntries.map((entry: TimeEntry) => (
                <TimeEntryRow
                  key={entry.id}
                  entry={entry}
                  showActions={entry.status === 'REJECTED'}
                  onEdit={entry.status === 'REJECTED' ? handleEditEntry : undefined}
                  highlighted={entry.id === deepLinkEntryId}
                  rowId={`time-entry-${entry.id}`}
                />
              ))}
            </div>
          </div>
        )}

        {!hasHistoryRange && (
          <EmptyState message="Select a date range, status filter, or search to view history entries." />
        )}

        {!isLoading && regularEntries.length === 0 && (
          <EmptyState message="No timesheet entries. Create one to get started!" />
        )}
      </div>

      <Modal
        open={editingId !== null && editFormData !== null}
        onClose={() => { setEditingId(null); setEditFormData(null); }}
        title="Correct & Resubmit Entry"
        description="Edit the entry below. It will return to Draft so you can resubmit."
      >
        {editFormData && (
          <form onSubmit={handleSaveEdit} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-sm font-medium">Date</label>
                <input
                  type="date"
                  className="field-input"
                  value={editFormData.entry_date}
                  onChange={(e) => setEditFormData((f) => f ? { ...f, entry_date: e.target.value } : f)}
                  required
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium">Hours</label>
                <input
                  type="number"
                  step="0.25"
                  min="0.25"
                  max="24"
                  className="field-input"
                  value={editFormData.hours}
                  onChange={(e) => setEditFormData((f) => f ? { ...f, hours: parseFloat(e.target.value) } : f)}
                  required
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Project</label>
              <select
                className="field-input"
                value={editFormData.project_id}
                onChange={(e) => setEditFormData((f) => f ? { ...f, project_id: Number(e.target.value), task_id: 0 } : f)}
                required
              >
                <option value={0}>Select project</option>
                {(projects ?? []).map((p: Project) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Task (optional)</label>
              <select
                className="field-input"
                value={editFormData.task_id}
                onChange={(e) => setEditFormData((f) => f ? { ...f, task_id: Number(e.target.value) } : f)}
              >
                <option value={0}>No task</option>
                {(editTasks ?? []).map((t: Task) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Description</label>
              <textarea
                className="field-textarea"
                rows={3}
                value={editFormData.description}
                onChange={(e) => setEditFormData((f) => f ? { ...f, description: e.target.value } : f)}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Edit Reason <span className="text-red-500">*</span></label>
              <input
                className="field-input"
                value={editFormData.edit_reason ?? ''}
                onChange={(e) => setEditFormData((f) => f ? { ...f, edit_reason: e.target.value } : f)}
                placeholder="Why are you correcting this entry?"
                required
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">History Summary <span className="text-red-500">*</span></label>
              <input
                className="field-input"
                value={editFormData.history_summary ?? ''}
                onChange={(e) => setEditFormData((f) => f ? { ...f, history_summary: e.target.value } : f)}
                placeholder="Brief description of what changed"
                required
              />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button type="button" className="action-button-secondary" onClick={() => { setEditingId(null); setEditFormData(null); }}>
                Cancel
              </button>
              <button type="submit" className="action-button" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? 'Saving...' : 'Save & Return to Draft'}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
};
