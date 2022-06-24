import shutil
from pathlib import Path


def clean():
    """
    Delete all ``.cache/ and ``.build/`` folders in the project and local
    dependencies.
    """
    project_path = Path(__file__).parent.parent
    for path in (
        project_path,
        project_path / "BrownieProject",
        project_path / "Dependency",
        project_path / "DependencyOfDependency",
        project_path / "ProjectWithinProject",
        project_path / "VersionSpecifiedInConfig",
    ):
        for cache in (path / ".build", path / "contracts" / ".cache"):
            if cache.is_dir():
                shutil.rmtree(cache)


def main():
    clean()
