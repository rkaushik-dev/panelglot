import os
import shutil
import time

import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.locking import (
    STALE_AFTER,
    LockError,
    LockInfo,
    ProjectLock,
    held,
)
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def somebody_else(taken_at, operation="import"):
    return LockInfo(host="buildbox", pid=4242, operation=operation,
                    taken_at=taken_at)


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), *args,
    ])


def lock_path(config):
    return config.root / config.catalog_dir / ".lock"


# -- the record ---------------------------------------------------------


def test_a_lock_round_trips():
    info = somebody_else(1000.0)
    assert LockInfo.parse(info.serialise()) == info


def test_a_half_written_lock_is_no_lock():
    # A corrupt lock file means the writer died mid-create, which means
    # nobody holds it.
    assert LockInfo.parse("buildbox\n42\n") is None


def test_a_lock_with_junk_in_it_is_no_lock():
    assert LockInfo.parse("buildbox\nnotapid\nimport\n100\n") is None


def test_an_empty_file_is_no_lock():
    assert LockInfo.parse("") is None


def test_the_age_is_measured_from_when_it_was_taken():
    assert somebody_else(1000.0).age(1090.0) == 90.0


def test_the_age_never_goes_negative():
    # Clock skew on a share is normal and a negative age would read as stale.
    assert somebody_else(2000.0).age(1000.0) == 0.0


def test_a_fresh_lock_is_not_stale():
    assert not somebody_else(1000.0).is_stale(1000.0 + STALE_AFTER - 1)


def test_an_old_lock_is():
    assert somebody_else(1000.0).is_stale(1000.0 + STALE_AFTER + 1)


def test_the_expiry_is_generous_enough_for_a_real_run():
    # A pretranslate against a rate limited engine takes twenty minutes, and
    # stealing a lock from a process that is still working is the worse bug.
    assert STALE_AFTER >= 20 * 60


def test_a_lock_names_who_holds_it():
    described = somebody_else(time.time() - 30).describe()
    assert "buildbox" in described
    assert "4242" in described
    assert "import" in described


def test_our_own_lock_is_recognised():
    import socket

    mine = LockInfo(host=socket.gethostname(), pid=os.getpid(),
                    operation="x", taken_at=time.time())
    assert mine.is_mine()
    assert not somebody_else(time.time()).is_mine()


# -- taking and giving up -----------------------------------------------


def test_taking_a_lock_creates_the_file(tmp_path):
    path = tmp_path / "catalog" / ".lock"
    with ProjectLock(path, operation="import"):
        assert path.exists()


def test_releasing_removes_it(tmp_path):
    path = tmp_path / "catalog" / ".lock"
    with ProjectLock(path):
        pass
    assert not path.exists()


def test_the_file_says_what_the_operation_was(tmp_path):
    path = tmp_path / ".lock"
    with ProjectLock(path, operation="pretranslate"):
        assert held(path).operation == "pretranslate"


def test_a_second_holder_is_refused(tmp_path):
    path = tmp_path / ".lock"
    path.write_text(somebody_else(time.time()).serialise(), encoding="utf-8")

    with pytest.raises(LockError, match="buildbox"):
        ProjectLock(path).acquire()


def test_the_refusal_says_what_to_do(tmp_path):
    path = tmp_path / ".lock"
    path.write_text(somebody_else(time.time()).serialise(), encoding="utf-8")

    with pytest.raises(LockError, match="delete the file"):
        ProjectLock(path).acquire()


def test_a_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / ".lock"
    path.write_text(somebody_else(time.time() - STALE_AFTER - 60).serialise(),
                    encoding="utf-8")

    lock = ProjectLock(path)
    lock.acquire()
    assert held(path).is_mine()
    lock.release()


def test_taking_over_warns(tmp_path):
    path = tmp_path / ".lock"
    path.write_text(somebody_else(time.time() - STALE_AFTER - 60).serialise(),
                    encoding="utf-8")

    lock = ProjectLock(path)
    lock.acquire()
    assert any("took over a lock" in w for w in lock.warnings)
    lock.release()


def test_a_corrupt_lock_is_simply_taken(tmp_path):
    path = tmp_path / ".lock"
    path.write_text("half a", encoding="utf-8")

    lock = ProjectLock(path)
    lock.acquire()
    assert held(path).is_mine()
    lock.release()


def test_the_same_process_can_take_it_twice(tmp_path):
    path = tmp_path / ".lock"
    first = ProjectLock(path)
    first.acquire()
    ProjectLock(path).acquire()
    first.release()


def test_releasing_a_lock_never_taken_does_nothing(tmp_path):
    ProjectLock(tmp_path / ".lock").release()


def test_the_expiry_can_be_shortened(tmp_path):
    path = tmp_path / ".lock"
    path.write_text(somebody_else(time.time() - 5).serialise(), encoding="utf-8")

    lock = ProjectLock(path, stale_after=1)
    lock.acquire()
    assert held(path).is_mine()


def test_held_of_nothing_is_none(tmp_path):
    assert held(tmp_path / "nowhere.lock") is None


# -- through the commands -----------------------------------------------


def test_a_write_leaves_no_lock_behind(project):
    run(project, "extract")
    assert not lock_path(project).exists()


def test_a_held_lock_stops_an_import(project, tmp_path):
    lock_path(project).parent.mkdir(parents=True, exist_ok=True)
    lock_path(project).write_text(somebody_else(time.time()).serialise(),
                                  encoding="utf-8")

    result = run(project, "extract")
    assert result.exit_code != 0
    # Raised rather than printed here: turning a V4TError into a message and
    # an exit code is the entry point's job, and CliRunner invokes the group.
    assert isinstance(result.exception, LockError)
    assert "buildbox" in str(result.exception)


def test_the_lock_survives_the_failure_it_caused(project):
    lock_path(project).parent.mkdir(parents=True, exist_ok=True)
    original = somebody_else(time.time()).serialise()
    lock_path(project).write_text(original, encoding="utf-8")

    run(project, "extract")
    # The run that was refused must not clean up somebody else's lock on the
    # way out. That is how two writers end up with no lock at all.
    assert lock_path(project).read_text(encoding="utf-8") == original


def test_a_dry_run_takes_no_lock(project):
    lock_path(project).parent.mkdir(parents=True, exist_ok=True)
    lock_path(project).write_text(somebody_else(time.time()).serialise(),
                                  encoding="utf-8")

    # A run that writes nothing has no business making anybody else wait.
    assert run(project, "extract", "--dry-run").exit_code == 0


def test_a_stale_lock_is_reported_on_the_run(project):
    lock_path(project).parent.mkdir(parents=True, exist_ok=True)
    lock_path(project).write_text(
        somebody_else(time.time() - STALE_AFTER - 60).serialise(),
        encoding="utf-8",
    )

    result = run(project, "extract")
    assert result.exit_code == 0
    assert "took over a lock" in result.output


def test_a_read_only_command_never_locks(project):
    lock_path(project).parent.mkdir(parents=True, exist_ok=True)
    lock_path(project).write_text(somebody_else(time.time()).serialise(),
                                  encoding="utf-8")

    assert run(project, "check", "--fail-on", "never").exit_code == 0


def test_the_lock_sits_beside_the_catalog(project):
    run(project, "extract")
    assert lock_path(project).parent == project.catalog_path().parent
