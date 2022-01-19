import shutil
from pathlib import Path

import pytest  # type: ignore
from ape import Project


@pytest.fixture
def project():
    base_project_dir = Path(__file__).parent
    project = Project(base_project_dir)
    project.config.PROJECT_FOLDER = base_project_dir
    try:
        shutil.rmtree(project._cache_folder)
        yield project
    finally:
        shutil.rmtree(project._cache_folder)
