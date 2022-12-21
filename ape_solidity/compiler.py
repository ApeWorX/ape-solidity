import json
import os
import re
from copy import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

import solcx  # type: ignore
from ape.api import CompilerAPI, PluginConfig
from ape.exceptions import CompilerError
from ape.logging import logger
from ape.types import ContractType
from ape.utils import cached_property, get_relative_path
from requests.exceptions import ConnectionError
from semantic_version import NpmSpec, Version  # type: ignore
from solcx.exceptions import SolcError  # type: ignore
from solcx.install import get_executable  # type: ignore

from ape_solidity._utils import (
    Extension,
    ImportRemapping,
    ImportRemappingBuilder,
    get_import_lines,
    get_pragma_spec,
    get_version_with_commit_hash,
    load_dict,
    verify_contract_filepaths,
)
from ape_solidity.exceptions import IncorrectMappingFormatError


class SolidityConfig(PluginConfig):
    # Configure re-mappings using a `=` separated-str,
    # e.g. '@import_name=path/to/dependency'
    import_remapping: List[str] = []
    optimize: bool = True
    version: Optional[str] = None
    evm_version: Optional[str] = None


class SolidityCompiler(CompilerAPI):
    _import_remapping_hash: Optional[int] = None
    _cached_project_path: Optional[Path] = None
    _cached_import_map: Dict[str, str] = {}

    @property
    def name(self) -> str:
        return "solidity"

    @property
    def config(self) -> SolidityConfig:
        return cast(SolidityConfig, self.config_manager.get_config(self.name))

    @cached_property
    def available_versions(self) -> List[Version]:
        # NOTE: Package version should already be included in available versions
        try:
            return solcx.get_installable_solc_versions()
        except ConnectionError:
            # Compiling offline
            logger.warning("Internet connection required to fetch installable Solidity versions.")
            return []

    @property
    def installed_versions(self) -> List[Version]:
        return solcx.get_installed_solc_versions()

    def get_versions(self, all_paths: List[Path]) -> Set[str]:
        versions = set()
        for path in all_paths:
            # Make sure we have the compiler available to compile this
            version_spec = get_pragma_spec(path)
            if version_spec:
                versions.add(str(version_spec.select(self.available_versions)))

        return versions

    def get_import_remapping(self, base_path: Optional[Path] = None) -> Dict[str, str]:
        """
        Specify the remapping using a ``=`` separated str
        e.g. ``'@import_name=path/to/dependency'``.
        """
        base_path = base_path or self.project_manager.contracts_folder
        remappings = self.config.import_remapping
        if not remappings:
            return {}

        elif not isinstance(remappings, (list, tuple)) or not isinstance(remappings[0], str):
            raise IncorrectMappingFormatError()

        contracts_cache = base_path / ".cache"
        builder = ImportRemappingBuilder(contracts_cache)

        # Convert to tuple for hashing, check if there's been a change
        remappings_tuple = tuple(remappings)

        if all(
            (
                self._import_remapping_hash,
                self._import_remapping_hash == hash(remappings_tuple),
                contracts_cache.is_dir(),
            )
        ):
            return self._cached_import_map

        packages_cache = self.config_manager.packages_folder

        # Download dependencies for first time.
        # This only happens if calling this method before compiling in ape core.
        _ = self.project_manager.dependencies

        for item in remappings:
            remapping_obj = ImportRemapping(entry=item, packages_cache=packages_cache)
            builder.add_entry(remapping_obj)
            package_id = remapping_obj.package_id
            data_folder_cache = packages_cache / package_id

            # Re-build a downloaded dependency manifest into the .cache directory for imports.
            sub_contracts_cache = contracts_cache / package_id
            if not sub_contracts_cache.is_dir() or not list(sub_contracts_cache.iterdir()):
                cached_manifest_file = data_folder_cache / f"{remapping_obj.name}.json"
                if not cached_manifest_file.is_file():
                    logger.debug(f"Unable to find dependency '{package_id}'.")

                else:
                    manifest = json.loads(cached_manifest_file.read_text())
                    self._add_dependencies(manifest, sub_contracts_cache, builder)

        # Update cache and hash
        self._cached_project_path = self.project_manager.path
        self._cached_import_map = builder.import_map
        self._import_remapping_hash = hash(remappings_tuple)
        return builder.import_map

    def _add_dependencies(
        self, manifest_data: Dict, cache_dir: Path, builder: ImportRemappingBuilder
    ):
        if not cache_dir.is_dir():
            cache_dir.mkdir(parents=True)

        sources = manifest_data.get("sources") or {}

        for source_name, src in sources.items():
            cached_source = cache_dir / source_name

            if cached_source.is_file():
                # Source already present
                continue

            # NOTE: Cached source may included sub-directories.
            cached_source.parent.mkdir(parents=True, exist_ok=True)
            if "content" in src:
                cached_source.touch()
                cached_source.write_text(src.get("content") or "")

        # Add dependency remapping that may be needed.
        for compiler in manifest_data.get("compilers") or []:
            settings = compiler.get("settings") or {}
            settings_map = settings.get("remappings") or []
            remapping_list = [
                ImportRemapping(entry=x, packages_cache=self.config_manager.packages_folder)
                for x in settings_map
            ]
            for remapping in remapping_list:
                builder.add_entry(remapping)

        # Locate the dependency in the .ape packages cache
        dependencies = manifest_data.get("buildDependencies") or {}
        packages_dir = self.config_manager.packages_folder
        for dependency_package_name, uri in dependencies.items():
            uri_str = str(uri)
            if "://" in uri_str:
                uri_str = "://".join(uri_str.split("://")[1:])  # strip off scheme

            dependency_name = str(dependency_package_name)
            if str(self.config_manager.packages_folder) in uri_str:
                # Using a local dependency
                version = "local"
            else:
                # Check for GitHub-style dependency
                version_match = re.match(r".*/releases/tag/(v?[\d|.]+)", str(uri_str))
                if version_match:
                    version = version_match.groups()[0]
                    if not version.startswith("v"):
                        version = f"v{version}"
                else:
                    raise CompilerError(f"Unable to discern dependency type '{uri_str}'.")

            # Find matching package
            for package in packages_dir.iterdir():
                if package.name.replace("_", "-").lower() == dependency_name:
                    dependency_name = str(package.name)
                    break

            dependency_path = (
                self.config_manager.packages_folder
                / Path(dependency_name)
                / version
                / f"{dependency_name}.json"
            )
            if dependency_path.is_file():
                raw_manifest = json.loads(dependency_path.read_text())
                dep_id = Path(dependency_name) / version
                if dep_id not in builder.dependencies_added:
                    builder.dependencies_added.add(dep_id)
                    self._add_dependencies(
                        raw_manifest,
                        builder.contracts_cache / dep_id,
                        builder,
                    )

    def get_compiler_settings(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> Dict[Version, Dict]:

        # Currently needed because of a bug in Ape core 0.5.5.
        only_files = []
        for path in contract_filepaths:
            if path.is_dir():
                logger.error(
                    f"Unable to get compiler settings for directory '{path.name}'. Skipping."
                )
            else:
                only_files.append(path)

        base_path = base_path or self.config_manager.contracts_folder
        files_by_solc_version = self.get_version_map(only_files, base_path=base_path)
        if not files_by_solc_version:
            return {}

        compiler_args: Dict = self._get_compiler_arguments(files_by_solc_version, base_path)
        settings: Dict = {}
        for solc_version, arguments in compiler_args.items():
            sources = files_by_solc_version[solc_version]
            version_settings: Dict[str, Union[Any, List[Any]]] = {
                "optimizer": {"enabled": arguments.get("optimize", False), "runs": 200},
                "outputSelection": {
                    p.name: {p.stem: arguments.get("output_values", [])} for p in sources
                },
            }
            remappings: List[str] = arguments.get("import_remappings", [])
            if remappings:
                # Standard JSON input requires remappings to be sorted.
                version_settings["remappings"] = sorted(list(remappings))

            evm_version = arguments.get("evm_version")
            if evm_version:
                version_settings["evmVersion"] = evm_version

            settings[solc_version] = version_settings

        return settings

    def _get_compiler_arguments(self, version_map: Dict, base_path: Path) -> Dict[Version, Dict]:
        base_arguments = {
            "output_values": [
                "abi",
                "bin",
                "bin-runtime",
                "devdoc",
                "userdoc",
            ],
            "optimize": self.config.optimize,
            "evm_version": self.config.evm_version,
        }
        arguments_map = {}
        global_import_remapping_list = self.get_import_remapping(base_path=base_path)
        for solc_version, sources in version_map.items():
            cleaned_version = solc_version.truncate()
            import_remapping_list = copy(global_import_remapping_list)
            remapping_kept_list = set()
            if import_remapping_list:
                # Filter out unused import remapping
                resolved_remapped_sources = set(
                    [
                        x
                        for ls in self.get_imports(list(sources), base_path=base_path).values()
                        for x in ls
                        if x.startswith(".cache")
                    ]
                )
                for source in resolved_remapped_sources:
                    parent_key = os.path.sep.join(source.split(os.path.sep)[:3])
                    for k, v in [
                        (k, v) for k, v in import_remapping_list.items() if parent_key in v
                    ]:
                        remapping_kept_list.add(f"{k}={v}")

            arguments = {
                **base_arguments,
                "solc_binary": get_executable(cleaned_version),
                "solc_version": cleaned_version,
            }

            if solc_version >= Version("0.6.9"):
                arguments["base_path"] = base_path
            else:
                # Append base_path to remappings
                parts = [x.split("=") for x in remapping_kept_list]
                remapping_kept_list = {f"{p[0]}={base_path / p[1]}" for p in parts}

            if remapping_kept_list:
                arguments["import_remappings"] = remapping_kept_list

            arguments_map[solc_version] = arguments

        return arguments_map

    def compile(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        base_path = base_path or self.config_manager.contracts_folder
        files_by_solc_version = self.get_version_map(contract_filepaths, base_path=base_path)
        compiler_arguments = self._get_compiler_arguments(
            files_by_solc_version, base_path=base_path
        )
        contract_types: List[ContractType] = []
        solc_versions_by_contract_name: Dict[str, Version] = {}
        for solc_version, arguments in compiler_arguments.items():
            files = list(files_by_solc_version[solc_version])
            if not files:
                continue

            logger.debug(f"Compiling using Solidity compiler '{solc_version}'")

            try:
                output = solcx.compile_files(files, **arguments)
            except SolcError as err:
                raise CompilerError(str(err)) from err

            def parse_contract_name(value: str) -> Tuple[Path, str]:
                parts = value.split(":")
                return Path(parts[0]), parts[1]

            # Filter source files that the user did not ask for, such as
            # imported relative files that are not part of the input.
            input_contract_names: List[str] = []
            for contract_id in output.keys():
                path, name = parse_contract_name(contract_id)
                for input_file_path in contract_filepaths:
                    if str(path) in str(input_file_path):
                        input_contract_names.append(name)

            for contract_name, contract_type in output.items():
                contract_path, contract_name = parse_contract_name(contract_name)
                if contract_name not in input_contract_names:
                    # Only return ContractTypes explicitly asked for.
                    continue

                deployment_bytecode = contract_type["bin"]
                runtime_bytecode = contract_type["bin"]

                # Skip library linking.
                if "__$" in deployment_bytecode or "__$" in runtime_bytecode:
                    logger.warning("Libraries must be deployed and configured separately.")
                    continue

                previously_compiled_version = solc_versions_by_contract_name.get(contract_name)
                if previously_compiled_version:
                    # Don't add previously compiled contract type unless it was compiled
                    # using a greater Solidity version.
                    if previously_compiled_version >= solc_version:
                        continue
                    else:
                        contract_types = [ct for ct in contract_types if ct.name != contract_name]

                contract_type["contractName"] = contract_name
                contract_type["sourceId"] = str(
                    get_relative_path(base_path / contract_path, base_path)
                )
                contract_type["deploymentBytecode"] = {"bytecode": deployment_bytecode}
                contract_type["runtimeBytecode"] = {"bytecode": runtime_bytecode}
                contract_type["userdoc"] = load_dict(contract_type["userdoc"])
                contract_type["devdoc"] = load_dict(contract_type["devdoc"])
                contract_type_obj = ContractType.parse_obj(contract_type)
                contract_types.append(contract_type_obj)
                solc_versions_by_contract_name[contract_name] = solc_version

        return contract_types

    def get_imports(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> Dict[str, List[str]]:
        # NOTE: Process import remappings _before_ getting the full contract set.
        contracts_path = base_path or self.config_manager.contracts_folder
        import_remapping = self.get_import_remapping(base_path=contracts_path)
        contract_filepaths_set = verify_contract_filepaths(contract_filepaths)

        def import_str_to_source_id(_import_str: str, source_path: Path) -> str:
            quote = '"' if '"' in _import_str else "'"

            try:
                end_index = _import_str.index(quote) + 1
            except ValueError as err:
                raise CompilerError(
                    f"Error parsing import statement '{_import_str}' in '{source_path.name}'."
                ) from err

            import_str_prefix = _import_str[end_index:]
            import_str_value = import_str_prefix[: import_str_prefix.index(quote)]
            path = (source_path.parent / import_str_value).resolve()
            source_id_value = str(get_relative_path(path, contracts_path))

            # Convert remapping list back to source
            for key, value in import_remapping.items():
                if key not in source_id_value:
                    continue

                sections = [s for s in source_id_value.split(key) if s]
                depth = len(sections) - 1
                source_id_value = ""

                index = 0
                for section in sections:
                    if index == depth:
                        source_id_value += value
                        source_id_value += section
                    elif index >= depth:
                        source_id_value += section

                    index += 1

                break

            return source_id_value

        imports_dict: Dict[str, List[str]] = {}
        for src_path, import_strs in get_import_lines(contract_filepaths_set).items():
            import_set = set()
            for import_str in import_strs:
                import_item = import_str_to_source_id(import_str, src_path)
                import_set.add(import_item)

            source_id = str(get_relative_path(src_path, contracts_path))
            imports_dict[str(source_id)] = list(import_set)

        return imports_dict

    def get_version_map(
        self,
        contract_filepaths: Union[Path, List[Path]],
        base_path: Optional[Path] = None,
    ) -> Dict[Version, Set[Path]]:
        #  Ensure `.cache` folder is built before getting version map.
        _ = self.get_import_remapping(base_path=base_path)

        if not isinstance(contract_filepaths, (list, tuple)):
            contract_filepaths = [contract_filepaths]

        base_path = base_path or self.project_manager.contracts_folder
        contract_filepaths_set = verify_contract_filepaths(contract_filepaths)
        sources = [
            p
            for p in self.project_manager.source_paths
            if p.is_file() and p.suffix == Extension.SOL.value
        ]
        imports = self.get_imports(sources, base_path)

        # Add imported source files to list of contracts to compile.
        source_paths_to_get = contract_filepaths_set.copy()
        for source_path in contract_filepaths_set:
            imported_source_paths = self._get_imported_source_paths(source_path, base_path, imports)
            for imported_source in imported_source_paths:
                source_paths_to_get.add(imported_source)

        # Use specified version if given one
        if self.config.version is not None:
            specified_version = Version(self.config.version)
            if specified_version not in self.installed_versions:
                solcx.install_solc(specified_version)

            specified_version_with_commit_hash = get_version_with_commit_hash(specified_version)
            return {specified_version_with_commit_hash: source_paths_to_get}

        # else: find best version per source file

        # Build map of pragma-specs.
        source_by_pragma_spec = {p: self._get_pragma_spec(p) for p in source_paths_to_get}

        # If no Solidity version has been installed previously while fetching the
        # contract version pragma, we must install a compiler, so choose the latest
        if not self.installed_versions and not any(source_by_pragma_spec.values()):
            solcx.install_solc(max(self.available_versions), show_progress=False)

        # Adjust best-versions based on imports.
        files_by_solc_version: Dict[Version, Set[Path]] = {}
        for source_file_path in source_paths_to_get:
            solc_version = self._get_best_version(source_file_path, source_by_pragma_spec)
            imported_source_paths = self._get_imported_source_paths(
                source_file_path, base_path, imports
            )

            for imported_source_path in imported_source_paths:
                imported_pragma_spec = source_by_pragma_spec[imported_source_path]
                imported_version = self._get_best_version(
                    imported_source_path, source_by_pragma_spec
                )

                if imported_pragma_spec is not None and (
                    imported_pragma_spec.expression.startswith("=")
                    or imported_pragma_spec.expression[0].isdigit()
                ):
                    # Have to use this version.
                    solc_version = imported_version
                    break

                elif imported_version < solc_version:
                    # If we get here, the highest version of an import is lower than the reference.
                    solc_version = imported_version

            if solc_version not in files_by_solc_version:
                files_by_solc_version[solc_version] = set()

            for path in (source_file_path, *imported_source_paths):
                files_by_solc_version[solc_version].add(path)

        # If being used in another version AND no imports in this version require it,
        # remove it from this version.
        for solc_version, files in files_by_solc_version.copy().items():
            for file in files.copy():
                used_in_other_version = any(
                    [file in ls for v, ls in files_by_solc_version.items() if v != solc_version]
                )
                if not used_in_other_version:
                    continue

                other_files = [f for f in files_by_solc_version[solc_version] if f != file]
                used_in_imports = False
                for other_file in other_files:
                    source_id = str(get_relative_path(other_file, base_path))
                    import_paths = [base_path / i for i in imports.get(source_id, []) if i]
                    if file in import_paths:
                        used_in_imports = True
                        break

                if not used_in_imports:
                    files_by_solc_version[solc_version].remove(file)
                    if not files_by_solc_version[solc_version]:
                        del files_by_solc_version[solc_version]

        return {get_version_with_commit_hash(v): ls for v, ls in files_by_solc_version.items()}

    def _get_imported_source_paths(
        self,
        path: Path,
        base_path: Path,
        imports: Dict,
        source_ids_checked: Optional[List[str]] = None,
    ) -> Set[Path]:
        source_ids_checked = source_ids_checked or []
        source_identifier = str(get_relative_path(path, base_path))
        if source_identifier in source_ids_checked:
            # Already got this source's imports
            return set()

        source_ids_checked.append(source_identifier)
        import_file_paths = [base_path / i for i in imports.get(source_identifier, []) if i]
        return_set = {i for i in import_file_paths}
        for import_path in import_file_paths:
            indirect_imports = self._get_imported_source_paths(
                import_path, base_path, imports, source_ids_checked=source_ids_checked
            )
            for indirect_import in indirect_imports:
                return_set.add(indirect_import)

        return return_set

    def _get_pragma_spec(self, path: Path) -> Optional[NpmSpec]:
        pragma_spec = get_pragma_spec(path)
        if not pragma_spec:
            return None

        # Check if we need to install specified compiler version
        if pragma_spec is pragma_spec.select(self.installed_versions):
            return pragma_spec

        compiler_version = pragma_spec.select(self.available_versions)
        if compiler_version:
            solcx.install_solc(compiler_version, show_progress=False)
        else:
            raise CompilerError(f"Solidity version specification '{pragma_spec}' could not be met.")

        return pragma_spec

    def _get_best_version(self, path: Path, source_by_pragma_spec: Dict) -> Version:
        pragma_spec = source_by_pragma_spec[path]
        return (
            pragma_spec.select(self.installed_versions)
            if pragma_spec
            else max(self.installed_versions)
        )
