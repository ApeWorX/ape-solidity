import shutil
from pathlib import Path

import ape
import pytest

DEPENDENCY_0_NAME = "__test_dependency__"
DEPENDENCY_1_NAME = "__test_remapping__"


@pytest.fixture(autouse=True, scope="session")
def clean_dependencies():
    dep_1 = ape.config.packages_folder / DEPENDENCY_0_NAME
    dep_2 = ape.config.packages_folder / DEPENDENCY_1_NAME

    def _clean():
        for _path in (dep_1, dep_2):
            if _path.is_dir():
                shutil.rmtree(_path)

    _clean()
    yield
    _clean()


@pytest.fixture
def config():
    return ape.config


@pytest.fixture
def project(config):
    base_project_dir = Path(__file__).parent
    contract_cache = base_project_dir / "contracts" / ".cache"
    build_dir = base_project_dir / ".build"

    def _clean():
        for _path in (contract_cache, build_dir):
            if _path.is_dir():
                shutil.rmtree(str(_path))

    _clean()
    with config.using_project(base_project_dir) as project:
        yield project
        _clean()


@pytest.fixture(scope="session")
def compiler():
    return ape.compilers.registered_compilers[".sol"]
