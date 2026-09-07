"""Tests for idempotent project-state tracking."""
from forge.models import GitState, Project
from forge.project_state import StateStore, fingerprint, identity


def make(name="demo", dirty=0, readme=True, path=None):
    return Project(name=name, path=path or "/tmp/%s" % name, has_readme=readme,
                   file_count=10, git=GitState(repo=True, branch="main", dirty=dirty))


class TestIdentity:
    def test_same_path_same_key(self):
        assert identity(make()) == identity(make())

    def test_different_paths_differ(self):
        """The same name vendored in a monorepo must not collide."""
        standalone = make("open-school", path="/p/open-school")
        vendored = make("open-school", path="/p/unified/apps/open-school")
        assert identity(standalone) != identity(vendored)

    def test_falls_back_to_name_without_path(self):
        assert identity(Project(name="bare")) == "bare"


class TestFingerprint:
    def test_is_stable(self):
        assert fingerprint(make()) == fingerprint(make())

    def test_changes_with_state(self):
        assert fingerprint(make(dirty=0)) != fingerprint(make(dirty=5))

    def test_changes_with_flags(self):
        assert fingerprint(make(readme=True)) != fingerprint(make(readme=False))

    def test_is_short_hex(self):
        digest = fingerprint(make())
        assert len(digest) == 16
        int(digest, 16)


class TestStateStore:
    def test_first_record_is_new(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        assert store.record(make()) == "new"

    def test_second_identical_record_is_unchanged(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        store.record(make())
        assert store.record(make()) == "unchanged"

    def test_modified_project_is_changed(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        store.record(make(dirty=0))
        assert store.record(make(dirty=9)) == "changed"

    def test_roundtrip_persists(self, tmp_path):
        path = tmp_path / "s.json"
        store = StateStore(path=path)
        store.record(make())
        store.save()

        reloaded = StateStore.load(path)
        assert identity(make()) in reloaded.snapshots
        assert reloaded.snapshots[identity(make())].name == "demo"

    def test_idempotent_across_reloads(self, tmp_path):
        """Running the pipeline repeatedly must not report spurious changes."""
        path = tmp_path / "s.json"
        for _ in range(5):
            store = StateStore.load(path)
            outcome = store.record(make())
            store.save()
        assert outcome == "unchanged"

    def test_record_all_counts(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        counts = store.record_all([make("a"), make("b")])
        assert counts["new"] == 2

    def test_missing_file_loads_empty(self, tmp_path):
        assert StateStore.load(tmp_path / "absent.json").snapshots == {}

    def test_corrupt_file_loads_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert StateStore.load(path).snapshots == {}

    def test_regression_detected(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        store.record(make(readme=True))
        worse = make(readme=False)
        assert store.regressed([worse])

    def test_no_false_regression(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        store.record(make())
        assert store.regressed([make()]) == []


class TestDuplicateNames:
    """Regression guard: same name at two paths used to overwrite each other."""

    def pair(self):
        return [make("open-school", dirty=0, path="/p/open-school"),
                make("open-school", dirty=7, path="/p/unified/apps/open-school")]

    def test_both_paths_recorded(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        store.record_all(self.pair())
        assert len(store.snapshots) == 2

    def test_stays_idempotent_across_runs(self, tmp_path):
        path = tmp_path / "s.json"
        for _ in range(4):
            store = StateStore.load(path)
            counts = store.record_all(self.pair())
            store.save()
        assert counts == {"new": 0, "changed": 0, "unchanged": 2}

    def test_duplicates_reported(self, tmp_path):
        store = StateStore(path=tmp_path / "s.json")
        store.record_all(self.pair())
        dupes = store.duplicates()
        assert "open-school" in dupes
        assert len(dupes["open-school"]) == 2
