import os
import shutil
from contextlib import contextmanager
from distutils.dir_util import copy_tree
from pathlib import Path
from tempfile import mkdtemp

import ape
import pytest
import solcx  # type: ignore

from ape_solidity.compiler import Extension

# NOTE: Ensure that we don't use local paths for these
DATA_FOLDER = Path(mkdtemp()).resolve()
PROJECT_FOLDER = Path(mkdtemp()).resolve()
ape.config.DATA_FOLDER = DATA_FOLDER
ape.config.PROJECT_FOLDER = PROJECT_FOLDER


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


@pytest.fixture(autouse=True)
def data_folder():
    base_path = Path(__file__).parent / "data"
    copy_tree(base_path.as_posix(), DATA_FOLDER.as_posix())
    return DATA_FOLDER


@pytest.fixture
def config():
    return ape.config


@pytest.fixture(autouse=True)
def project(data_folder, config):
    _ = data_folder  # Ensure happens first.
    project_source_dir = Path(__file__).parent
    project_dest_dir = PROJECT_FOLDER / project_source_dir.name

    # Delete build / .cache that may exist pre-copy
    project_path = Path(__file__).parent
    for path in (
        project_path,
        project_path / "BrownieProject",
        project_path / "BrownieStyleDependency",
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
        if project.local_project._cache_folder.is_dir():
            shutil.rmtree(project.local_project._cache_folder)


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[Extension.SOL.value]


@pytest.fixture
def vyper_source_path(project):
    return project.contracts_folder / "RandomVyperFile.vy"


@pytest.fixture
def account():
    return ape.accounts.test_accounts[0]


@pytest.fixture
def owner():
    return ape.accounts.test_accounts[1]


@pytest.fixture
def not_owner():
    return ape.accounts.test_accounts[2]


@pytest.fixture
def connection():
    with ape.networks.ethereum.local.use_provider("test"):
        yield
