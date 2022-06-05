import shutil
from distutils.dir_util import copy_tree
from pathlib import Path
from tempfile import mkdtemp

import ape
import pytest

# NOTE: Ensure that we don't use local paths for these
ape.config.DATA_FOLDER = Path(mkdtemp()).resolve()
ape.config.PROJECT_FOLDER = Path(mkdtemp()).resolve()

READ_ONLY_MAIN_PROJECT_DIR = Path(__file__).parent
READ_ONLY_PROJECTS_DIR = READ_ONLY_MAIN_PROJECT_DIR / "data" / "projects"


@pytest.fixture
def config():
    return ape.config


@pytest.fixture(autouse=True)
def project(config):
    project_dest_dir = config.PROJECT_FOLDER / "tests"
    contracts_folder = READ_ONLY_PROJECTS_DIR / "Project" / "contracts"

    # Delete build / .cache that may exist pre-copy
    sub_project_dirs = [
        p for p in READ_ONLY_PROJECTS_DIR.iterdir() if p.is_dir() and p.name != "Project"
    ]
    contracts_folders = [contracts_folder, *[p / "contracts" for p in sub_project_dirs]]
    dependency_caches = [p / ".cache" for p in contracts_folders if (p / ".cache").is_dir()]
    build_caches = [
        p / ".build"
        for p in [READ_ONLY_MAIN_PROJECT_DIR, *sub_project_dirs]
        if (p / ".build").is_dir()
    ]
    for path in [p for p in [*dependency_caches, *build_caches]]:
        shutil.rmtree(path)

    copy_tree(READ_ONLY_MAIN_PROJECT_DIR.as_posix(), project_dest_dir.as_posix())
    with config.using_project(project_dest_dir) as project:
        yield project
        if project._project._cache_folder.is_dir():
            shutil.rmtree(project._project._cache_folder)


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[".sol"]
