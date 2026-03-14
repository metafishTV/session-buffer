"""Tests for buffer_utils — shared hook discovery utilities."""
import os
import json
import pytest

import importlib.util
_spec = importlib.util.spec_from_file_location(
    'buffer_utils',
    os.path.join(os.path.dirname(__file__), '..', 'plugin', 'scripts', 'buffer_utils.py'))
buffer_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buffer_utils)


class TestIsGitRepo:
    def test_directory_with_dot_git(self, tmp_path):
        (tmp_path / '.git').mkdir()
        assert buffer_utils.is_git_repo(str(tmp_path)) is True

    def test_directory_without_dot_git(self, tmp_path):
        assert buffer_utils.is_git_repo(str(tmp_path)) is False

    def test_nonexistent_directory(self, tmp_path):
        assert buffer_utils.is_git_repo(str(tmp_path / 'nope')) is False


class TestMatchCwdToProject:
    def test_cwd_equals_repo_root(self):
        assert buffer_utils.match_cwd_to_project('/home/user/proj', '/home/user/proj') is True

    def test_cwd_inside_repo(self):
        assert buffer_utils.match_cwd_to_project('/home/user/proj/src/lib', '/home/user/proj') is True

    def test_cwd_is_parent_of_repo(self):
        assert buffer_utils.match_cwd_to_project('/home/user', '/home/user/proj') is False

    def test_cwd_unrelated(self):
        assert buffer_utils.match_cwd_to_project('/tmp/other', '/home/user/proj') is False

    def test_prefix_collision_blocked(self):
        """repo_root=/proj must NOT match cwd=/project-2."""
        assert buffer_utils.match_cwd_to_project('/project-2', '/proj') is False

    @pytest.mark.skipif(os.name != 'nt', reason='Windows-only')
    def test_windows_case_insensitive(self):
        assert buffer_utils.match_cwd_to_project(
            'c:\\Users\\user\\proj', 'C:\\Users\\user\\proj') is True


class TestReadRegistry:
    def test_no_file_returns_empty(self, tmp_path):
        result = buffer_utils.read_registry(str(tmp_path / 'nonexistent.json'))
        assert result == {'schema_version': 2, 'projects': {}}

    def test_reads_v2_as_is(self, tmp_path):
        reg = {
            'schema_version': 2,
            'projects': {
                'myproj': {
                    'repo_root': '/home/user/myproj',
                    'buffer_path': '/home/user/myproj/.claude/buffer',
                    'scope': 'full',
                    'last_handoff': '2026-03-14'
                }
            }
        }
        path = tmp_path / 'projects.json'
        path.write_text(json.dumps(reg), encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        assert result['schema_version'] == 2
        assert result['projects']['myproj']['repo_root'] == '/home/user/myproj'

    def test_upgrades_v1_to_v2(self, tmp_path):
        reg = {
            'schema_version': 1,
            'projects': {
                'myproj': {
                    'buffer_path': '/home/user/myproj/.claude/buffer',
                    'scope': 'full',
                    'last_handoff': '2026-03-10',
                    'remote_backup': True,
                    'project_context': 'test project'
                }
            }
        }
        path = tmp_path / 'projects.json'
        path.write_text(json.dumps(reg), encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        assert result['schema_version'] == 2
        proj = result['projects']['myproj']
        assert proj['repo_root'] == '/home/user/myproj'
        assert proj['scope'] == 'full'
        assert proj['remote_backup'] is True
        assert proj['project_context'] == 'test project'
        assert proj['last_handoff'] == '2026-03-10'

    def test_v1_upgrade_strips_buffer_suffix(self, tmp_path):
        reg = {
            'schema_version': 1,
            'projects': {
                'winproj': {
                    'buffer_path': 'C:\\Users\\user\\proj\\.claude\\buffer',
                    'scope': 'lite'
                }
            }
        }
        path = tmp_path / 'projects.json'
        path.write_text(json.dumps(reg), encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        proj = result['projects']['winproj']
        assert '.claude' not in proj['repo_root']
        assert 'buffer' not in proj['repo_root']

    def test_corrupt_json_returns_empty(self, tmp_path):
        path = tmp_path / 'projects.json'
        path.write_text('not json', encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        assert result == {'schema_version': 2, 'projects': {}}


class TestFindBufferDir:
    def _make_buffer(self, root):
        buf = root / '.claude' / 'buffer'
        buf.mkdir(parents=True)
        (buf / 'handoff.json').write_text('{}', encoding='utf-8')
        return buf

    def _make_git_repo(self, root):
        (root / '.git').mkdir(exist_ok=True)

    def _make_registry(self, reg_path, projects):
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        data = {'schema_version': 2, 'projects': projects}
        reg_path.write_text(json.dumps(data), encoding='utf-8')

    def test_registry_match_returns_buffer_path(self, tmp_path):
        repo = tmp_path / 'myrepo'
        repo.mkdir()
        self._make_git_repo(repo)
        buf = self._make_buffer(repo)
        reg_path = tmp_path / 'registry.json'
        self._make_registry(reg_path, {
            'myproj': {
                'repo_root': str(repo),
                'buffer_path': str(buf),
            }
        })
        result = buffer_utils.find_buffer_dir(str(repo), registry_path=str(reg_path))
        assert result == str(buf)

    def test_registry_match_cwd_inside_repo(self, tmp_path):
        repo = tmp_path / 'myrepo'
        subdir = repo / 'src' / 'lib'
        subdir.mkdir(parents=True)
        self._make_git_repo(repo)
        buf = self._make_buffer(repo)
        reg_path = tmp_path / 'registry.json'
        self._make_registry(reg_path, {
            'myproj': {
                'repo_root': str(repo),
                'buffer_path': str(buf),
            }
        })
        result = buffer_utils.find_buffer_dir(str(subdir), registry_path=str(reg_path))
        assert result == str(buf)

    def test_walkup_finds_buffer_in_git_repo(self, tmp_path):
        repo = tmp_path / 'myrepo'
        repo.mkdir()
        self._make_git_repo(repo)
        buf = self._make_buffer(repo)
        reg_path = tmp_path / 'empty_registry.json'
        result = buffer_utils.find_buffer_dir(str(repo), registry_path=str(reg_path))
        assert result == str(buf)

    def test_walkup_rejects_buffer_in_non_git_dir(self, tmp_path):
        non_git = tmp_path / 'workspace'
        non_git.mkdir()
        self._make_buffer(non_git)
        reg_path = tmp_path / 'empty_registry.json'
        result = buffer_utils.find_buffer_dir(str(non_git), registry_path=str(reg_path))
        assert result is None

    def test_no_buffer_anywhere_returns_none(self, tmp_path):
        reg_path = tmp_path / 'empty_registry.json'
        result = buffer_utils.find_buffer_dir(str(tmp_path), registry_path=str(reg_path))
        assert result is None

    def test_registry_path_not_on_disk_returns_none(self, tmp_path):
        reg_path = tmp_path / 'registry.json'
        self._make_registry(reg_path, {
            'myproj': {
                'repo_root': str(tmp_path / 'ghost'),
                'buffer_path': str(tmp_path / 'ghost' / '.claude' / 'buffer'),
            }
        })
        result = buffer_utils.find_buffer_dir(str(tmp_path / 'ghost'), registry_path=str(reg_path))
        assert result is None
