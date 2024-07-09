import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import mkdtemp
from unittest import mock

import ape
import pytest
import solcx
from ape.utils.os import create_tempdir
from click.testing import CliRunner

from ape_solidity._utils import Extension


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


@pytest.fixture
def fake_no_installs(mocker):
    """
    Tricks the tests into thinking there are no installed versions.
    This saves time because it won't actually need to install solc,
    and it should still work.
    """
    patch = mocker.patch("ape_solidity.compiler.get_installed_solc_versions")
    patch.return_value = []
    return patch


@pytest.fixture
def temp_solcx_path(monkeypatch):
    """
    Creates a new, temporary installation path for solcx for a given test.
    """
    with _tmp_solcx_path(monkeypatch) as path:
        yield path


@pytest.fixture(scope="session")
def project(config):
    _ = config  # Ensure temp data folder gets set first.
    root = Path(__file__).parent

    # Delete .build / .cache that may exist pre-copy
    for path in (
        root,
        root / "BrownieProject",
        root / "BrownieStyleDependency",
        root / "Dependency",
        root / "DependencyOfDependency",
        root / "ProjectWithinProject",
        root / "VersionSpecifiedInConfig",
    ):
        for cache in (path / ".build", path / "contracts" / ".cache"):
            if cache.is_dir():
                shutil.rmtree(cache)

    root_project = ape.Project(root)
    with root_project.isolate_in_tempdir() as tmp_project:
        yield tmp_project


@pytest.fixture(scope="session", autouse=True)
def config():
    cfg = ape.config

    # Uncomment to install dependencies in actual data folder.
    # This will save time running tests.
    # project = ape.Project(Path(__file__).parent)
    # project.dependencies.install()

    # Ensure we don't persist any .ape data.
    real_data_folder = cfg.DATA_FOLDER
    with create_tempdir() as path:
        cfg.DATA_FOLDER = path

        # Copy in existing packages to save test time
        # when running locally.
        packages = real_data_folder / "packages"
        packages.mkdir(parents=True, exist_ok=True)
        shutil.copytree(packages, path / "packages", dirs_exist_ok=True)

        yield cfg


@pytest.fixture
def compiler_manager():
    return ape.compilers


@pytest.fixture
def compiler(compiler_manager):
    return compiler_manager.solidity


@pytest.fixture(autouse=True)
def ignore_other_compilers(mocker, compiler_manager, compiler):
    """
    Having ape-vyper installed causes the random Vyper file
    (that exists for testing purposes) to get compiled and
    vyper to get repeatedly installed in a temporary directory.
    Avoid that by tricking Ape into thinking ape-vyper is not
    installed (if it is).
    """
    existing_compilers = compiler_manager.registered_compilers
    ape_pm = compiler_manager.ethpm
    valid_compilers = {
        ext: c for ext, c in existing_compilers.items() if ext in [x.value for x in Extension]
    }
    path = "ape.managers.compilers.CompilerManager.registered_compilers"
    mock_registered_compilers = mocker.patch(path, new_callable=mock.PropertyMock)

    # Only ethpm (.json) and Solidity extensions allowed.
    mock_registered_compilers.return_value = {".json": ape_pm, **valid_compilers}


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
    with ape.networks.ethereum.local.use_provider("test") as provider:
        yield provider


@pytest.fixture
def cli_runner():
    return CliRunner()
