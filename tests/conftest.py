import shutil
from pathlib import Path

import pytest  # type: ignore
from ape import Project


@pytest.fixture
def project():
    project = Project(Path(__file__).parent)
    try:
        shutil.rmtree(project._cache_folder)
        yield project
    finally:
        shutil.rmtree(project._cache_folder)
