import React, { useState } from 'react';
import { PlusCircle, Pencil, Trash2, X } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import { Loading, Error, SearchInput } from '@/components';
import { useClients, useCreateClient, useUpdateClient, useDeleteClient, useProjects, useCreateProject, useUpdateProject, useDeleteProject, useTasks, useCreateTask, useUpdateTask, useDeleteTask } from '@/hooks';
import { Client, Project, Task } from '@/types';

type ClientFormState = {
  name: string;
  quickbooks_customer_id: string;
};

const emptyClientForm = (): ClientFormState => ({
  name: '',
  quickbooks_customer_id: '',
});

type ProjectFormState = {
  name: string;
  client_id: number;
  billable_rate: number;
  quickbooks_project_id: string;
  code: string;
  description: string;
  start_date: string;
  end_date: string;
  estimated_hours: number;
  budget_amount: number;
  currency: string;
  is_active: boolean;
};

const emptyProjectForm = (): ProjectFormState => ({
  name: '',
  client_id: 0,
  billable_rate: 0,
  quickbooks_project_id: '',
  code: '',
  description: '',
  start_date: '',
  end_date: '',
  estimated_hours: 0,
  budget_amount: 0,
  currency: 'USD',
  is_active: true,
});

type TaskFormState = {
  name: string;
  code: string;
  description: string;
  is_active: boolean;
};

const emptyTaskForm = (): TaskFormState => ({
  name: '',
  code: '',
  description: '',
  is_active: true,
});

export const ClientManagementPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const deepLinkedProjectId = React.useMemo(() => {
    const projectId = searchParams.get('projectId');
    const parsed = projectId ? Number(projectId) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  }, [searchParams]);
  const { data: clients, isLoading: clientsLoading, error: clientsError } = useClients();
  const { data: projects, isLoading: projectsLoading, error: projectsError } = useProjects({ limit: 500 });
  const { data: tasks, isLoading: tasksLoading, error: tasksError } = useTasks({ limit: 1000, active_only: false });
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const createTask = useCreateTask();
  const updateTask = useUpdateTask();
  const deleteTask = useDeleteTask();
  const createClient = useCreateClient();
  const updateClient = useUpdateClient();
  const deleteClient = useDeleteClient();
  const [editingClient, setEditingClient] = useState<Client | null>(null);
  const deleteProject = useDeleteProject();

  const [showProjectModal, setShowProjectModal] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [projectForm, setProjectForm] = useState<ProjectFormState>(emptyProjectForm());
  const [projectError, setProjectError] = useState('');
  const [showClientModal, setShowClientModal] = useState(false);
  const [clientForm, setClientForm] = useState<ClientFormState>(emptyClientForm());
  const [clientError, setClientError] = useState('');
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [taskForm, setTaskForm] = useState<TaskFormState>(emptyTaskForm());
  const [taskError, setTaskError] = useState('');
  const [confirmDeleteTaskId, setConfirmDeleteTaskId] = useState<number | null>(null);

  // Navigation state
  const [navigationLevel, setNavigationLevel] = useState<'clients' | 'projects'>('clients');
  const [selectedClientId, setSelectedClientId] = useState<number | null>(() => {
    const clientId = searchParams.get('clientId');
    const parsed = clientId ? Number(clientId) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  });
  
  // Expandable project tasks
  const [expandedProjectId, setExpandedProjectId] = useState<number | null>(null);

  const [clientSearch, setClientSearch] = useState('');
  const [projectSearch, setProjectSearch] = useState('');
  const [projectStatusFilter, setProjectStatusFilter] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>(() => {
    const status = searchParams.get('status');
    if (status === 'ACTIVE' || status === 'INACTIVE') {
      return status;
    }
    return 'ALL';
  });

  React.useEffect(() => {
    const status = searchParams.get('status');
    const clientId = searchParams.get('clientId');
    const parsed = clientId ? Number(clientId) : NaN;

    setProjectStatusFilter(status === 'ACTIVE' || status === 'INACTIVE' ? status : 'ALL');
    setSelectedClientId(Number.isFinite(parsed) ? parsed : null);
    setNavigationLevel(Number.isFinite(parsed) ? 'projects' : 'clients');
    setExpandedProjectId(deepLinkedProjectId);
  }, [searchParams]);

  React.useEffect(() => {
    if (!deepLinkedProjectId) return;

    const target = document.getElementById(`project-${deepLinkedProjectId}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [deepLinkedProjectId, selectedClientId, projects]);

  if (clientsLoading || projectsLoading || tasksLoading) return <Loading />;
  if (clientsError || projectsError || tasksError) return <Error message="Failed to load client/project/task management data" />;

  const normalizedClientSearch = clientSearch.trim().toLowerCase();
  const normalizedProjectSearch = projectSearch.trim().toLowerCase();

  const clientSuggestions: string[] = Array.from(
    new Set<string>(
      (clients ?? []).flatMap((c: Client) =>
        ([c.name, c.quickbooks_customer_id] as (string | null | undefined)[])
          .filter((v): v is string => typeof v === 'string' && v.length > 0)
      )
    )
  ).sort();

  const projectSuggestions: string[] = Array.from(
    new Set<string>(
      (projects ?? []).flatMap((p: Project) =>
        ([p.name, p.code, p.client?.name] as (string | null | undefined)[])
          .filter((v): v is string => typeof v === 'string' && v.length > 0)
      )
    )
  ).sort();

  const filteredClients = (clients ?? []).filter((client: Client) => {
    if (!normalizedClientSearch) return true;
    return (
      client.name.toLowerCase().includes(normalizedClientSearch) ||
      (client.quickbooks_customer_id ?? '').toLowerCase().includes(normalizedClientSearch)
    );
  });

  const selectedClient = (clients ?? []).find((client: Client) => client.id === selectedClientId) ?? null;

  const filteredProjects = (projects ?? []).filter((project: Project) => {
    const matchesSearch =
      normalizedProjectSearch.length === 0 ||
      project.name.toLowerCase().includes(normalizedProjectSearch) ||
      (project.code ?? '').toLowerCase().includes(normalizedProjectSearch) ||
      (project.client?.name ?? '').toLowerCase().includes(normalizedProjectSearch);

    const matchesStatus =
      projectStatusFilter === 'ALL' ||
      (projectStatusFilter === 'ACTIVE' && project.is_active) ||
      (projectStatusFilter === 'INACTIVE' && !project.is_active);

    const matchesClient = selectedClientId === null || project.client_id === selectedClientId;

    return matchesSearch && matchesStatus && matchesClient;
  });

  // Get tasks for expanded project
  const tasksForExpandedProject = expandedProjectId
    ? (tasks ?? []).filter((task: Task) => task.project_id === expandedProjectId)
    : [];


  const openCreateProject = () => {
    setEditingProject(null);
    setProjectForm({
      ...emptyProjectForm(),
      client_id: selectedClientId ?? 0,
    });
    setProjectError('');
    setShowProjectModal(true);
  };

  const openCreateTask = (projectId: number) => {
    setEditingTask(null);
    setTaskForm(emptyTaskForm());
    setTaskError('');
    setExpandedProjectId(projectId);
    setShowTaskModal(true);
  };

  const openCreateClient = () => {
    setEditingClient(null);
    setClientForm(emptyClientForm());
    setClientError('');
    setShowClientModal(true);
  };

  const openEditClient = (client: Client) => {
    setEditingClient(client);
    setClientForm({
      name: client.name,
      quickbooks_customer_id: client.quickbooks_customer_id || '',
    });
    setClientError('');
    setShowClientModal(true);
  };

  const closeClientModal = () => {
    setShowClientModal(false);
    setEditingClient(null);
    setClientError('');
  };

  const openEditProject = (project: Project) => {
    setEditingProject(project);
    setProjectForm({
      name: project.name,
      client_id: project.client_id,
      billable_rate: Number(project.billable_rate || 0),
      quickbooks_project_id: project.quickbooks_project_id || '',
      code: project.code || '',
      description: project.description || '',
      start_date: project.start_date || '',
      end_date: project.end_date || '',
      estimated_hours: Number(project.estimated_hours || 0),
      budget_amount: Number(project.budget_amount || 0),
      currency: project.currency || 'USD',
      is_active: project.is_active,
    });
    setProjectError('');
    setShowProjectModal(true);
  };

  const closeProjectModal = () => {
    setShowProjectModal(false);
    setEditingProject(null);
    setProjectError('');
  };

  const closeTaskModal = () => {
    setShowTaskModal(false);
    setEditingTask(null);
    setTaskError('');
  };

  const openEditTask = (task: Task) => {
    setEditingTask(task);
    setTaskForm({
      name: task.name,
      code: task.code || '',
      description: task.description || '',
      is_active: task.is_active,
    });
    setTaskError('');
    setShowTaskModal(true);
  };

  const navigateToProjects = (clientId: number) => {
    setSelectedClientId(clientId);
    setNavigationLevel('projects');
    setExpandedProjectId(null);
  };

  const navigateBackToClients = () => {
    setNavigationLevel('clients');
    setSelectedClientId(null);
    setExpandedProjectId(null);
    setProjectSearch('');
    setProjectStatusFilter('ALL');
  };

  const toggleProjectExpanded = (projectId: number) => {
    setExpandedProjectId(expandedProjectId === projectId ? null : projectId);
  };

  const handleProjectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setProjectError('');

    if (!projectForm.name.trim() || !projectForm.client_id || projectForm.billable_rate <= 0) {
      setProjectError('Project name, client, and billable rate are required.');
      return;
    }

    const payload = {
      name: projectForm.name.trim(),
      client_id: projectForm.client_id,
      billable_rate: projectForm.billable_rate,
      quickbooks_project_id: projectForm.quickbooks_project_id.trim() || undefined,
      code: projectForm.code.trim() || undefined,
      description: projectForm.description.trim() || undefined,
      start_date: projectForm.start_date || undefined,
      end_date: projectForm.end_date || undefined,
      estimated_hours: projectForm.estimated_hours > 0 ? projectForm.estimated_hours : undefined,
      budget_amount: projectForm.budget_amount > 0 ? projectForm.budget_amount : undefined,
      currency: projectForm.currency.trim() || undefined,
      is_active: projectForm.is_active,
    };

    try {
      if (editingProject) {
        await updateProject.mutateAsync({ id: editingProject.id, data: payload });
      } else {
        await createProject.mutateAsync(payload);
      }
      closeProjectModal();
    } catch (err: unknown) {
      const message =
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'An error occurred';
      setProjectError(message ?? 'An error occurred');
    }
  };

  const handleClientSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setClientError('');

    if (!clientForm.name.trim()) {
      setClientError('Client name is required.');
      return;
    }

    try {
      if (editingClient) {
        await updateClient.mutateAsync({
          id: editingClient.id,
          data: {
            name: clientForm.name.trim(),
            quickbooks_customer_id: clientForm.quickbooks_customer_id.trim() || undefined,
          },
        });
      } else {
        await createClient.mutateAsync({
          name: clientForm.name.trim(),
          quickbooks_customer_id: clientForm.quickbooks_customer_id.trim() || undefined,
        });
      }
      closeClientModal();
    } catch (err: unknown) {
      const message =
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'An error occurred';
      setClientError(message ?? 'An error occurred');
    }
  };

  const handleTaskSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTaskError('');

    if (!expandedProjectId || !taskForm.name.trim()) {
      setTaskError('Task name is required.');
      return;
    }

    const payload = {
      project_id: expandedProjectId,
      name: taskForm.name.trim(),
      code: taskForm.code.trim() || undefined,
      description: taskForm.description.trim() || undefined,
      is_active: taskForm.is_active,
    };

    try {
      if (editingTask) {
        await updateTask.mutateAsync({ id: editingTask.id, data: payload });
      } else {
        await createTask.mutateAsync(payload);
      }
      closeTaskModal();
    } catch (err: unknown) {
      const message =
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'An error occurred';
      setTaskError(message ?? 'An error occurred');
    }
  };

  const handleDeleteTask = async (taskId: number) => {
    await deleteTask.mutateAsync(taskId);
    setConfirmDeleteTaskId(null);
  };

  const handleDeleteClient = async (client: Client) => {
    const projectCount = (projects ?? []).filter((p: Project) => p.client_id === client.id).length;
    const msg = projectCount > 0
      ? `Delete client "${client.name}" and its ${projectCount} project(s)? This cannot be undone.`
      : `Delete client "${client.name}"? This cannot be undone.`;
    if (!window.confirm(msg)) return;
    try {
      await deleteClient.mutateAsync(client.id);
    } catch {
      alert('Failed to delete client. It may have associated time entries.');
    }
  };

  const handleDeleteProject = async (project: Project) => {
    if (!window.confirm(`Delete project "${project.name}"? This will also delete its tasks and time entries.`)) return;
    try {
      await deleteProject.mutateAsync(project.id);
    } catch {
      alert('Failed to delete project. It may have associated time entries.');
    }
  };

  return (
    <div>
      <div>
        {/* Page Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold">Client Management</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {(clients ?? []).length} clients · {(projects ?? []).length} projects
            </p>
          </div>
        </div>

        {/* CLIENTS VIEW */}
        {navigationLevel === 'clients' && (
          <div className="mb-8">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-2xl font-bold">Clients</h2>
                <p className="text-sm text-muted-foreground mt-1">Select a client to view and manage its projects</p>
              </div>
              <button
                onClick={openCreateClient}
                className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 shadow"
              >
                <PlusCircle className="w-4 h-4" />
                New Client
              </button>
            </div>

            <div className="mb-4">
              <SearchInput
                value={clientSearch}
                onChange={setClientSearch}
                suggestions={clientSuggestions}
                onSelect={(val) => {
                  const match = (clients ?? []).find(
                    (c: Client) => c.name === val || c.quickbooks_customer_id === val
                  );
                  if (match) {
                    setClientSearch('');
                    navigateToProjects(match.id);
                  }
                }}
                placeholder="Search clients by name or QuickBooks ID..."
                className="w-full md:w-96 px-3 py-2 border rounded-lg"
              />
            </div>

            <div className="bg-card border rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-semibold">Client Name</th>
                    <th className="text-left px-4 py-3 font-semibold">QuickBooks Customer ID</th>
                    <th className="text-right px-4 py-3 font-semibold">Projects</th>
                    <th className="text-right px-4 py-3 w-16"></th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredClients.length === 0 && (
                    <tr>
                      <td colSpan={3} className="text-center py-8 text-muted-foreground">
                        No clients found
                      </td>
                    </tr>
                  )}
                  {filteredClients.map((client: Client) => (
                    <tr
                      key={client.id}
                      className="hover:bg-muted/10 transition-colors cursor-pointer"
                      onClick={() => navigateToProjects(client.id)}
                    >
                      <td className="px-4 py-3">
                        <div className="font-semibold text-primary underline underline-offset-2">{client.name}</div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{client.quickbooks_customer_id || '—'}</td>
                      <td className="px-4 py-3 text-right text-muted-foreground">
                        {(projects ?? []).filter((project: Project) => project.client_id === client.id).length}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); openEditClient(client); }}
                            className="inline-flex items-center rounded-md p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                            title="Edit client"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleDeleteClient(client); }}
                            className="inline-flex items-center rounded-md p-1.5 text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
                            title="Delete client"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* PROJECTS VIEW */}
        {navigationLevel === 'projects' && selectedClient && (
          <div className="mb-8">
            {/* Breadcrumb & Title */}
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <button
                    onClick={navigateBackToClients}
                    className="text-primary hover:text-primary/80 text-sm font-medium flex items-center gap-1 transition-colors"
                  >
                    ← Back to Clients
                  </button>
                </div>
                <h2 className="text-2xl font-bold">Projects · {selectedClient.name}</h2>
                <p className="text-sm text-muted-foreground mt-1">Click a project to expand and view its tasks</p>
              </div>
              <button
                onClick={openCreateProject}
                className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 shadow"
              >
                <PlusCircle className="w-4 h-4" />
                New Project
              </button>
            </div>

            {/* Filters */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
              <SearchInput
                value={projectSearch}
                onChange={setProjectSearch}
                suggestions={projectSuggestions}
                onSelect={(val) => {
                  const match = (projects ?? []).find(
                    (p: Project) => p.name === val || p.code === val
                  );
                  if (match) {
                    setProjectSearch('');
                    openEditProject(match);
                  }
                }}
                placeholder="Search projects by name or code..."
                className="w-full px-3 py-2 border rounded-lg"
              />
              <select
                value={projectStatusFilter}
                onChange={(e) => setProjectStatusFilter(e.target.value as 'ALL' | 'ACTIVE' | 'INACTIVE')}
                className="w-full px-3 py-2 border rounded-lg"
              >
                <option value="ALL">All statuses</option>
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </div>

            {/* Projects List */}
            <div className="space-y-3">
              {filteredProjects.length === 0 && (
                <div className="bg-card border rounded-xl p-8 text-center text-muted-foreground">
                  No projects found for {selectedClient.name}
                </div>
              )}
                {filteredProjects.map((project: Project) => (
                  <div key={project.id} className="bg-card border rounded-xl overflow-hidden">
                    {/* Project Row */}
                    <div
                      id={`project-${project.id}`}
                      className={`px-4 py-3 cursor-pointer hover:bg-muted/5 transition-colors flex items-center justify-between ${!project.is_active ? 'opacity-60' : ''} ${deepLinkedProjectId === project.id ? 'ring-2 ring-primary ring-inset' : ''}`}
                      onClick={() => toggleProjectExpanded(project.id)}
                    >
                    <div className="flex-1">
                      <h3 className="font-semibold text-base">{project.name}</h3>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Code: {project.code || '—'} • Rate: ${project.billable_rate} • Hours: {project.estimated_hours || '—'}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${project.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                        {project.is_active ? 'Active' : 'Inactive'}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          openEditProject(project);
                        }}
                        className="p-1.5 rounded hover:bg-muted transition-colors"
                        title="Edit Project"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteProject(project);
                        }}
                        className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors"
                        title="Delete Project"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                      <div className="text-muted-foreground">
                        {expandedProjectId === project.id ? '▼' : '▶'}
                      </div>
                    </div>
                  </div>

                  {/* Expanded Tasks Section */}
                  {expandedProjectId === project.id && (
                    <div className="border-t bg-muted/5 px-4 py-3">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="font-semibold text-sm">Tasks</h4>
                        <button
                          onClick={() => openCreateTask(project.id)}
                          className="flex items-center gap-1 px-3 py-1.5 bg-primary text-primary-foreground text-xs rounded hover:bg-primary/90 transition-colors"
                        >
                          <PlusCircle className="w-3.5 h-3.5" />
                          New Task
                        </button>
                      </div>

                      {tasksForExpandedProject.length === 0 ? (
                        <p className="text-xs text-muted-foreground py-2">No tasks for this project. Create one to get started.</p>
                      ) : (
                        <div className="space-y-2">
                          {tasksForExpandedProject.map((task: Task) => (
                            <div
                              key={task.id}
                              className={`bg-card border rounded px-3 py-2 flex items-center justify-between text-sm ${!task.is_active ? 'opacity-60' : ''}`}
                            >
                              <div className="flex-1">
                                <p className="font-medium">{task.name}</p>
                                {task.code && <p className="text-xs text-muted-foreground">{task.code}</p>}
                              </div>
                              <div className="flex items-center gap-2">
                                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${task.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                                  {task.is_active ? 'Active' : 'Inactive'}
                                </span>
                                <button
                                  onClick={() => openEditTask(task)}
                                  className="p-1 rounded hover:bg-muted transition-colors"
                                  title="Edit Task"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  onClick={() => setConfirmDeleteTaskId(task.id)}
                                  className="p-1 rounded hover:bg-red-50 text-red-600 transition-colors"
                                  title="Delete Task"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {showProjectModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="text-lg font-bold">{editingProject ? 'Edit Project' : 'New Project'}</h2>
              <button onClick={closeProjectModal} className="p-1.5 rounded hover:bg-muted">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleProjectSubmit} className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Project Name</label>
                  <input
                    required
                    value={projectForm.name}
                    onChange={(e) => setProjectForm((current) => ({ ...current, name: e.target.value }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Project Code</label>
                  <input
                    value={projectForm.code}
                    onChange={(e) => setProjectForm((current) => ({ ...current, code: e.target.value }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Client</label>
                  <select
                    value={projectForm.client_id || ''}
                    onChange={(e) => setProjectForm((current) => ({ ...current, client_id: Number(e.target.value) || 0 }))}
                    className="w-full px-3 py-2 border rounded"
                    required
                  >
                    <option value="">Select client</option>
                    {(clients ?? []).map((client: Client) => (
                      <option key={client.id} value={client.id}>{client.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Billable Rate</label>
                  <input
                    required
                    type="number"
                    min="0"
                    step="0.01"
                    value={projectForm.billable_rate}
                    onChange={(e) => setProjectForm((current) => ({ ...current, billable_rate: Number(e.target.value) || 0 }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">QuickBooks Project ID</label>
                  <input
                    value={projectForm.quickbooks_project_id}
                    onChange={(e) => setProjectForm((current) => ({ ...current, quickbooks_project_id: e.target.value }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Currency</label>
                  <input
                    value={projectForm.currency}
                    onChange={(e) => setProjectForm((current) => ({ ...current, currency: e.target.value }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Start Date</label>
                  <input
                    type="date"
                    value={projectForm.start_date}
                    onChange={(e) => setProjectForm((current) => ({ ...current, start_date: e.target.value }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">End Date</label>
                  <input
                    type="date"
                    value={projectForm.end_date}
                    onChange={(e) => setProjectForm((current) => ({ ...current, end_date: e.target.value }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Estimated Hours</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={projectForm.estimated_hours}
                    onChange={(e) => setProjectForm((current) => ({ ...current, estimated_hours: Number(e.target.value) || 0 }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Budget Amount</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={projectForm.budget_amount}
                    onChange={(e) => setProjectForm((current) => ({ ...current, budget_amount: Number(e.target.value) || 0 }))}
                    className="w-full px-3 py-2 border rounded"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea
                  value={projectForm.description}
                  onChange={(e) => setProjectForm((current) => ({ ...current, description: e.target.value }))}
                  className="w-full px-3 py-2 border rounded"
                  rows={3}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="project_is_active"
                  type="checkbox"
                  checked={projectForm.is_active}
                  onChange={(e) => setProjectForm((current) => ({ ...current, is_active: e.target.checked }))}
                  className="rounded"
                />
                <label htmlFor="project_is_active" className="text-sm font-medium">Active project</label>
              </div>

              {projectError && (
                <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{projectError}</p>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createProject.isPending || updateProject.isPending}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {createProject.isPending || updateProject.isPending ? 'Saving...' : editingProject ? 'Save Project' : 'Create Project'}
                </button>
                <button
                  type="button"
                  onClick={closeProjectModal}
                  className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showClientModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-lg">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="text-lg font-bold">{editingClient ? 'Edit Client' : 'New Client'}</h2>
              <button onClick={closeClientModal} className="p-1.5 rounded hover:bg-muted">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleClientSubmit} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Client Name</label>
                <input
                  required
                  value={clientForm.name}
                  onChange={(e) => setClientForm((current) => ({ ...current, name: e.target.value }))}
                  className="w-full px-3 py-2 border rounded"
                  placeholder="Acme Corp"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">QuickBooks Customer ID</label>
                <input
                  value={clientForm.quickbooks_customer_id}
                  onChange={(e) => setClientForm((current) => ({ ...current, quickbooks_customer_id: e.target.value }))}
                  className="w-full px-3 py-2 border rounded"
                  placeholder="Optional"
                />
              </div>

              {clientError && (
                <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{clientError}</p>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createClient.isPending || updateClient.isPending}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {(createClient.isPending || updateClient.isPending) ? 'Saving...' : editingClient ? 'Update Client' : 'Create Client'}
                </button>
                <button
                  type="button"
                  onClick={closeClientModal}
                  className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showTaskModal && expandedProjectId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="text-lg font-bold">{editingTask ? 'Edit Task' : 'New Task'}</h2>
              <button onClick={closeTaskModal} className="p-1.5 rounded hover:bg-muted">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleTaskSubmit} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Task Name</label>
                <input
                  required
                  value={taskForm.name}
                  onChange={(e) => setTaskForm((current) => ({ ...current, name: e.target.value }))}
                  className="w-full px-3 py-2 border rounded"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Task Code</label>
                <input
                  value={taskForm.code}
                  onChange={(e) => setTaskForm((current) => ({ ...current, code: e.target.value }))}
                  className="w-full px-3 py-2 border rounded"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea
                  value={taskForm.description}
                  onChange={(e) => setTaskForm((current) => ({ ...current, description: e.target.value }))}
                  className="w-full px-3 py-2 border rounded"
                  rows={3}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="task_is_active"
                  type="checkbox"
                  checked={taskForm.is_active}
                  onChange={(e) => setTaskForm((current) => ({ ...current, is_active: e.target.checked }))}
                  className="rounded"
                />
                <label htmlFor="task_is_active" className="text-sm font-medium">Active task</label>
              </div>

              {taskError && (
                <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{taskError}</p>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createTask.isPending || updateTask.isPending}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {createTask.isPending || updateTask.isPending ? 'Saving...' : editingTask ? 'Save Task' : 'Create Task'}
                </button>
                <button
                  type="button"
                  onClick={closeTaskModal}
                  className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {confirmDeleteTaskId !== null && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-md p-6">
            <h2 className="text-lg font-bold mb-2">Delete Task</h2>
            <p className="text-sm text-muted-foreground mb-5">This action cannot be undone. Do you want to continue?</p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => handleDeleteTask(confirmDeleteTaskId)}
                disabled={deleteTask.isPending}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-60"
              >
                {deleteTask.isPending ? 'Deleting...' : 'Delete'}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDeleteTaskId(null)}
                className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
