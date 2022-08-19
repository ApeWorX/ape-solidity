import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union, cast

import solcx  # type: ignore
from ape.api import CompilerAPI, PluginConfig
from ape.exceptions import CompilerError, ConfigError
from ape.logging import logger
from ape.types import ContractType
from ape.utils import cached_property, get_all_files_in_directory, get_relative_path
from ethpm_types import PackageManifest
from packaging import version
from packaging.version import Version as _Version
from requests.exceptions import ConnectionError
from semantic_version import NpmSpec, Version  # type: ignore


def get_pragma_spec(source_file_path: Path) -> Optional[NpmSpec]:
    """
    Extracts pragma information from Solidity source code.
    Args:
        source_file_path: Solidity source code
    Returns: NpmSpec object or None, if no valid pragma is found
    """
    if not source_file_path.is_file():
        return None

    source = source_file_path.read_text()
    pragma_match = next(re.finditer(r"(?:\n|^)\s*pragma\s*solidity\s*([^;\n]*)", source), None)
    if pragma_match is None:
        return None  # Try compiling with latest

    # The following logic handles the case where the user puts a space
    # between the operator and the version number in the pragam string,
    # such as `solidity >= 0.4.19 < 0.7.0`.
    pragma_expression = ""
    pragma_parts = pragma_match.groups()[0].split()
    num_parts = len(pragma_parts)
    for index in range(num_parts):
        pragma_expression += pragma_parts[index]
        if any([c.isdigit() for c in pragma_parts[index]]) and index < num_parts - 1:
            pragma_expression += " "

    try:
        return NpmSpec(pragma_expression)

    except ValueError as err:
        logger.error(str(err))
        return None


class SolidityConfig(PluginConfig):
    # Configure re-mappings using a `=` separated-str,
    # e.g. '@import_name=path/to/dependency'
    import_remapping: List[str] = []
    optimize: bool = True
    version: Optional[str] = None


class IncorrectMappingFormatError(ConfigError):
    def __init__(self):
        super().__init__(
            "Incorrectly formatted 'solidity.remapping' config property. "
            "Expected '@value_1=value2'."
        )


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

    def get_versions(self, all_paths: List[Path]) -> Set[str]:
        versions = set()
        for path in all_paths:
            # Make sure we have the compiler available to compile this
            version_spec = get_pragma_spec(path)
            if version_spec:
                versions.add(str(version_spec.select(self.available_versions)))

        return versions

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

    def get_import_remapping(self, base_path: Optional[Path] = None) -> Dict[str, str]:
        """
        Specify the remapping using a ``=`` separated str
        e.g. ``'@import_name=path/to/dependency'``.
        """
        import_map: Dict[str, str] = {}
        items = self.config.import_remapping

        if not items:
            return import_map

        if not isinstance(items, (list, tuple)) or not isinstance(items[0], str):
            raise IncorrectMappingFormatError()

        base_path = base_path or self.config_manager.contracts_folder
        contracts_cache = base_path / ".cache"

        # Convert to tuple for hashing, check if there's been a change
        items_tuple = tuple(items)
        if all(
            (
                self._cached_project_path,
                self._import_remapping_hash,
                self._cached_project_path == self.project_manager.path,
                self._import_remapping_hash == hash(items_tuple),
                contracts_cache.exists(),
            )
        ):
            return self._cached_import_map

        packages_cache = self.config_manager.packages_folder

        # Download dependencies for first time.
        # This only happens if calling this method before compiling in ape core.
        _ = self.project_manager.dependencies

        for item in items:
            item_parts = item.split("=")
            if len(item_parts) != 2:
                raise IncorrectMappingFormatError()

            suffix_str = item_parts[1]
            name = suffix_str.split(os.path.sep)[0]
            suffix = Path(suffix_str)

            if isinstance(version.parse(suffix.name), _Version) and not suffix.name.startswith("v"):
                suffix = suffix.parent / f"v{suffix.name}"

            data_folder_cache = packages_cache / suffix

            if len(suffix.parents) == 1 and data_folder_cache.exists():
                # The user did not specify a version_id suffix in their mapping.
                # We try to smartly figure one out, else error.
                version_ids = [d.name for d in data_folder_cache.iterdir()]
                if len(version_ids) == 1:
                    # Use only version ID available.
                    suffix = suffix / version_ids[0]
                    data_folder_cache = packages_cache / suffix
                elif not version_ids:
                    raise CompilerError(f"Missing dependency '{suffix}'.")
                else:
                    options_str = ", ".join(version_ids)
                    raise CompilerError(
                        "Ambiguous version reference. "
                        f"Please set import remapping value to {suffix}/{{version_id}} "
                        f"where 'version_id' is one of '{options_str}'."
                    )

            # Re-build a downloaded dependency manifest into the .cache directory for imports.
            sub_contracts_cache = contracts_cache / suffix
            if not sub_contracts_cache.exists() or not list(sub_contracts_cache.iterdir()):
                cached_manifest_file = data_folder_cache / f"{name}.json"
                if not cached_manifest_file.exists():
                    logger.warning(f"Unable to find dependency '{suffix}'.")

                else:
                    manifest = PackageManifest(**json.loads(cached_manifest_file.read_text()))
                    sub_contracts_cache.mkdir(parents=True)
                    sources = manifest.sources or {}
                    for source_name, source in sources.items():
                        cached_source = sub_contracts_cache / source_name

                        # NOTE: Cached source may included sub-directories.
                        cached_source.parent.mkdir(parents=True, exist_ok=True)

                        if source.content:
                            cached_source.touch()
                            cached_source.write_text(source.content)

            sub_contracts_cache = (
                get_relative_path(sub_contracts_cache, base_path)
                if base_path
                else sub_contracts_cache
            )
            import_map[item_parts[0]] = str(sub_contracts_cache)

        # Update cache and hash
        self._cached_project_path = self.project_manager.path
        self._cached_import_map = import_map
        self._import_remapping_hash = hash(items_tuple)
        return import_map

    def get_compiler_settings(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> Dict[Version, Dict]:
        contracts_path = base_path or self.config_manager.contracts_folder
        files_by_solc_version = self.get_version_map(contract_filepaths, base_path=contracts_path)
        if not files_by_solc_version:
            return {}
        settings_map = self._get_compiler_settings(files_by_solc_version, contracts_path)
        return settings_map

    def _get_compiler_settings(self, version_map: Dict, base_path: Path) -> Dict[Version, Dict]:
        import_remappings = self.get_import_remapping(base_path=base_path)
        base_settings = {
            "output_values": [
                "abi",
                "bin",
                "bin-runtime",
                "devdoc",
                "userdoc",
            ],
            "optimize": self.config.optimize,
        }
        settings_map = {}
        for solc_version in version_map:

            cli_base_path = base_path if solc_version >= Version("0.6.9") else None

            settings = {
                **base_settings,
                "solc_version": solc_version,
                "import_remappings": import_remappings,
            }

            if cli_base_path:
                settings["base_path"] = cli_base_path
            else:
                settings["import_remappings"] = {
                    i: str(base_path / relative_path)
                    for i, relative_path in import_remappings.items()
                }
            settings_map[solc_version] = settings
        return settings_map

    def compile(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        contracts_path = base_path or self.config_manager.contracts_folder
        files_by_solc_version = self.get_version_map(contract_filepaths, base_path=contracts_path)
        settings_map = self._get_compiler_settings(files_by_solc_version, base_path=contracts_path)
        contract_types: List[ContractType] = []
        solc_versions_by_contract_name: Dict[str, Version] = {}
        for solc_version, settings in settings_map.items():
            files = files_by_solc_version[solc_version]
            logger.debug(f"Compiling using Solidity compiler '{solc_version}'")
            output = solcx.compile_files([f for f in files], **settings)

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
                    get_relative_path(contracts_path / contract_path, contracts_path)
                )
                contract_type["deploymentBytecode"] = {"bytecode": deployment_bytecode}
                contract_type["runtimeBytecode"] = {"bytecode": runtime_bytecode}
                contract_type["userdoc"] = _load_dict(contract_type["userdoc"])
                contract_type["devdoc"] = _load_dict(contract_type["devdoc"])
                contract_type_obj = ContractType.parse_obj(contract_type)
                contract_types.append(contract_type_obj)
                solc_versions_by_contract_name[contract_name] = solc_version

        return contract_types

    def get_imports(
        self, contract_filepaths: List[Path], base_path: Optional[Path]
    ) -> Dict[str, List[str]]:
        contracts_path = base_path or self.config_manager.contracts_folder
        import_remapping = self.get_import_remapping(base_path=contracts_path)

        def import_str_to_source_id(_import_str: str, source_path: Path) -> str:
            quote = '"' if '"' in _import_str else "'"
            end_index = _import_str.index(quote) + 1
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

        for filepath in contract_filepaths:
            import_set = set()
            source_lines = filepath.read_text().splitlines()
            line_number = 0
            for ln in source_lines:
                if not ln.startswith("import"):
                    continue

                if ";" in ln:
                    import_str = ln

                else:
                    # Is multi-line.
                    import_str = ln
                    start_index = line_number + 1
                    for next_ln in source_lines[start_index:]:
                        import_str += f" {next_ln.strip()}"

                        if ";" in next_ln:
                            break

                import_item = import_str_to_source_id(import_str, filepath)
                import_set.add(import_item)
                line_number += 1

            source_id = str(get_relative_path(filepath, contracts_path))
            imports_dict[str(source_id)] = list(import_set)

        return imports_dict

    def get_version_map(
        self, contract_filepaths: Union[Path, List[Path]], base_path: Optional[Path] = None
    ) -> Dict[Version, Set[Path]]:
        if not isinstance(contract_filepaths, (list, tuple)):
            contract_filepaths = [contract_filepaths]

        contracts_path = base_path or self.config_manager.contracts_folder
        imports = self.get_imports(get_all_files_in_directory(contracts_path), contracts_path)

        # Add imported source files to list of contracts to compile.
        source_paths_to_compile = {p for p in contract_filepaths}
        for source_path in contract_filepaths:
            imported_source_paths = self._get_imported_source_paths(
                source_path, contracts_path, imports
            )
            for imported_source in imported_source_paths:
                source_paths_to_compile.add(imported_source)

        # Use specified version if given one
        if self.config.version is not None:
            specified_version = Version(self.config.version)
            if specified_version not in self.installed_versions:
                solcx.install_solc(specified_version)

            return {specified_version: source_paths_to_compile}

        # else: find best version per source file

        # Build map of pragma-specs.
        source_by_pragma_spec = {p: self._get_pragma_spec(p) for p in source_paths_to_compile}

        # If no Solidity version has been installed previously while fetching the
        # contract version pragma, we must install a compiler, so choose the latest
        if not self.installed_versions and not any(source_by_pragma_spec.values()):
            solcx.install_solc(max(self.available_versions), show_progress=False)

        # Adjust best-versions based on imports.
        files_by_solc_version: Dict[Version, Set[Path]] = {}
        for source_file_path in source_paths_to_compile:
            solc_version = self._get_best_version(source_file_path, source_by_pragma_spec)
            imported_source_paths = self._get_imported_source_paths(
                source_file_path, contracts_path, imports
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
                    source_id = str(get_relative_path(other_file, contracts_path))
                    import_paths = [contracts_path / i for i in imports.get(source_id, []) if i]
                    if file in import_paths:
                        used_in_imports = True
                        break

                if not used_in_imports:
                    files_by_solc_version[solc_version].remove(file)
                    if not files_by_solc_version[solc_version]:
                        del files_by_solc_version[solc_version]

        return files_by_solc_version

    def _get_imported_source_paths(
        self,
        path: Path,
        contracts_path: Path,
        imports: Dict,
        source_ids_checked: Optional[List[str]] = None,
    ) -> Set[Path]:
        source_ids_checked = source_ids_checked or []
        source_identifier = str(get_relative_path(path, contracts_path))
        if source_identifier in source_ids_checked:
            # Already got this source's imports
            return set()

        source_ids_checked.append(source_identifier)
        import_file_paths = [contracts_path / i for i in imports.get(source_identifier, []) if i]
        return_set = {i for i in import_file_paths}
        for import_path in import_file_paths:
            indirect_imports = self._get_imported_source_paths(
                import_path, contracts_path, imports, source_ids_checked=source_ids_checked
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


def _load_dict(data: Union[str, dict]) -> Dict:
    return data if isinstance(data, dict) else json.loads(data)
