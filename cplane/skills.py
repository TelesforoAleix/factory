"""Repository-owned skills and project switches. No runtime writes to the source."""
import json
from pathlib import Path
import re

from .state import StateError

ROOT = Path(__file__).resolve().parent.parent / 'skills'
DEFAULTS = frozenset(('cut', 'slice-review', 'grilling'))


def catalog():
    result = []
    for path in sorted(ROOT.glob('*.md')):
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', path.stem) or path.is_symlink():
            raise StateError('Invalid skill file')
        text = path.read_text()
        try:
            metadata = json.loads(text.splitlines()[0].removeprefix('--- '))
            if (metadata['name'] != path.stem or not isinstance(metadata['description'], str)
                    or not metadata['description'].strip()):
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            raise StateError('Invalid skill frontmatter') from None
        result.append(dict(name=path.stem, description=metadata['description']))
    return result


def content(name):
    if name not in {skill['name'] for skill in catalog()}:
        raise StateError('Unknown skill')
    return (ROOT / (name + '.md')).read_text()


def instructions(name):
    return content(name).split('\n', 1)[1]


def install(folder, names):
    """Only called on a new root-owned workspace, before ownership transfer."""
    available = {skill['name']: skill for skill in catalog()}
    if not isinstance(names, list) or any(name not in available for name in names):
        raise StateError('Unknown skill')
    lines = ['# Enabled skills', '', 'Read the relevant skill before using it.', '']
    for name in names:
        target = folder / '.claude' / 'skills' / name / 'SKILL.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        # Claude expects YAML frontmatter delimiters on separate lines.
        metadata = available[name]
        target.write_text('---\nname: ' + name + '\ndescription: ' +
                          json.dumps(metadata['description']) + '\n---\n' + instructions(name))
        lines.append(f"- {name}: {available[name]['description']} (.claude/skills/{name}/SKILL.md)")
    (folder / 'AGENTS.md').write_text('\n'.join(lines) + '\n')


class SkillStore:
    def skill_project(self, repositories):
        if len(repositories) != 1:
            return None
        with self.locked():
            rows = list(self.connection.execute(
                'SELECT key FROM cplane_projects WHERE repository = %s',
                (repositories[0].split('/')[-1],)))
            return rows[0][0] if len(rows) == 1 else None

    def skill_list(self, project=None):
        from .cut import skills_version
        with self.locked():
            projects = [r[0] for r in self.connection.execute('SELECT key FROM cplane_projects ORDER BY key')]
            if project is not None and project not in projects:
                raise StateError('Unknown project')
            switches = {(p, s): enabled for p, s, enabled in self.connection.execute(
                'SELECT project, skill, enabled FROM cplane_project_skills')}
            version = skills_version()
            result = []
            for skill in catalog():
                enabled = [p for p in projects if switches.get((p, skill['name']), skill['name'] in DEFAULTS)]
                if project is None or project in enabled:
                    result.append(dict(**skill, version=version, projects=enabled))
            return result

    def skill_set(self, name, project, enabled):
        if name not in {s['name'] for s in catalog()}:
            raise StateError('Unknown skill')
        with self.mutation():
            if not self.connection.execute('SELECT 1 FROM cplane_projects WHERE key = %s', (project,)).fetchone():
                raise StateError('Unknown project')
            self.connection.execute(
                'INSERT INTO cplane_project_skills (project, skill, enabled) VALUES (%s, %s, %s) '
                'ON CONFLICT (project, skill) DO UPDATE SET enabled = EXCLUDED.enabled',
                (project, name, enabled))

    def session_skills(self, repositories):
        from .cut import skills_version
        project = self.skill_project(repositories)
        names = ([s['name'] for s in self.skill_list(project)] if project else
                 sorted(DEFAULTS))
        return names, skills_version()
