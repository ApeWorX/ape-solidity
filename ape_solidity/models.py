from pathlib import Path
from collections.abc import Sequence

from ape.managers import ProjectManager
from ape.utils import ManagerAccessMixin
from ape.utils.basemodel import classproperty
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ape_solidity.compiler import SolidityCompiler


class ApeSolidityModel(ManagerAccessMixin):
    @classproperty
    def solidity(cls) -> "SolidityCompiler":
        return cls.compiler_manager.solidity


class ImportRemappingCache(ApeSolidityModel):
    def __init__(self):
        # Cache project paths to import remapping.
        self._cache: dict[str, dict[str, str]] = {}

    def __getitem__(self, project: ProjectManager) -> dict[str, str]:
        if remapping := self._cache.get(f"{project.path}"):
            return remapping

        return self.add(project)

    def add(self, project: ProjectManager) -> dict[str, str]:
        remapping = self.solidity.get_import_remapping(project=project)
        self._cache[f"{project.path}"] = remapping
        return remapping


import_remapping_cache = ImportRemappingCache()


class SourceTree(ApeSolidityModel):
    """
    A model representing a source-tree, meaning given a sequence
    of base-sources, this is the tree of each of them with their imports.
    """

    @classmethod
    def from_source_files(
        cls, source_files: Sequence[Path], project: ProjectManager
    ) -> "SourceTree":
        pass
