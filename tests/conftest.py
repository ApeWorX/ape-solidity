import shutil
from pathlib import Path

import ape
import pytest  # type: ignore


@pytest.fixture
def config():
    return ape.config


@pytest.fixture
def project(config):
    base_project_dir = Path(__file__).parent
    with config.using_project(base_project_dir) as project:
        try:
            shutil.rmtree(project._project._cache_folder)
            yield project
        finally:
            shutil.rmtree(project._project._cache_folder)


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[".sol"]
