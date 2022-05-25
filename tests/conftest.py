import shutil
from pathlib import Path
from tempfile import mkdtemp

import ape
import pytest

DEPENDENCY_0_NAME = "__test_dependency__"
DEPENDENCY_1_NAME = "__test_remapping__"


# NOTE: Ensure that we don't use local paths for these
ape.config.DATA_FOLDER = Path(mkdtemp()).resolve()
ape.config.PROJECT_FOLDER = Path(mkdtemp()).resolve()


@pytest.fixture
def config():
    return ape.config


@pytest.fixture
def project(config):
    project_dir = Path(__file__).parent
    contract_cache = project_dir / "contracts" / ".cache"
    build_dir = project_dir / ".build"

    def _clean():
        for _path in (contract_cache, build_dir):
            if _path.is_dir():
                shutil.rmtree(str(_path))

    _clean()
    with config.using_project(project_dir) as project:
        yield project
        _clean()


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[".sol"]
