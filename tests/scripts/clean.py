import shutil
from pathlib import Path


def clean():
    """
    Delete all ``.cache/ and ``.build/`` folders in the project and local
    dependencies.
    """
    project_path = Path(__file__).parent.parent
    dependency_path = project_path / "Dependency"
    dependency_of_dependency = project_path / "DependencyOfDependency"
    project_within_a_project_path = project_path / "ProjectWithinProject"
    brownie_project = project_path / "BrownieProject"
    for path in (
        project_path,
        dependency_path,
        dependency_of_dependency,
        project_within_a_project_path,
        brownie_project,
    ):
        for cache in (path / ".build", path / "contracts" / ".cache"):
            if cache.is_dir():
                shutil.rmtree(cache)


def main():
    clean()
