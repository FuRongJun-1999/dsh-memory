"""Opt-in, thread-local CSRE session for normal SQLite transaction writers.

Keeps a read-only observer open only inside ``with CsreSession(...)``. SQLite
data_version detects commits, including WAL and restored-mtime updates. A new
version still triggers the original full content/schema hash. Default Csre and
navigation keep full validation; MD sources always keep full fresh reads.
"""
import os
from pathlib import Path
import sqlite3

try:
    from .csre import Csre
except ImportError:
    from csre import Csre


class CsreSession(Csre):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active = False
        self._observer = None
        self._identity = None
        self._snapshot_cache = None
        self._snapshot_token = None
        self._source_kind = None
        self.full_source_reads = 0
        self.source_cache_hits = 0

    def __enter__(self):
        if self._active:
            raise RuntimeError('CSRE session is already active')
        self._active = True
        return self

    def __exit__(self, *_):
        self.close()

    def _close_observer(self):
        if self._observer is not None:
            self._observer.close()
        self._observer = self._identity = None
        self._snapshot_cache = self._snapshot_token = None

    def close(self):
        self._close_observer()
        self._active = False
        self._invalidate('session_closed')

    def _file_identity(self):
        path = Path(self.db_path).resolve()
        stat = path.stat()
        return os.path.normcase(os.path.realpath(path)), stat.st_dev, stat.st_ino

    def _version(self):
        return self._observer.execute('PRAGMA data_version').fetchone()[0]

    def _full_snapshot(self):
        self.full_source_reads += 1
        return super()._source_snapshot()

    def _source_snapshot(self):
        if not self._active:
            raise RuntimeError('use CsreSession inside a with block')
        root = os.environ.get('WB_MD_ROOT') or ''
        if os.environ.get('WB_MD_DIRECT') == '1' and os.path.isdir(root):
            self._close_observer()
            self._source_kind = 'md'
            return self._full_snapshot()
        self._source_kind = 'sqlite'
        for _ in range(3):
            identity = self._file_identity()
            if identity != self._identity:
                self._close_observer()
                path = Path(self.db_path).resolve()
                self._observer = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                self._identity = identity
            before = self._version()
            token = identity, before
            if token == self._snapshot_token and self._snapshot_cache is not None:
                self.source_cache_hits += 1
                return self._snapshot_cache
            snapshot = self._full_snapshot()
            after = self._version()
            if before == after and identity == self._file_identity():
                self._snapshot_cache = snapshot
                self._snapshot_token = token
                return snapshot
        raise RuntimeError('source changed during three validation attempts')

    def index_info(self):
        return dict(super().index_info(),
                    freshness_check=('full_source_row_hash_for_md' if self._source_kind == 'md'
                                     else 'sqlite_data_version_in_explicit_session'),
                    full_source_reads=self.full_source_reads,
                    source_cache_hits=self.source_cache_hits,
                    session_active=self._active)
