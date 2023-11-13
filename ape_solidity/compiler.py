import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union, cast

from ape.api import CompilerAPI, PluginConfig
from ape.contracts import ContractInstance
from ape.exceptions import CompilerError, ConfigError, ContractLogicError
from ape.logging import logger
from ape.types import AddressType, ContractType
from ape.utils import cached_property, get_relative_path
from eth_utils import add_0x_prefix, is_0x_prefixed
from ethpm_types import ASTNode, HexBytes, PackageManifest
from ethpm_types.ast import ASTClassification
from ethpm_types.source import Content
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkg_resources import get_distribution
from requests.exceptions import ConnectionError
from solcx import (
    compile_source,
    compile_standard,
    get_installable_solc_versions,
    get_installed_solc_versions,
    install_solc,
)
from solcx.exceptions import SolcError
from solcx.install import get_executable

from ape_solidity._utils import (
    OUTPUT_SELECTION,
    Extension,
    ImportRemapping,
    ImportRemappingBuilder,
    add_commit_hash,
    get_import_lines,
    get_pragma_spec_from_path,
    get_pragma_spec_from_str,
    load_dict,
    select_version,
    strip_commit_hash,
    verify_contract_filepaths,
)
from ape_solidity.exceptions import (
    RUNTIME_ERROR_CODE_PREFIX,
    RUNTIME_ERROR_MAP,
    IncorrectMappingFormatError,
    RuntimeErrorType,
    RuntimeErrorUnion,
    SolcInstallError,
)

# Define a regex pattern that matches import statements
# Both single and multi-line imports will be matched
IMPORTS_PATTERN = re.compile(
    r"import\s+((.*?)(?=;)|[\s\S]*?from\s+(.*?)(?=;));\s", flags=re.MULTILINE
)

LICENSES_PATTERN = re.compile(r"(// SPDX-License-Identifier:\s*([^\n]*)\s)")

VERSION_PRAGMA_PATTERN = re.compile(r"pragma solidity[^;]*;")


class SolidityConfig(PluginConfig):
    # Configure re-mappings using a `=` separated-str,
    # e.g. '@import_name=path/to/dependency'
    import_remapping: List[str] = []
    optimize: bool = True
    version: Optional[str] = None
    evm_version: Optional[str] = None
    via_ir: bool = False


class SolidityCompiler(CompilerAPI):
    _import_remapping_hash: Optional[int] = None
    _cached_project_path: Optional[Path] = None
    _cached_import_map: Dict[str, str] = {}
    _libraries: Dict[str, Dict[str, AddressType]] = {}
    _contracts_needing_libraries: Set[Path] = set()

    @property
    def name(self) -> str:
        return "solidity"

    @property
    def config(self) -> SolidityConfig:
        return cast(SolidityConfig, self.config_manager.get_config(self.name))

    @property
    def libraries(self) -> Dict[str, Dict[str, AddressType]]:
        return self._libraries

    @cached_property
    def available_versions(self) -> List[Version]:
        # NOTE: Package version should already be included in available versions
        try:
            return get_installable_solc_versions()
        except ConnectionError:
            # Compiling offline
            logger.warning("Internet connection required to fetch installable Solidity versions.")
            return []

    @property
    def installed_versions(self) -> List[Version]:
        """
        Returns a lis of installed version WITHOUT their
        commit hashes.
        """
        return get_installed_solc_versions()

    @property
    def latest_version(self) -> Optional[Version]:
        """
        Returns the latest version available of ``solc``.
        When unable to retrieve available ``solc`` versions, such as
        times disconnected from the Internet, returns ``None``.
        """
        return _try_max(self.available_versions)

    @property
    def latest_installed_version(self) -> Optional[Version]:
        """
        Returns the highest version of all the installed versions.
        If ``solc`` is not installed at all, returns ``None``.
        """
        return _try_max(self.installed_versions)

    @property
    def _settings_version(self) -> Optional[Version]:
        """
        A helper property that gets, verifies, and installs (if needed)
        the version specified in the settings.
        """
        if not (version := self.settings.version):
            return None

        installed_versions = self.installed_versions
        specified_commit_hash = "+" in version
        base_version = strip_commit_hash(version)
        if base_version not in installed_versions:
            install_solc(base_version, show_progress=True)

        settings_version = add_commit_hash(base_version)
        if specified_commit_hash:
            if settings_version != version:
                raise ConfigError(
                    f"Commit hash from settings version {version} "
                    f"differs from installed: {settings_version}"
                )

        return settings_version

    @cached_property
    def _ape_version(self) -> Version:
        return Version(get_distribution("eth-ape").version.split(".dev")[0].strip())

    def add_library(self, *contracts: ContractInstance):
        """
        Set a library contract type address. This is useful when deploying a library
        in a local network and then adding the address afterward. Now, when
        compiling again, it will use the new address.

        Args:
            contracts (``ContractInstance``): The deployed library contract(s).
        """

        for contract in contracts:
            source_id = contract.contract_type.source_id
            if not source_id:
                raise CompilerError("Missing source ID.")

            name = contract.contract_type.name
            if not name:
                raise CompilerError("Missing contract type name.")

            self._libraries[source_id] = {name: contract.address}

        if self._contracts_needing_libraries:
            # TODO: Only attempt to re-compile contacts that use the given libraries.
            # Attempt to re-compile contracts that needed libraries.
            try:
                self.project_manager.load_contracts(
                    [
                        self.config_manager.contracts_folder / s
                        for s in self._contracts_needing_libraries
                    ],
                    use_cache=False,
                )
            except CompilerError as err:
                logger.error(
                    f"Failed when trying to re-compile contracts requiring libraries.\n{err}"
                )

            self._contracts_needing_libraries = set()

    def get_versions(self, all_paths: List[Path]) -> Set[str]:
        versions = set()
        for path in all_paths:
            # Make sure we have the compiler available to compile this
            if version_spec := get_pragma_spec_from_path(path):
                if selected_version := select_version(version_spec, self.available_versions):
                    versions.add(selected_version.base_version)

        return versions

    def get_import_remapping(self, base_path: Optional[Path] = None) -> Dict[str, str]:
        """
        Specify the remapping using a ``=`` separated str
        e.g. ``'@import_name=path/to/dependency'``.
        """
        base_path = base_path or self.project_manager.contracts_folder
        remappings = self.settings.import_remapping
        if not remappings:
            return {}

        elif not isinstance(remappings, (list, tuple)) or not isinstance(remappings[0], str):
            raise IncorrectMappingFormatError()

        contracts_cache = base_path / ".cache"
        builder = ImportRemappingBuilder(contracts_cache)

        # Convert to tuple for hashing, check if there's been a change
        remappings_tuple = tuple(remappings)
        if (
            self._import_remapping_hash
            and self._import_remapping_hash == hash(remappings_tuple)
            and contracts_cache.is_dir()
        ):
            return self._cached_import_map

        packages_cache = self.config_manager.packages_folder

        # Download dependencies for first time.
        # This only happens if calling this method before compiling in ape core.
        dependencies = self.project_manager.dependencies

        for item in remappings:
            remapping_obj = ImportRemapping(entry=item, packages_cache=packages_cache)
            builder.add_entry(remapping_obj)
            package_id = remapping_obj.package_id

            # Handle missing version ID
            if len(package_id.parts) == 1:
                if package_id.name in dependencies and len(dependencies[package_id.name]) == 1:
                    version_id = next(iter(dependencies[package_id.name]))
                    package_id = package_id / version_id

            data_folder_cache = packages_cache / package_id

            # Re-build a downloaded dependency manifest into the .cache directory for imports.
            sub_contracts_cache = contracts_cache / package_id
            if not sub_contracts_cache.is_dir() or not list(sub_contracts_cache.iterdir()):
                cached_manifest_file = data_folder_cache / f"{remapping_obj.name}.json"
                if not cached_manifest_file.is_file():
                    logger.debug(f"Unable to find dependency '{package_id}'.")

                else:
                    manifest = PackageManifest.parse_file(cached_manifest_file)
                    self._add_dependencies(manifest, sub_contracts_cache, builder)

        # Update cache and hash
        self._cached_project_path = self.project_manager.path
        self._cached_import_map = builder.import_map
        self._import_remapping_hash = hash(remappings_tuple)
        return builder.import_map

    def _add_dependencies(
        self, manifest: PackageManifest, cache_dir: Path, builder: ImportRemappingBuilder
    ):
        if not cache_dir.is_dir():
            cache_dir.mkdir(parents=True)

        sources = manifest.sources or {}

        for source_name, src in sources.items():
            cached_source = cache_dir / source_name

            if cached_source.is_file():
                # Source already present
                continue

            # NOTE: Cached source may included sub-directories.
            cached_source.parent.mkdir(parents=True, exist_ok=True)
            if src.content:
                cached_source.touch()
                cached_source.write_text(str(src.content))

        # Add dependency remapping that may be needed.
        for compiler in manifest.compilers or []:
            settings = compiler.settings or {}
            settings_map = settings.get("remappings") or []
            remapping_list = [
                ImportRemapping(entry=x, packages_cache=self.config_manager.packages_folder)
                for x in settings_map
            ]
            for remapping in remapping_list:
                builder.add_entry(remapping)

        # Locate the dependency in the .ape packages cache
        dependencies = manifest.dependencies or {}
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
                match_checks = (r".*/releases/tag/(v?[\d|.]+)", r".*/tree/(v?[\w|.|\d]+)")
                version = None
                for check in match_checks:
                    version_match = re.match(check, str(uri_str))
                    if version_match:
                        version = version_match.groups()[0]
                        if not version.startswith("v") and version[0].isnumeric():
                            version = f"v{version}"

                        break

            # Find matching package
            for package in packages_dir.iterdir():
                if package.name.replace("_", "-").lower() == dependency_name:
                    dependency_name = str(package.name)
                    break

            dependency_root_path = self.config_manager.packages_folder / Path(dependency_name)

            if version is None:
                version_dirs = [
                    d
                    for d in list(dependency_root_path.iterdir())
                    if d.is_dir() and not d.name.startswith(".")
                ]
                if len(version_dirs) == 1:
                    # Use the only existing version.
                    version = version_dirs[0].name

                elif (dependency_root_path / "local").is_dir():
                    # If not specified, and local exists, use local by default.
                    version = "local"

                else:
                    options = ", ".join([x.name for x in dependency_root_path.iterdir()])
                    raise CompilerError(
                        f"Ambiguous dependency version. "
                        f"Please specify. Available versions: '{options}'."
                    )

            dependency_path = dependency_root_path / version / f"{dependency_name}.json"
            if dependency_path.is_file():
                sub_manifest = PackageManifest.parse_file(dependency_path)
                dep_id = Path(dependency_name) / version
                if dep_id not in builder.dependencies_added:
                    builder.dependencies_added.add(dep_id)
                    self._add_dependencies(
                        sub_manifest,
                        builder.contracts_cache / dep_id,
                        builder,
                    )

    def get_compiler_settings(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> Dict[Version, Dict]:
        base_path = base_path or self.config_manager.contracts_folder
        files_by_solc_version = self.get_version_map(contract_filepaths, base_path=base_path)
        if not files_by_solc_version:
            return {}

        import_remappings = self.get_import_remapping(base_path=base_path)
        settings: Dict = {}
        for solc_version, sources in files_by_solc_version.items():
            version_settings: Dict[str, Union[Any, List[Any]]] = {
                "optimizer": {"enabled": self.settings.optimize, "runs": 200},
                "outputSelection": {
                    str(get_relative_path(p, base_path)): {"*": OUTPUT_SELECTION, "": ["ast"]}
                    for p in sources
                },
            }
            remappings_used = set()
            if import_remappings:
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
                    for k, v in [(k, v) for k, v in import_remappings.items() if parent_key in v]:
                        remappings_used.add(f"{k}={v}")

            if remappings_used:
                # Standard JSON input requires remappings to be sorted.
                version_settings["remappings"] = sorted(list(remappings_used))

            evm_version = self.settings.evm_version
            if evm_version:
                version_settings["evmVersion"] = evm_version

            if solc_version >= Version("0.7.5"):
                version_settings["viaIR"] = self.settings.via_ir

            settings[solc_version] = version_settings

            # TODO: Filter out libraries that are not used for this version.
            libs = self.libraries
            if libs:
                version_settings["libraries"] = libs

        return settings

    def get_standard_input_json(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> Dict[Version, Dict]:
        base_path = base_path or self.config_manager.contracts_folder
        files_by_solc_version = self.get_version_map(contract_filepaths, base_path=base_path)
        settings = self.get_compiler_settings(contract_filepaths, base_path)
        input_jsons = {}
        for solc_version, vers_settings in settings.items():
            if not list(files_by_solc_version[solc_version]):
                continue

            logger.debug(f"Compiling using Solidity compiler '{solc_version}'")
            cleaned_version = Version(solc_version.base_version)
            solc_binary = get_executable(version=cleaned_version)
            arguments = {"solc_binary": solc_binary, "solc_version": cleaned_version}

            if solc_version >= Version("0.6.9"):
                arguments["base_path"] = base_path

            if missing_sources := [
                x for x in vers_settings["outputSelection"] if not (base_path / x).is_file()
            ]:
                missing_src_str = ", ".join(missing_sources)
                raise CompilerError(f"Missing sources: '{missing_src_str}'.")

            sources = {
                x: {"content": (base_path / x).read_text()}
                for x in vers_settings["outputSelection"]
            }
            input_jsons[solc_version] = {
                "sources": sources,
                "settings": vers_settings,
                "language": "Solidity",
            }

        return input_jsons

    def compile(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        base_path = base_path or self.config_manager.contracts_folder
        solc_versions_by_contract_name: Dict[str, Version] = {}
        contract_types: List[ContractType] = []
        input_jsons = self.get_standard_input_json(contract_filepaths, base_path=base_path)
        for solc_version, input_json in input_jsons.items():
            logger.info(f"Compiling using Solidity compiler '{solc_version}'.")
            cleaned_version = Version(solc_version.base_version)
            solc_binary = get_executable(version=cleaned_version)
            arguments: Dict = {"solc_binary": solc_binary, "solc_version": cleaned_version}

            if solc_version >= Version("0.6.9"):
                arguments["base_path"] = base_path

            # Allow empty contracts, like Vyper does.
            arguments["allow_empty"] = True

            try:
                output = compile_standard(input_json, **arguments)
            except SolcError as err:
                raise CompilerError(str(err)) from err

            contracts = output.get("contracts", {})
            input_contract_names: List[str] = []
            for source_id, contracts_out in contracts.items():
                for name, _ in contracts_out.items():
                    # Filter source files that the user did not ask for, such as
                    # imported relative files that are not part of the input.
                    for input_file_path in contract_filepaths:
                        if source_id in str(input_file_path):
                            input_contract_names.append(name)

            def classify_ast(_node: ASTNode):
                if _node.ast_type in ("FunctionDefinition", "FunctionDefinitionNode"):
                    _node.classification = ASTClassification.FUNCTION

                for child in _node.children:
                    classify_ast(child)

            for source_id, contracts_out in contracts.items():
                ast_data = output["sources"][source_id]["ast"]
                ast = ASTNode.parse_obj(ast_data)
                classify_ast(ast)

                for contract_name, ct_data in contracts_out.items():
                    contract_path = base_path / source_id

                    if contract_name not in input_contract_names:
                        # Only return ContractTypes explicitly asked for.
                        continue

                    evm_data = ct_data["evm"]

                    # NOTE: This sounds backwards, but it isn't...
                    #  The "deployment_bytecode" is the same as the "bytecode",
                    #  and the "deployedBytecode" is the same as the "runtimeBytecode".
                    deployment_bytecode = add_0x_prefix(evm_data["bytecode"]["object"])
                    runtime_bytecode = add_0x_prefix(evm_data["deployedBytecode"]["object"])

                    # Skip library linking.
                    if "__$" in deployment_bytecode or "__$" in runtime_bytecode:
                        logger.warning(
                            f"Unable to compile {contract_name} - missing libraries. "
                            f"Call `{self.add_library.__name__}` with the necessary libraries"
                        )
                        self._contracts_needing_libraries.add(contract_path)
                        continue

                    previously_compiled_version = solc_versions_by_contract_name.get(contract_name)
                    if previously_compiled_version:
                        # Don't add previously compiled contract type unless it was compiled
                        # using a greater Solidity version.
                        if previously_compiled_version >= solc_version:
                            continue
                        else:
                            contract_types = [
                                ct for ct in contract_types if ct.name != contract_name
                            ]

                    ct_data["contractName"] = contract_name
                    ct_data["sourceId"] = str(
                        get_relative_path(base_path / contract_path, base_path)
                    )
                    ct_data["deploymentBytecode"] = {"bytecode": deployment_bytecode}
                    ct_data["runtimeBytecode"] = {"bytecode": runtime_bytecode}
                    ct_data["userdoc"] = load_dict(ct_data["userdoc"])
                    ct_data["devdoc"] = load_dict(ct_data["devdoc"])
                    ct_data["sourcemap"] = evm_data["bytecode"]["sourceMap"]
                    ct_data["ast"] = ast
                    contract_type = ContractType.parse_obj(ct_data)
                    contract_types.append(contract_type)
                    solc_versions_by_contract_name[contract_name] = solc_version

        return contract_types

    def compile_code(
        self,
        code: str,
        base_path: Optional[Path] = None,
        **kwargs,
    ) -> ContractType:
        if settings_version := self._settings_version:
            version = settings_version

        elif pragma := self._get_pramga_spec_from_str(code):
            if selected_version := select_version(pragma, self.installed_versions):
                version = selected_version
            else:
                if selected_version := select_version(pragma, self.available_versions):
                    version = selected_version
                    install_solc(version, show_progress=False)
                else:
                    raise SolcInstallError()

        elif latest_installed := self.latest_installed_version:
            version = latest_installed

        elif latest := self.latest_version:
            install_solc(latest, show_progress=False)
            version = latest

        else:
            raise SolcInstallError()

        version = add_commit_hash(version)
        cleaned_version = Version(version.base_version)
        executable = get_executable(cleaned_version)
        try:
            result = compile_source(
                code,
                import_remappings=self.get_import_remapping(base_path=base_path),
                base_path=base_path,
                solc_binary=executable,
                solc_version=cleaned_version,
                allow_empty=True,
            )
        except SolcError as err:
            raise CompilerError(str(err)) from err

        output = result[next(iter(result.keys()))]
        return ContractType(
            abi=output["abi"],
            ast=output["ast"],
            deploymentBytecode={"bytecode": HexBytes(output["bin"])},
            devdoc=load_dict(output["devdoc"]),
            runtimeBytecode={"bytecode": HexBytes(output["bin-runtime"])},
            sourcemap=output["srcmap"],
            userdoc=load_dict(output["userdoc"]),
            **kwargs,
        )

    def _get_unmapped_imports(
        self,
        contract_filepaths: List[Path],
        base_path: Optional[Path] = None,
    ) -> Dict[str, List[Tuple[str, str]]]:
        contracts_path = base_path or self.config_manager.contracts_folder
        import_remapping = self.get_import_remapping(base_path=contracts_path)
        contract_filepaths_set = verify_contract_filepaths(contract_filepaths)

        imports_dict: Dict[str, List[Tuple[str, str]]] = {}
        for src_path, import_strs in get_import_lines(contract_filepaths_set).items():
            import_list = []
            for import_str in import_strs:
                raw_import_item_search = re.search(r'"(.*?)"', import_str)
                if raw_import_item_search is None:
                    raise CompilerError(f"No target filename found in import {import_str}")
                raw_import_item = raw_import_item_search.group(1)
                import_item = _import_str_to_source_id(
                    import_str, src_path, contracts_path, import_remapping
                )

                # Only add to the list if it's not already there, to mimic set behavior
                if (import_item, raw_import_item) not in import_list:
                    import_list.append((import_item, raw_import_item))

            source_id = str(get_relative_path(src_path, contracts_path))
            imports_dict[str(source_id)] = import_list

        return imports_dict

    def get_imports(
        self,
        contract_filepaths: List[Path],
        base_path: Optional[Path] = None,
    ) -> Dict[str, List[str]]:
        # NOTE: Process import remappings _before_ getting the full contract set.
        contracts_path = base_path or self.config_manager.contracts_folder
        import_remapping = self.get_import_remapping(base_path=contracts_path)
        contract_filepaths_set = verify_contract_filepaths(contract_filepaths)

        imports_dict: Dict[str, List[str]] = {}
        for src_path, import_strs in get_import_lines(contract_filepaths_set).items():
            import_set = set()
            for import_str in import_strs:
                import_item = _import_str_to_source_id(
                    import_str, src_path, contracts_path, import_remapping
                )
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
        if version := self._settings_version:
            return {version: source_paths_to_get}

        # else: find best version per source file

        # Build map of pragma-specs.
        source_by_pragma_spec = {p: get_pragma_spec_from_path(p) for p in source_paths_to_get}

        # If no Solidity version has been installed previously while fetching the
        # contract version pragma, we must install a compiler, so choose the latest
        if (
            not self.installed_versions
            and not any(source_by_pragma_spec.values())
            and (latest := self.latest_version)
        ):
            install_solc(latest, show_progress=False)

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
                    str(imported_pragma_spec)[0].startswith("=")
                    or str(imported_pragma_spec)[0].isdigit()
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

        return {add_commit_hash(v): ls for v, ls in files_by_solc_version.items()}

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

    def _get_pramga_spec_from_str(self, source_str: str) -> Optional[SpecifierSet]:
        if not (pragma_spec := get_pragma_spec_from_str(source_str)):
            return None

        # Check if we need to install specified compiler version
        if select_version(pragma_spec, self.installed_versions):
            return pragma_spec

        elif compiler_version := select_version(pragma_spec, self.available_versions):
            install_solc(compiler_version, show_progress=False)

        else:
            # Attempt to use the best-installed version.
            for version in self.installed_versions:
                if version not in pragma_spec:
                    continue

                logger.warning(
                    "Ape is unable to determine if additional versions are needed "
                    f"in order to meet spec {pragma_spec}. Resorting to the best matching "
                    "already-installed version. Alternatively, specify a Solidity "
                    "compiler version in your ape-config.yaml."
                )
                return pragma_spec

            # None of the installed versions match, and we are unable to install.
            raise CompilerError(f"Solidity version specification '{pragma_spec}' could not be met.")

        return pragma_spec

    def _get_best_version(self, path: Path, source_by_pragma_spec: Dict) -> Version:
        compiler_version: Optional[Version] = None
        if pragma_spec := source_by_pragma_spec.get(path):
            if selected := select_version(pragma_spec, self.installed_versions):
                compiler_version = selected

            elif selected := select_version(pragma_spec, self.available_versions):
                # Install missing version.
                # NOTE: Must be installed before adding commit hash.
                install_solc(selected, show_progress=True)
                compiler_version = add_commit_hash(selected)

        elif latest_installed := self.latest_installed_version:
            compiler_version = latest_installed

        elif latest := self.latest_version:
            # Download latest version.
            install_solc(latest, show_progress=True)
            compiler_version = latest

        else:
            raise SolcInstallError()

        assert compiler_version  # For mypy
        return add_commit_hash(compiler_version)

    def enrich_error(self, err: ContractLogicError) -> ContractLogicError:
        if not is_0x_prefixed(err.revert_message):
            # Nothing to do.
            return err

        if panic_cls := _get_sol_panic(err.revert_message):
            return panic_cls(
                base_err=err.base_err,
                contract_address=err.contract_address,
                source_traceback=err.source_traceback,
                trace=err.trace,
                txn=err.txn,
            )

        # Check for ErrorABI.
        bytes_message = HexBytes(err.revert_message)
        selector = bytes_message[:4]
        input_data = bytes_message[4:]

        # TODO: Any version after Ape 0.6.11 we can replace this with `err.address`.
        if not (
            address := err.contract_address
            or getattr(err.txn, "receiver", None)
            or getattr(err.txn, "contract_address", None)
        ):
            return err

        if not self.network_manager.active_provider:
            # Connection required.
            return err

        if (
            not (contract := self.chain_manager.contracts.instance_at(address))
            or selector not in contract.contract_type.errors
        ):
            return err

        ecosystem = self.provider.network.ecosystem
        abi = contract.contract_type.errors[selector]
        inputs = ecosystem.decode_calldata(abi, input_data)
        error_class = contract.get_error_by_signature(abi.signature)
        return error_class(
            abi,
            inputs,
            base_err=err.base_err,
            contract_address=err.contract_address,
            source_traceback=err.source_traceback,
            trace=err.trace,
            txn=err.txn,
        )

    def _flatten_source(
        self, path: Path, base_path: Optional[Path] = None, raw_import_name: Optional[str] = None
    ) -> str:
        base_path = base_path or self.config_manager.contracts_folder
        imports = self._get_unmapped_imports([path])
        source = ""
        for import_list in imports.values():
            for import_path, raw_import_path in sorted(import_list):
                source += self._flatten_source(
                    base_path / import_path, base_path=base_path, raw_import_name=raw_import_path
                )
        if raw_import_name:
            source += f"// File: {raw_import_name}\n"
        else:
            source += f"// File: {path.name}\n"
        source += path.read_text() + "\n"
        return source

    def flatten_contract(self, path: Path, **kwargs) -> Content:
        # try compiling in order to validate it works
        self.compile([path], base_path=self.config_manager.contracts_folder)
        source = self._flatten_source(path)
        source = remove_imports(source)
        source = process_licenses(source)
        source = remove_version_pragmas(source)
        pragma = get_first_version_pragma(path.read_text())
        source = "\n".join([pragma, source])
        lines = source.splitlines()
        line_dict = {i + 1: line for i, line in enumerate(lines)}
        return Content(__root__=line_dict)


def remove_imports(flattened_contract: str) -> str:
    # Use regex.sub() to remove matched import statements
    no_imports_contract = IMPORTS_PATTERN.sub("", flattened_contract)

    return no_imports_contract


def remove_version_pragmas(flattened_contract: str) -> str:
    return VERSION_PRAGMA_PATTERN.sub("", flattened_contract)


def get_first_version_pragma(source: str) -> str:
    match = VERSION_PRAGMA_PATTERN.search(source)
    if match:
        return match.group(0)
    return ""


def get_licenses(source: str) -> List[Tuple[str, str]]:
    matches = LICENSES_PATTERN.findall(source)
    return matches


def process_licenses(contract: str) -> str:
    """
    Process the licenses in a contract.
    Ensure that all licenses are identical, and if not, raise an error.
    The contract is returned with a single license identifier line at its top.
    """

    # Extract SPDX license identifiers from the contract.
    extracted_licenses = get_licenses(contract)

    # Return early if no licenses are present in the contract.
    if not extracted_licenses:
        return contract

    # Get the unique license identifiers. We expect that all licenses in a contract are the same.
    unique_license_identifiers = {
        license_identifier for _, license_identifier in extracted_licenses
    }

    # If we have more than one unique license identifier, raise an error.
    if len(unique_license_identifiers) > 1:
        raise CompilerError(f"Conflicting licenses found: {unique_license_identifiers}")

    # Get the first license line and identifier.
    license_line, _ = extracted_licenses[0]

    # Remove all of the license lines from the contract.
    contract_without_licenses = contract.replace(license_line, "")

    # Prepend the contract with only one license line.
    contract_with_single_license = f"{license_line}\n{contract_without_licenses}"

    return contract_with_single_license


def _get_sol_panic(revert_message: str) -> Optional[Type[RuntimeErrorUnion]]:
    if revert_message.startswith(RUNTIME_ERROR_CODE_PREFIX):
        # ape-geth (style) plugins show the hex with the Panic ABI prefix.
        error_type_val = int(
            f"0x{revert_message.replace(RUNTIME_ERROR_CODE_PREFIX, '').lstrip('0')}", 16
        )
    else:
        # Some plugins, like ape-hardhat, will deliver panic codes directly (no Panic ABI prefix)
        error_type_val = int(revert_message, 16)

    if error_type_val in [x.value for x in RuntimeErrorType]:
        return RUNTIME_ERROR_MAP[RuntimeErrorType(error_type_val)]

    return None


def _import_str_to_source_id(
    _import_str: str, source_path: Path, base_path: Path, import_remapping: Dict[str, str]
) -> str:
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
    source_id_value = str(get_relative_path(path, base_path))

    # Get all matches.
    matches: List[Tuple[str, str]] = []
    for key, value in import_remapping.items():
        if key not in source_id_value:
            continue

        matches.append((key, value))

    if not matches:
        return source_id_value

    # Convert remapping list back to source using longest match (most exact).
    key, value = max(matches, key=lambda x: len(x[0]))
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

    return source_id_value


def _try_max(ls: List[Any]):
    return max(ls) if ls else None
