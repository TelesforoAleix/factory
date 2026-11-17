"""Stored role policy and execution levels, separate from version 1 documents."""
from .state import StateError

TOOLS = ('codex', 'claude')
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')
LEVELS = ('light', 'standard', 'strong')


class RoleStore:
    def role_list(self):
        with self.locked():
            return [{'role': r[0], 'tool': r[1], 'model': r[2], 'effort': r[3],
                         'in_list': self.model_in_list(r[1], r[2], r[3])}
                    for r in self.connection.execute(
                        'SELECT role, tool, model, effort FROM cplane_roles ORDER BY role').fetchall()]

    def role_get(self, role):
        # Legacy conversations follow the project policy unless overridden.
        role = 'project' if role == 'legacy' else role
        with self.locked():
            row = self.connection.execute(
                'SELECT tool, model, effort FROM cplane_roles WHERE role = %s', (role,)).fetchone()
            if row is None:
                raise StateError('Unknown role')
            return dict(zip(('tool', 'model', 'effort'), row))

    def role_set(self, role, tool, model, effort):
        with self.mutation():
            self.role_get(role)
            if role == 'legacy':
                raise StateError('Unknown role')
            model = self.model_choice(tool, model, effort)
            self.connection.execute('UPDATE cplane_roles SET tool = %s, model = %s, effort = %s WHERE role = %s',
                                    (tool, model, effort, role))
            return self.role_list()

    def slice_policy(self, identifier):
        with self.locked():
            row = self.connection.execute(
                'SELECT level FROM cplane_slice_levels WHERE slice_id = %s', (identifier,)).fetchone()
            # Retain the public projection shape for existing UI callers. Legacy
            # overrides remain in storage but are never read or applied.
            return {'level': row[0], 'overrides': {}} if row else None

    def slice_level(self, identifier, level, overrides=None):
        if level not in LEVELS:
            raise StateError('Unknown executor level')
        with self.mutation():
            self.connection.execute(
                "INSERT INTO cplane_slice_levels (slice_id, level, overrides) VALUES (%s, %s, '{}'::jsonb) "
                'ON CONFLICT (slice_id) DO UPDATE SET level = EXCLUDED.level', (identifier, level))

    def slice_executor(self, item):
        """Legacy v1 display metadata; execution selection belongs to the platform."""
        return item['executor']
