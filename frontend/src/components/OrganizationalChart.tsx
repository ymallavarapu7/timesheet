import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { User } from '@/types';
import { cn } from '@/lib/utils';

interface OrgChartProps {
  users: User[];
  usersByManager: Record<number, User[]>;
  topLevelUsers: User[];
  currentUserId?: number;
}

// ---------------------------------------------------------------------------
// Role badge
// ---------------------------------------------------------------------------

const ROLE_STYLES: Record<string, string> = {
  VIEWER:        'bg-yellow-500/10 text-yellow-500 border border-yellow-500/25',
  ADMIN:         'bg-red-500/10    text-red-400    border border-red-500/25',
  MANAGER:       'bg-purple-500/10 text-purple-400 border border-purple-500/25',
  SENIOR_MANAGER:'bg-purple-500/10 text-purple-400 border border-purple-500/25',
  EMPLOYEE:      'bg-blue-500/10   text-blue-400   border border-blue-500/20',
  PLATFORM_ADMIN:'bg-red-500/10    text-red-400    border border-red-500/25',
};

const ROLE_LABELS: Record<string, string> = {
  VIEWER: 'CEO', ADMIN: 'Admin', MANAGER: 'Manager',
  SENIOR_MANAGER: 'Sr. Manager', EMPLOYEE: 'Employee', PLATFORM_ADMIN: 'Platform Admin',
};

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={cn('text-[9px] font-bold tracking-wide uppercase px-1.5 py-0.5 rounded', ROLE_STYLES[role] ?? ROLE_STYLES.EMPLOYEE)}>
      {ROLE_LABELS[role] ?? role}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Node card
// ---------------------------------------------------------------------------

interface NodeCardProps {
  user: User;
  isCurrentUser: boolean;
  isCollapsed: boolean;
  hasChildren: boolean;
  descendantCount: number;
  onToggle: () => void;
  searchQuery: string;
  reportsToName?: string;
}

const NodeCard = React.memo(function NodeCard({
  user, isCurrentUser, isCollapsed, hasChildren, descendantCount, onToggle, searchQuery, reportsToName,
}: NodeCardProps) {
  const isMatch = searchQuery.length > 0 && user.full_name.toLowerCase().includes(searchQuery);
  const isDimmed = searchQuery.length > 0 && !isMatch;

  return (
    <div
      onClick={hasChildren ? onToggle : undefined}
      className={cn(
        'relative rounded-[10px] border bg-card px-3.5 py-2.5 select-none transition-all duration-150',
        'w-[190px]',
        hasChildren && 'cursor-pointer',
        isCurrentUser
          ? 'border-primary shadow-[0_0_0_3px_rgba(56,139,253,0.18)]'
          : 'border-border hover:border-primary/60 hover:shadow-[0_0_0_3px_rgba(56,139,253,0.1)] hover:bg-muted/30',
        isMatch && 'border-orange-400 shadow-[0_0_0_3px_rgba(240,136,62,0.2)]',
        isDimmed && 'opacity-10 pointer-events-none',
      )}
    >
      {/* collapsed descendant count bubble */}
      {hasChildren && isCollapsed && descendantCount > 0 && (
        <span className="absolute -top-2 -right-2 bg-muted border border-border text-muted-foreground text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none z-10">
          +{descendantCount}
        </span>
      )}

      <p className="text-[13px] font-semibold text-foreground leading-snug truncate">{user.full_name}</p>
      {user.title && <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{user.title}</p>}
      {user.department && <p className="text-[10px] text-muted-foreground/60 mt-0.5 truncate">{user.department}</p>}
      {reportsToName && (
        <p className="text-[9px] text-muted-foreground/50 mt-0.5 truncate">↑ {reportsToName}</p>
      )}

      <div className="flex items-center justify-between mt-2 gap-1.5">
        <div className="flex items-center gap-1 flex-wrap">
          <RoleBadge role={user.role} />
          {isCurrentUser && (
            <span className="text-[9px] font-semibold text-primary bg-primary/10 border border-primary/25 px-1.5 py-0.5 rounded">
              you
            </span>
          )}
        </div>
        {hasChildren && (
          <span className="w-[18px] h-[18px] rounded-full bg-muted border border-border text-muted-foreground text-[11px] font-bold flex items-center justify-center shrink-0">
            {isCollapsed ? '+' : '−'}
          </span>
        )}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Tree node — CSS connector approach
//
// Layout per node:
//   [card]
//   | (vertical stem, 28px)
//   [horizontal bar spanning all children]
//   | | | (vertical drop to each child)
//   [child] [child] [child]
//
// All done with border/pseudo tricks on wrapper divs — no SVG, no DOM measurements.
// ---------------------------------------------------------------------------

interface TreeNodeProps {
  user: User;
  usersByManager: Record<number, User[]>;
  currentUserId?: number;
  searchQuery: string;
  depth: number;
  expandAll: boolean;
  expandVersion: number;
  reportsToName?: string;
  hasParentLine?: boolean;
}

function TreeNode({
  user, usersByManager, currentUserId, searchQuery, depth, expandAll, expandVersion, reportsToName, hasParentLine,
}: TreeNodeProps) {
  const children = usersByManager[user.id] ?? [];
  const hasChildren = children.length > 0;

  const [collapsed, setCollapsed] = useState(depth >= 2);

  // Only respond when expandVersion actually increments (button click), not on mount/remount.
  const lastVersion = useRef(expandVersion);
  useEffect(() => {
    if (expandVersion === lastVersion.current) return;
    lastVersion.current = expandVersion;
    setCollapsed(!expandAll);
  }, [expandVersion, expandAll]);

  const descendantCount = useMemo(() => {
    const count = (uid: number): number => {
      const c = usersByManager[uid] ?? [];
      return c.reduce((acc, ch) => acc + 1 + count(ch.id), 0);
    };
    return count(user.id);
  }, [user.id, usersByManager]);

  const showChildren = hasChildren && !collapsed;

  return (
    // Outer wrapper: flex column, centered horizontally
    <div className="flex flex-col items-center relative">

      {/* Vertical line coming IN from parent above */}
      {hasParentLine && (
        <div className="w-px bg-border" style={{ height: 28 }} />
      )}

      {/* The card itself */}
      <NodeCard
        user={user}
        isCurrentUser={user.id === currentUserId}
        isCollapsed={collapsed}
        hasChildren={hasChildren}
        descendantCount={descendantCount}
        onToggle={() => setCollapsed(c => !c)}
        searchQuery={searchQuery}
        reportsToName={reportsToName}
      />

      {/* Children subtree */}
      {showChildren && (
        <div className="flex flex-col items-center">
          {/* Stem down from card to horizontal bar */}
          <div className="w-px bg-border" style={{ height: 24 }} />

          {children.length === 1 ? (
            // Single child: just a straight line, no horizontal bar
            <TreeNode
              key={children[0].id}
              user={children[0]}
              usersByManager={usersByManager}
              currentUserId={currentUserId}
              searchQuery={searchQuery}
              depth={depth + 1}
              expandAll={expandAll}
              expandVersion={expandVersion}
              hasParentLine={true}
            />
          ) : (
            // Multiple children: horizontal bar with drops
            <div className="relative flex flex-row items-start">
              {children.map((child, i) => {
                const isFirst = i === 0;
                const isLast  = i === children.length - 1;
                return (
                  <div key={child.id} className="flex flex-col items-center" style={{ padding: '0 20px' }}>
                    {/* Horizontal bar segment + vertical drop */}
                    <div className="relative w-full flex justify-center" style={{ height: 24 }}>
                      {/* Left half of horizontal bar */}
                      {!isFirst && (
                        <div
                          className="absolute bg-border"
                          style={{ height: 2, top: 0, right: '50%', left: 0 }}
                        />
                      )}
                      {/* Right half of horizontal bar */}
                      {!isLast && (
                        <div
                          className="absolute bg-border"
                          style={{ height: 2, top: 0, left: '50%', right: 0 }}
                        />
                      )}
                      {/* Vertical drop from bar to child */}
                      <div
                        className="absolute bg-border"
                        style={{ width: 2, top: 0, bottom: 0, left: 'calc(50% - 1px)' }}
                      />
                    </div>

                    <TreeNode
                      user={child}
                      usersByManager={usersByManager}
                      currentUserId={currentUserId}
                      searchQuery={searchQuery}
                      depth={depth + 1}
                      expandAll={expandAll}
                      expandVersion={expandVersion}
                      hasParentLine={false}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// External list view
// ---------------------------------------------------------------------------

function ExternalList({ users, searchQuery }: { users: User[]; searchQuery: string }) {
  const filtered = searchQuery
    ? users.filter(u => u.full_name.toLowerCase().includes(searchQuery))
    : users;

  if (users.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        No external employees found.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">
        External employees — {users.length} total
      </p>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
        {filtered.map(user => (
          <div
            key={user.id}
            className="rounded-[10px] border border-border bg-card px-3.5 py-2.5 hover:border-primary/60 hover:bg-muted/30 transition-all"
          >
            <p className="text-[13px] font-semibold text-foreground truncate">{user.full_name}</p>
            {user.title && <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{user.title}</p>}
            {user.department && <p className="text-[10px] text-muted-foreground/60 mt-0.5 truncate">{user.department}</p>}
            <div className="flex items-center gap-1.5 mt-2">
              <RoleBadge role={user.role} />
              <span className="text-[9px] font-bold tracking-wide uppercase px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border">
                EXT
              </span>
            </div>
          </div>
        ))}
      </div>
      {filtered.length === 0 && searchQuery && (
        <p className="text-sm text-muted-foreground mt-4">No results for "{searchQuery}"</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Missing manager drawer
// ---------------------------------------------------------------------------

function MissingManagerDrawer({ users, open, onClose }: { users: User[]; open: boolean; onClose: () => void }) {
  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />}
      <div className={cn(
        'fixed top-0 right-0 bottom-0 z-50 w-[320px] bg-card border-l border-border flex flex-col transition-transform duration-200',
        open ? 'translate-x-0' : 'translate-x-full',
      )}>
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-border shrink-0">
          <div>
            <p className="text-sm font-semibold">Employees missing a manager</p>
            <p className="text-xs text-muted-foreground mt-0.5">Assign a manager so they appear in the hierarchy</p>
          </div>
          <button
            onClick={onClose}
            className="w-6 h-6 rounded-md border border-border bg-muted text-muted-foreground flex items-center justify-center text-xs hover:bg-muted/80"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
          {users.map(u => (
            <div key={u.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-3 py-2.5">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-foreground truncate">{u.full_name}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  {u.role}{u.department ? ` · ${u.department}` : ''}
                </p>
              </div>
              <button className="text-[10px] font-semibold px-2.5 py-1.5 rounded-md border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors shrink-0 whitespace-nowrap">
                Assign manager
              </button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const OrganizationalChart: React.FC<OrgChartProps> = ({
  users,
  currentUserId,
}) => {
  const [view, setView]               = useState<'internal' | 'external'>('internal');
  const [searchQuery, setSearchQuery] = useState('');
  const [drawerOpen, setDrawerOpen]   = useState(false);
  const [expandAll, setExpandAll]     = useState(false);
  const [expandVersion, setExpandVersion] = useState(0);

  // Pan + zoom state
  const [scale, setScale]   = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragging  = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, ox: 0, oy: 0 });
  const wrapRef   = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const stateRef  = useRef({ scale: 1, offset: { x: 0, y: 0 } });

  const externalUsers = useMemo(() => users.filter(u => u.is_external), [users]);
  const internalUsers = useMemo(() => users.filter(u => !u.is_external), [users]);

  const internalUsersByManager = useMemo(() => {
    const map: Record<number, User[]> = {};
    internalUsers.forEach(u => {
      if (!u.manager_id) return;
      if (!map[u.manager_id]) map[u.manager_id] = [];
      map[u.manager_id].push(u);
    });
    Object.values(map).forEach(arr => arr.sort((a, b) => a.full_name.localeCompare(b.full_name)));
    return map;
  }, [internalUsers]);

  const internalVisibleIds = useMemo(
    () => new Set(internalUsers.map(u => u.id)),
    [internalUsers],
  );

  const allUserIdToName = useMemo(() => {
    const m: Record<number, string> = {};
    users.forEach(u => { m[u.id] = u.full_name; });
    return m;
  }, [users]);

  const { internalTopLevel, missingManagerUsers } = useMemo(() => {
    const roots = internalUsers
      .filter(u => !u.manager_id || !internalVisibleIds.has(u.manager_id))
      .sort((a, b) => a.full_name.localeCompare(b.full_name));

    const topLevel: User[] = [];
    const missing: User[]  = [];
    roots.forEach(u => {
      if ((internalUsersByManager[u.id] ?? []).length > 0) {
        topLevel.push(u);
      } else if (!u.manager_id) {
        missing.push(u);
      } else {
        topLevel.push(u);
      }
    });
    return { internalTopLevel: topLevel, missingManagerUsers: missing };
  }, [internalUsers, internalVisibleIds, internalUsersByManager]);

  const q = searchQuery.trim().toLowerCase();


  useEffect(() => { stateRef.current = { scale, offset }; }, [scale, offset]);

  const fitView = useCallback(() => {
    if (!wrapRef.current || !canvasRef.current) return;
    const ww = wrapRef.current.clientWidth;
    const wh = wrapRef.current.clientHeight;
    // Reset transform to measure natural content size, then restore.
    const el = canvasRef.current;
    const prev = el.style.transform;
    el.style.transform = 'none';
    const cw = el.offsetWidth;
    const ch = el.offsetHeight;
    el.style.transform = prev;
    const s  = Math.min(1, (ww - 80) / Math.max(cw, 1), (wh - 60) / Math.max(ch, 1));
    const next = { scale: s, offset: { x: (ww - cw * s) / 2, y: 40 } };
    stateRef.current = next;
    setScale(next.scale);
    setOffset(next.offset);
  }, []);

  useEffect(() => {
    const t = setTimeout(fitView, 150);
    return () => clearTimeout(t);
  }, [fitView, view, expandAll]);

  // Native wheel listener
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const { scale: s, offset: o } = stateRef.current;
      const rect  = el.getBoundingClientRect();
      const mx    = e.clientX - rect.left;
      const my    = e.clientY - rect.top;
      const raw   = e.deltaMode === 1 ? e.deltaY * 20 : e.deltaY;
      const delta = raw > 0 ? -0.08 : 0.08;
      const ns    = Math.min(2, Math.max(0.15, s + delta));
      const next  = {
        scale: ns,
        offset: {
          x: mx - (mx - o.x) * (ns / s),
          y: my - (my - o.y) * (ns / s),
        },
      };
      stateRef.current = next;
      setScale(next.scale);
      setOffset(next.offset);
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('[data-nopan]')) return;
    e.preventDefault();
    dragging.current = true;
    dragStart.current = {
      x: e.clientX, y: e.clientY,
      ox: stateRef.current.offset.x,
      oy: stateRef.current.offset.y,
    };
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current) return;
    const next = {
      x: dragStart.current.ox + e.clientX - dragStart.current.x,
      y: dragStart.current.oy + e.clientY - dragStart.current.y,
    };
    stateRef.current.offset = next;
    setOffset(next);
  }, []);

  const onMouseUp = useCallback(() => { dragging.current = false; }, []);

  if (internalTopLevel.length === 0 && externalUsers.length === 0) {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground" data-testid="org-chart-empty">
        <p>No team members yet.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col" style={{ height: '600px' }}>
      {/* ── Toolbar ── */}
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border shrink-0 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            placeholder="Search name…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            data-nopan
            className="h-7 px-2.5 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground outline-none focus:border-primary w-40"
          />

          <div className="flex gap-0.5 bg-muted border border-border rounded-lg p-0.5">
            {(['internal', 'external'] as const).map(v => (
              <button
                key={v}
                data-nopan
                onClick={() => setView(v)}
                className={cn(
                  'px-3 py-1 rounded-md text-[11px] font-semibold transition-all',
                  view === v ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {v === 'internal' ? 'Internal' : 'External'}
              </button>
            ))}
          </div>

          {view === 'internal' && missingManagerUsers.length > 0 && (
            <button
              data-nopan
              onClick={() => setDrawerOpen(true)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-yellow-500/30 bg-yellow-500/8 text-yellow-500 text-[11px] font-semibold hover:bg-yellow-500/14 transition-colors"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 shrink-0" />
              {missingManagerUsers.length} employee{missingManagerUsers.length !== 1 ? 's' : ''} missing a manager
            </button>
          )}
        </div>

        {view === 'internal' && (
          <div className="flex items-center gap-1.5">
            <button
              data-nopan
              onClick={() => { setExpandAll(v => !v); setExpandVersion(v => v + 1); }}
              className="h-6 px-2.5 rounded border border-border bg-muted text-muted-foreground text-xs hover:bg-muted/80 font-medium"
            >
              {expandAll ? 'Collapse all' : 'Expand all'}
            </button>
            <div className="w-px h-4 bg-border" />
            <button data-nopan onClick={() => setScale(s => Math.max(0.15, s - 0.1))} className="h-6 w-6 rounded border border-border bg-muted text-muted-foreground text-sm flex items-center justify-center hover:bg-muted/80">−</button>
            <span className="text-xs text-muted-foreground w-9 text-center">{Math.round(scale * 100)}%</span>
            <button data-nopan onClick={() => setScale(s => Math.min(2, s + 0.1))} className="h-6 w-6 rounded border border-border bg-muted text-muted-foreground text-sm flex items-center justify-center hover:bg-muted/80">+</button>
            <button data-nopan onClick={fitView} className="h-6 px-2 rounded border border-border bg-muted text-muted-foreground text-xs hover:bg-muted/80">Fit</button>
          </div>
        )}
      </div>

      {/* ── Internal tree ── */}
      {view === 'internal' && (
        <div
          ref={wrapRef}
          className="flex-1 overflow-hidden relative cursor-grab active:cursor-grabbing"
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <div
            ref={canvasRef}
            style={{
              position: 'absolute', top: 0, left: 0,
              transformOrigin: '0 0',
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
              padding: '40px 60px 80px',
              width: 'max-content',
            }}
          >
            {internalTopLevel.length === 0 ? (
              <p className="text-sm text-muted-foreground">No internal employees yet.</p>
            ) : internalTopLevel.length === 1 ? (
              <TreeNode
                user={internalTopLevel[0]}
                usersByManager={internalUsersByManager}
                currentUserId={currentUserId}
                searchQuery={q}
                depth={0}
                expandAll={expandAll}
                expandVersion={expandVersion}
                hasParentLine={false}
                reportsToName={
                  internalTopLevel[0].manager_id && !internalVisibleIds.has(internalTopLevel[0].manager_id)
                    ? (allUserIdToName[internalTopLevel[0].manager_id] ?? 'External')
                    : undefined
                }
              />
            ) : (
              <div className="flex items-start gap-16">
                {internalTopLevel.map(u => (
                  <TreeNode
                    key={u.id}
                    user={u}
                    usersByManager={internalUsersByManager}
                    currentUserId={currentUserId}
                    searchQuery={q}
                    depth={0}
                    expandAll={expandAll}
                    expandVersion={expandVersion}
                    hasParentLine={false}
                    reportsToName={
                      u.manager_id && !internalVisibleIds.has(u.manager_id)
                        ? (allUserIdToName[u.manager_id] ?? 'External')
                        : undefined
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── External list ── */}
      {view === 'external' && (
        <ExternalList users={externalUsers} searchQuery={q} />
      )}

      {/* ── Missing manager drawer ── */}
      <MissingManagerDrawer
        users={missingManagerUsers}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
};
