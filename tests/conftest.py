import os
import shutil
from contextlib import contextmanager
from distutils.dir_util import copy_tree
from pathlib import Path
from tempfile import mkdtemp

import ape
import pytest
import solcx  # type: ignore

# NOTE: Ensure that we don't use local paths for these
ape.config.DATA_FOLDER = Path(mkdtemp()).resolve()
ape.config.PROJECT_FOLDER = Path(mkdtemp()).resolve()


@contextmanager
def _tmp_solcx_path(monkeypatch):
    solcx_install_path = mkdtemp()

    monkeypatch.setenv(
        solcx.install.SOLCX_BINARY_PATH_VARIABLE,
        solcx_install_path,
    )

    yield solcx_install_path

    if Path(solcx_install_path).is_dir():
        shutil.rmtree(solcx_install_path, ignore_errors=True)


@pytest.fixture(
    scope="session",
    autouse=os.environ.get("APE_SOLIDITY_USE_SYSTEM_SOLC") is None,
)
def setup_session_solcx_path(request):
    """
    Creates a new, temporary installation path for solcx when the test suite is
    run.

    This ensures the Solidity installations do not conflict with the user's
    installed versions and that the installations from the tests are cleaned up
    after the suite is finished.
    """
    from _pytest.monkeypatch import MonkeyPatch

    patch = MonkeyPatch()
    request.addfinalizer(patch.undo)

    with _tmp_solcx_path(patch) as path:
        yield path


@pytest.fixture
def temp_solcx_path(monkeypatch):
    """
    Creates a new, temporary installation path for solcx for a given test.
    """
    with _tmp_solcx_path(monkeypatch) as path:
        yield path


@pytest.fixture
def config():
    return ape.config


@pytest.fixture(autouse=True)
def project(config):
    project_source_dir = Path(__file__).parent
    project_dest_dir = config.PROJECT_FOLDER / project_source_dir.name

    # Delete build / .cache that may exist pre-copy
    project_path = Path(__file__).parent
    for path in (
        project_path,
        project_path / "BrownieProject",
        project_path / "Dependency",
        project_path / "DependencyOfDependency",
        project_path / "ProjectWithinProject",
        project_path / "VersionSpecifiedInConfig",
    ):
        for cache in (path / ".build", path / "contracts" / ".cache"):
            if cache.is_dir():
                shutil.rmtree(cache)

    copy_tree(project_source_dir.as_posix(), project_dest_dir.as_posix())
    with config.using_project(project_dest_dir) as project:
        yield project
        if project._project._cache_folder.is_dir():
            shutil.rmtree(project._project._cache_folder)


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[".sol"]
