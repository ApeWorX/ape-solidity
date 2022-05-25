import shutil
from pathlib import Path

import ape
import pytest  # type: ignore


@pytest.fixture
def project():
    base_project_dir = Path(__file__).parent

    project = ape.Project(base_project_dir)
    project.config_manager.PROJECT_FOLDER = base_project_dir
    project.config_manager.contracts_folder = base_project_dir / "contracts"
    try:
        shutil.rmtree(project._project._cache_folder)
        yield project
    finally:
        shutil.rmtree(project._project._cache_folder)


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[".sol"]


@pytest.fixture
def config():
    return ape.config
