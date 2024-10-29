import os
from collections.abc import Iterable
from functools import singledispatchmethod
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ape.exceptions import CompilerError, ProjectError
from ape.utils.basemodel import BaseModel, ManagerAccessMixin, classproperty
from ape.utils.os import get_relative_path
from pydantic import field_serializer

from ape_solidity._utils import get_single_import_lines

if TYPE_CHECKING:
    from ape.managers.project import ProjectManager

    from ape_solidity.compiler import SolidityCompiler


class ApeSolidityMixin(ManagerAccessMixin):
    @classproperty
    def solidity(cls) -> "SolidityCompiler":
        return cls.compiler_manager.solidity


class ApeSolidityModel(BaseModel, ApeSolidityMixin):
    pass


def _create_import_remapping(project: "ProjectManager") -> dict[str, str]:
    prefix = f"{get_relative_path(project.contracts_folder, project.path)}"
    specified = project.dependencies.install()

    # Ensure .cache folder is ready-to-go.
    cache_folder = project.contracts_folder / ".cache"
    cache_folder.mkdir(exist_ok=True, parents=True)

    # Start with explicitly configured remappings.
    cfg_remappings: dict[str, str] = {
        m.key: m.value for m in project.config.solidity.import_remapping
    }
    key_map: dict[str, str] = {}

    def get_cache_id(dep) -> str:
        return os.path.sep.join((prefix, ".cache", dep.name, dep.version))

    def unpack(dep):
        # Ensure the dependency is installed.
        try:
            dep.project
        except ProjectError:
            # Try to compile anyway.
            # Let the compiler fail on its own.
            return

        for unpacked_dep in dep.unpack(project.contracts_folder / ".cache"):
            main_key = key_map.get(unpacked_dep.name)
            keys = (main_key,) if main_key else (f"@{unpacked_dep.name}", unpacked_dep.name)
            for _key in keys:
                if _key not in remapping:
                    remapping[_key] = get_cache_id(unpacked_dep)
                # else, was specified or configured more appropriately.

    remapping: dict[str, str] = {}
    for key, value in cfg_remappings.items():
        # Check if legacy-style and still accept it.
        parts = value.split(os.path.sep)
        name = parts[0]
        _version = None
        if len(parts) > 2:
            # Clearly, not pointing at a dependency.
            remapping[key] = value
            continue

        elif len(parts) == 2:
            _version = parts[1]

        if _version is None:
            matching_deps = [d for d in project.dependencies.installed if d.name == name]
            if len(matching_deps) == 1:
                _version = matching_deps[0].version
            else:
                # Not obvious if it is pointing at one of these dependencies.
                remapping[key] = value
                continue

        # Dependency found. Map to it using the provider key.
        dependency = project.dependencies.get_dependency(name, _version)
        key_map[dependency.name] = key
        unpack(dependency)

    # Add auto-remapped dependencies.
    # (Meaning, the dependencies are specified but their remappings
    # are not, so we auto-generate default ones).
    for dependency in specified:
        unpack(dependency)

    return remapping


class ImportRemappingCache(ApeSolidityMixin):
    def __init__(self):
        # Cache project paths to import remapping.
        self._cache: dict[str, dict[str, str]] = {}

    def __getitem__(self, project: "ProjectManager") -> dict[str, str]:
        if remapping := self._cache.get(f"{project.path}"):
            return remapping

        return self.add_project(project)

    def add_project(self, project: "ProjectManager") -> dict[str, str]:
        remapping = _create_import_remapping(project)
        return self.add(project, remapping)

    def add(self, project: "ProjectManager", remapping: dict[str, str]):
        self._cache[f"{project.path}"] = remapping
        return remapping

    @classmethod
    def get_import_remapping(cls, project: "ProjectManager"):
        return _create_import_remapping(project)


class ImportStatementMetadata(ApeSolidityModel):
    quote_char: str
    sep_char: str
    raw_value: str

    # Only set when remappings are involved.
    import_remap_key: Optional[str] = None
    import_remap_value: Optional[str] = None

    # Only set when import-remapping resolves to a dependency.
    dependency_name: Optional[str] = None
    dependency_version: Optional[str] = None

    # Set once a source-file is located. This happens _after_
    # dependency related properties.
    source_id: Optional[str] = None
    path: Optional[Path] = None

    @property
    def value(self) -> str:
        if self.import_remap_key and self.import_remap_value:
            return self.raw_value.replace(self.import_remap_key, self.import_remap_value)

        return self.raw_value

    @property
    def dependency(self) -> Optional["ProjectManager"]:
        if name := self.dependency_name:
            if version := self.dependency_version:
                return self.local_project.dependencies[name][version]

        return None

    @classmethod
    def parse_line(
        cls,
        value: str,
        reference: Path,
        project: "ProjectManager",
        dependency: Optional["ProjectManager"] = None,
    ) -> "ImportStatementMetadata":
        quote = '"' if '"' in value else "'"
        sep = "\\" if "\\" in value else "/"

        try:
            end_index = value.index(quote) + 1
        except ValueError as err:
            raise CompilerError(
                f"Error parsing import statement '{value}' in '{reference.name}'."
            ) from err

        import_str_prefix = value[end_index:]
        value = import_str_prefix[: import_str_prefix.index(quote)]
        result = cls(quote_char=quote, sep_char=sep, raw_value=value)
        result._resolve_source(reference, project, dependency=dependency)
        return result

    def __repr__(self) -> str:
        return self.raw_value

    def __hash__(self) -> int:
        path = self.path or Path(self.raw_value)
        return hash(path)

    def _resolve_source(
        self,
        reference: Path,
        project: "ProjectManager",
        dependency: Optional["ProjectManager"] = None,
    ):
        if not self._resolve_dependency(project, dependency=dependency):
            # Handle non-dependencies.
            self._resolve_import_remapping(project)
            self._resolve_path(reference, project)

    def _resolve_import_remapping(self, project: "ProjectManager"):
        if self.value.startswith("."):
            # Relative paths should not use import-remappings.
            return

        import_remapping = self.solidity._import_remapping_cache[project]

        # Get all matches.
        valid_matches: list[tuple[str, str]] = []
        for check_remap_key, check_remap_value in import_remapping.items():
            if check_remap_key not in self.value:
                continue

            valid_matches.append((check_remap_key, check_remap_value))

        if valid_matches:
            self.import_remap_key, self.import_remap_value = max(
                valid_matches, key=lambda x: len(x[0])
            )

    def _resolve_path(self, reference: Path, project: "ProjectManager"):
        base_path = None
        if self.value.startswith("."):
            base_path = reference.parent
        elif (project.path / self.value).is_file():
            base_path = project.path
        elif (project.contracts_folder / self.value).is_file():
            base_path = project.contracts_folder
        elif self.import_remap_key is not None and self.import_remap_key.startswith("@"):
            nm = self.import_remap_key[1:]
            for cfg_dep in project.config.dependencies:
                if (
                    cfg_dep.get("name") == nm
                    and "project" in cfg_dep
                    and (Path(cfg_dep["project"]) / self.value).is_file()
                ):
                    base_path = Path(cfg_dep["project"])

        if base := base_path:
            self.path = (base / self.value).resolve().absolute()
            self.source_id = f"{get_relative_path(self.path, project.path)}"

    def _resolve_dependency(
        self, project: "ProjectManager", dependency: Optional["ProjectManager"] = None
    ) -> bool:
        config_project = dependency or project
        # NOTE: Dependency is set if we are getting dependencies of dependencies.
        #   It is tricky because we still need the base (local) project along
        #   with project defining this dependency, for separate pieces of data.
        #   (need base project for relative .cache folder location and need dependency
        #   for configuration).
        import_remapping = self.solidity._import_remapping_cache[config_project]
        parts = self.value.split(self.sep_char)
        pot_dep_names = {parts[0], parts[0].lstrip("@"), f"@{parts[0].lstrip('@')}"}
        matches = []
        for nm in pot_dep_names:
            if nm not in import_remapping or nm not in self.value:
                continue

            matches.append(nm)

        if not matches:
            return False

        name = max(matches, key=lambda x: len(x))
        resolved_import = import_remapping[name]
        resolved_path_parts = resolved_import.split(self.sep_char)
        if ".cache" not in resolved_path_parts:
            # Not a dependency
            return False

        cache_index = resolved_path_parts.index(".cache")
        nm_index = cache_index + 1
        version_index = nm_index + 1

        if version_index >= len(resolved_path_parts):
            # Not sure.
            return False

        cache_folder_name = resolved_path_parts[nm_index]
        cache_folder_version = resolved_path_parts[version_index]
        dependency_project = config_project.dependencies[cache_folder_name][cache_folder_version]
        if not dependency_project:
            return False

        self.import_remap_key = name
        self.import_remap_value = resolved_import
        self.dependency_name = dependency_project.name
        self.dependency_version = dependency_project.version
        path = project.path / self.value
        if path.is_file():
            self.source_id = self.value
            self.path = project.path / self.source_id
        else:
            contracts_dir = dependency_project.contracts_folder
            dep_path = dependency_project.path
            contracts_folder_name = f"{get_relative_path(contracts_dir, dep_path)}"
            prefix_pth = dep_path / contracts_folder_name
            start_idx = version_index + 1
            suffix = self.sep_char.join(self.value.split(self.sep_char)[start_idx:])
            new_path = prefix_pth / suffix
            if not new_path.is_file():
                # No further resolution required (but still is a resolved dependency).
                return True

            adjusted_base_path = (
                f"{self.sep_char.join(resolved_path_parts[:4])}"
                f"{self.sep_char}{contracts_folder_name}"
            )
            adjusted_src_id = f"{adjusted_base_path}{self.sep_char}{suffix}"

            # Also, correct import remappings now, since it didn't work.
            if key := self.import_remap_key:
                # Base path will now included the missing contracts name.
                self.solidity._import_remapping_cache[project][key] = adjusted_base_path
                self.import_remap_value = adjusted_base_path

            self.path = project.path / adjusted_src_id
            self.source_id = adjusted_src_id

        return True


class SourceTree(ApeSolidityModel):
    """
    A model representing a source-tree, meaning given a sequence
    of base-sources, this is the tree of each of them with their imports.
    """

    import_statements: dict[tuple[Path, str], set[ImportStatementMetadata]] = {}
    """
    Mapping of each file to its import-statements.
    """

    @field_serializer("import_statements")
    def _serialize_import_statements(self, statements, info):
        imports_by_source_id = {k[1]: v for k, v in statements.items()}
        keys = sorted(imports_by_source_id.keys())
        return {
            k: sorted(list({i.source_id for i in imports_by_source_id[k] if i.source_id}))
            for k in keys
        }

    @classmethod
    def from_source_files(
        cls,
        source_files: Iterable[Path],
        project: "ProjectManager",
        statements: Optional[dict[tuple[Path, str], set[ImportStatementMetadata]]] = None,
        dependency: Optional["ProjectManager"] = None,
    ) -> "SourceTree":
        statements = statements or {}
        for path in source_files:
            key = (path, f"{get_relative_path(path.absolute(), project.path)}")
            if key in statements:
                # We have already captures all of the imports from the file.
                continue

            statements[key] = set()
            for line in get_single_import_lines(path):
                node_data = ImportStatementMetadata.parse_line(
                    line, path, project, dependency=dependency
                )
                statements[key].add(node_data)
                if sub_path := node_data.path:
                    sub_source_id = f"{get_relative_path(sub_path.absolute(), project.path)}"
                    sub_key = (sub_path, sub_source_id)

                    if sub_key in statements:
                        sub_statements = statements[sub_key]
                    else:
                        sub_tree = SourceTree.from_source_files(
                            (sub_path,),
                            project,
                            statements=statements,
                            dependency=node_data.dependency,
                        )
                        statements = {**statements, **sub_tree.import_statements}
                        sub_statements = statements[sub_key]

                    for sub_stmt in sub_statements:
                        statements[key].add(sub_stmt)

        return cls(import_statements=statements)

    @singledispatchmethod
    def __getitem__(self, key) -> set[ImportStatementMetadata]:
        return set()

    @__getitem__.register
    def __getitem_path(self, path: Path) -> set[ImportStatementMetadata]:
        return next((v for k, v in self.import_statements.items() if k[0] == path), set())

    @__getitem__.register
    def __getitem_str(self, source_id: str) -> set[ImportStatementMetadata]:
        return next((v for k, v in self.import_statements.items() if k[1] == source_id), set())

    @singledispatchmethod
    def __contains__(self, value) -> bool:
        return False

    @__contains__.register
    def __contains_path(self, path: Path) -> bool:
        return any(x[0] == path for x in self.import_statements)

    @__contains__.register
    def __contains_str(self, source_id: str) -> bool:
        return any(x[1] == source_id for x in self.import_statements)

    @__contains__.register
    def __contains_tuple(self, key: tuple) -> bool:
        return key in self.import_statements

    def __repr__(self) -> str:
        key_str = ", ".join([f"{k[1]}={v}" for k, v in self.import_statements.items() if v])
        return f"<SourceTree {key_str}>"

    def get_imported_paths(self, path: Path) -> set[Path]:
        return {x.path for x in self[path] if x.path}

    def get_remappings_used(self, paths: Iterable[Path]) -> dict[str, str]:
        remappings = {}
        for path in paths:
            for metadata in self[path]:
                if not metadata.import_remap_key or not metadata.import_remap_value:
                    continue

                remappings[metadata.import_remap_key] = metadata.import_remap_value

        return remappings
