from distutils.dir_util import copy_tree
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
    project_source_dir = Path(__file__).parent
    project_dest_dir = config.PROJECT_FOLDER / project_source_dir.name
    copy_tree(project_source_dir.as_posix(), project_dest_dir.as_posix())
    with config.using_project(project_dest_dir) as project:
        yield project


@pytest.fixture
def compiler():
    return ape.compilers.registered_compilers[".sol"]
