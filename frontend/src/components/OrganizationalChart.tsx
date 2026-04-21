import React, { useMemo } from 'react';
import { User } from '@/types';

interface ChartNode {
  user: User;
  children: ChartNode[];
}

interface OrganizationalChartProps {
  users: User[];
  usersByManager: Record<number, User[]>;
  topLevelUsers: User[];
  currentUserId?: number;
}

const getUserColor = (role: string): string => {
  switch (role) {
    case 'ADMIN':
      return 'bg-red-100 border-red-300 text-red-900';
    case 'MANAGER':
      return 'bg-purple-100 border-purple-300 text-purple-900';
    case 'EMPLOYEE':
      return 'bg-blue-100 border-blue-300 text-blue-900';
    default:
      return 'bg-gray-100 border-gray-300 text-gray-900';
  }
};

interface TreeNodeProps {
  node: ChartNode;
  usersByManager: Record<number, User[]>;
  currentUserId?: number;
  depth: number;
  maxDepth: number;
}

const TreeNode: React.FC<TreeNodeProps> = ({
  node,
  usersByManager,
  currentUserId,
  depth,
  maxDepth,
}) => {
  const children = usersByManager[node.user.id] ?? [];
  const hasChildren = children.length > 0 && depth < maxDepth + 5;
  const isEmployee = node.user.role === 'EMPLOYEE';
  const shouldStackChildren = children.every(
    (child) => child.role === 'EMPLOYEE' || (usersByManager[child.id] ?? []).length === 0,
  );

  return (
    <div className="flex flex-col items-center">
      {/* User Box */}
      <div
        className={`
          border border-opacity-80 rounded px-2 py-1.5 text-center
          ${getUserColor(node.user.role)}
          shadow-sm hover:shadow-md transition-shadow
          ${isEmployee ? 'min-w-[90px]' : 'min-w-[110px]'}
        `}
      >
        <div className={`font-semibold leading-tight ${isEmployee ? 'text-[10px]' : 'text-xs'}`}>{node.user.full_name}</div>
        {!isEmployee && (
          <div className="text-[10px] mt-0.5 opacity-70">{node.user.title || node.user.role}</div>
        )}
        {!isEmployee && node.user.department && (
          <div className="text-[9px] mt-0.5 opacity-60">{node.user.department}</div>
        )}
        {node.user.id === currentUserId && (
          <div className="text-[8px] mt-0.5 opacity-50">← you</div>
        )}
      </div>

      {/* Connector Line */}
      {hasChildren && (
        <div className="w-0.5 h-3 bg-gray-400" />
      )}

      {/* Children */}
      {hasChildren && (
        <div className="relative">
          {shouldStackChildren ? (
            <div className="flex flex-col gap-2 pt-1">
              {children.map((child) => {
                const childNode: ChartNode = {
                  user: child,
                  children: [],
                };

                return (
                  <div key={child.id} className="flex flex-col items-center">
                    <div className="w-0.5 h-3 bg-gray-400 mx-auto" />
                    <TreeNode
                      node={childNode}
                      usersByManager={usersByManager}
                      currentUserId={currentUserId}
                      depth={depth + 1}
                      maxDepth={maxDepth}
                    />
                  </div>
                );
              })}
            </div>
          ) : (
            <>
              {/* Horizontal line connecting all children */}
              <div className="absolute left-0 right-0 top-0 h-0.5 bg-gray-400" />

              {/* Grid layout for children */}
              <div className="grid grid-cols-1 gap-3 pt-3" style={{
                gridTemplateColumns: `repeat(${Math.max(1, Math.min(children.length, 6))}, minmax(140px, 1fr))`,
              }}>
                {children.map((child) => {
                  const childNode: ChartNode = {
                    user: child,
                    children: [],  // Will be populated recursively
                  };

                  return (
                    <div key={child.id} className="flex flex-col items-center">
                      {/* Vertical line from horizontal to this child */}
                      <div className="w-0.5 h-3 bg-gray-400 mx-auto" />

                      {/* Recursively render child */}
                      <TreeNode
                        node={childNode}
                        usersByManager={usersByManager}
                        currentUserId={currentUserId}
                        depth={depth + 1}
                        maxDepth={maxDepth}
                      />
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export const OrganizationalChart: React.FC<OrganizationalChartProps> = ({
  usersByManager,
  topLevelUsers,
  currentUserId,
}) => {
  // Calculate max depth for layout purposes. Guarded so an empty top level
  // yields ``maxDepth = 1`` instead of ``-Infinity`` from ``Math.max(...[])``
  // — the empty branch below short-circuits before render anyway, but a
  // sane number keeps the ``useMemo`` return value safe for future callers.
  const maxDepth = useMemo(() => {
    const calculateDepth = (userId: number, visited: Set<number> = new Set()): number => {
      if (visited.has(userId)) return 0;
      visited.add(userId);
      const subordinates = usersByManager[userId] ?? [];
      if (subordinates.length === 0) return 1;
      return 1 + Math.max(...subordinates.map((u) => calculateDepth(u.id, visited)));
    };

    if (topLevelUsers.length === 0) return 1;
    return Math.max(...topLevelUsers.map((u) => calculateDepth(u.id)));
  }, [topLevelUsers, usersByManager]);

  if (topLevelUsers.length === 0) {
    return (
      <div
        className="flex items-center justify-center p-8 text-muted-foreground"
        data-testid="org-chart-empty"
      >
        <p>No team members yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex gap-6 p-4 w-max min-w-full justify-start">
        {topLevelUsers.map((topUser) => {
          const rootNode: ChartNode = {
            user: topUser,
            children: [],  // Will be populated recursively via usersByManager
          };

          return (
            <TreeNode
              key={topUser.id}
              node={rootNode}
              usersByManager={usersByManager}
              currentUserId={currentUserId}
              depth={0}
              maxDepth={maxDepth}
            />
          );
        })}
      </div>
    </div>
  );
};
