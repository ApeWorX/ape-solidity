import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from ape.api import CompilerAPI, PluginConfig
from ape.exceptions import CompilerError, ConfigError, ContractLogicError
from ape.logging import logger
from ape.managers.project import LocalProject, ProjectManager
from ape.types import AddressType, ContractType
from ape.utils import cached_property, get_full_extension, get_relative_path
from ape.version import version
from eth_pydantic_types import HexBytes
from eth_utils import add_0x_prefix, is_0x_prefixed
from ethpm_types.source import Compiler, Content
from packaging.version import Version
from pydantic import model_validator
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

from ape_solidity._models import ImportRemappingCache, SourceTree
from ape_solidity._utils import (
    OUTPUT_SELECTION,
    Extension,
    SolidityVersionSpecifier,
    add_commit_hash,
    get_pragma_spec_from_path,
    get_pragma_spec_from_str,
    load_dict,
    select_version,
    strip_commit_hash,
)
from ape_solidity.exceptions import (
    RUNTIME_ERROR_CODE_PREFIX,
    RUNTIME_ERROR_MAP,
    RuntimeErrorType,
    RuntimeErrorUnion,
    SolcCompileError,
    SolcInstallError,
)

if TYPE_CHECKING:
    from ape.contracts import ContractInstance


LICENSES_PATTERN = re.compile(r"(// SPDX-License-Identifier:\s*([^\n]*)\s)")

# Comment patterns
SINGLE_LINE_COMMENT_PATTERN = re.compile(r"^\s*//")
MULTI_LINE_COMMENT_START_PATTERN = re.compile(r"/\*")
MULTI_LINE_COMMENT_END_PATTERN = re.compile(r"\*/")

VERSION_PRAGMA_PATTERN = re.compile(r"pragma solidity[^;]*;")
DEFAULT_OPTIMIZATION_RUNS = 200


def _install_solc(version: Version) -> Version:
    logger.info(f"Installing solc '{version}'.")
    return install_solc(version, show_progress=True)


class ImportRemapping(PluginConfig):
    """
    A remapped import set in the config.
    """

    @model_validator(mode="before")
    def validate_str(cls, value):
        if isinstance(value, str):
            parts = value.split("=")
            return {"key": parts[0], "value": parts[1]}

        return value

    """
    The key of the remapping, such as ``@openzeppelin``.
    """
    key: str

    """
    The value to use in place of the key,
    such as ``path/somewhere/else``.
    """
    value: str

    def __str__(self) -> str:
        return f"{self.key}={self.value}"

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other

        return super().__eq__(other)


class SolidityConfig(PluginConfig):
    """
    Configure the ape-solidity plugin.
    """

    import_remapping: list[ImportRemapping] = []
    """
    Custom remappings as a key value map..
    Note: You do not need to specify dependencies here.
    """

    optimize: bool = True
    """
    Compile with optimization. Defaults to ``True``.
    """

    optimization_runs: int = DEFAULT_OPTIMIZATION_RUNS
    """
    The number of runs specifies roughly how often each opcode of the
    deployed code will be executed across the lifetime of the contract.
    Lower values will optimize more for initial deployment cost, higher
    values will optimize more for high-frequency usage.
    """

    version: Optional[str] = None
    """
    Hardcode a Solidity version to use. When not set,
    ape-solidity attempts to use the best version(s)
    available.
    """

    evm_version: Optional[str] = None
    """
    Compile targeting this EVM version.
    """

    via_ir: Optional[bool] = None
    """
    Set to ``True`` to turn on compilation mode via the IR.
    Defaults to ``None`` which does not pass the flag to
    the compiler (same as ``False``).
    """


def _get_flattened_source(path: Path, name: Optional[str] = None) -> str:
    name = name or path.name
    result = f"// File: {name}\n"
    result += f"{path.read_text(encoding='utf8').rstrip()}\n"
    return result


class SolidityCompiler(CompilerAPI):
    """
    The implementation of the ape-solidity Compiler class.
    Implements all methods in :class:`~ape.api.compilers.CompilerAPI`.
    Compiles ``.sol`` files into ``ContractTypes`` for usage in the
    Ape framework.
    """

    # Libraries adding for linking. See `add_library` method.
    _libraries: dict[str, dict[str, AddressType]] = {}

    @property
    def name(self) -> str:
        return "solidity"

    @property
    def libraries(self) -> dict[str, dict[str, AddressType]]:
        return self._libraries

    @cached_property
    def available_versions(self) -> list[Version]:
        try:
            return get_installable_solc_versions()
        except ConnectionError:
            # Compiling offline
            logger.warning("Internet connection required to fetch installable Solidity versions.")
            return []

    @property
    def installed_versions(self) -> list[Version]:
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

    @cached_property
    def _import_remapping_cache(self) -> ImportRemappingCache:
        return ImportRemappingCache()

    def _get_configured_version(
        self, project: Optional[ProjectManager] = None
    ) -> Optional[Version]:
        """
        A helper property that gets, verifies, and installs (if needed)
        the version specified in the config.
        """
        pm = project or self.local_project
        config = self.get_config(project=pm)
        if not (version := config.version):
            return None

        installed_versions = self.installed_versions
        specified_commit_hash = "+" in version
        base_version = strip_commit_hash(version)
        if base_version not in installed_versions:
            _install_solc(base_version)

        settings_version = add_commit_hash(base_version)
        if specified_commit_hash and settings_version != version:
            raise ConfigError(
                f"Commit hash from settings version {version} "
                f"differs from installed: {settings_version}"
            )

        return settings_version

    @cached_property
    def _ape_version(self) -> Version:
        return Version(version.split(".dev")[0].strip())

    def add_library(self, *contracts: "ContractInstance", project: Optional[ProjectManager] = None):
        """
        Set a library contract type address. This is useful when deploying a library
        in a local network and then adding the address afterward. Now, when
        compiling again, it will use the new address.

        Args:
            *contracts (``ContractInstance``): The deployed library contract(s).
            project (Optional[ProjectManager]): The project using the library.
        """
        pm = project or self.local_project
        for contract in contracts:
            if not (source_id := contract.contract_type.source_id):
                raise CompilerError("Missing source ID.")
            elif not (name := contract.contract_type.name):
                raise CompilerError("Missing contract type name.")

            self._libraries[source_id] = {name: contract.address}
            path = pm.path / source_id
            if not path.is_file():
                return

            # Recompile the same source, in case contracts were in there
            # that required the libraries.
            contract_types = {
                ct.name: ct for ct in self.compile((path,), project=project) if ct.name
            }
            if contract_types:
                all_types = {**pm.manifest.contract_types, **contract_types}
                pm.update_manifest(contract_types=all_types)

    def get_versions(self, all_paths: Iterable[Path]) -> set[str]:
        all_paths = _validate_can_compile(all_paths)
        versions = set()
        for path in all_paths:
            # Make sure we have the compiler available to compile this
            if version_spec := get_pragma_spec_from_path(path):
                if selected_version := select_version(version_spec, self.available_versions):
                    versions.add(selected_version.base_version)

        return versions

    def get_import_remapping(self, project: Optional[ProjectManager] = None) -> dict[str, str]:
        """
        Config remappings like ``'@import_name=path/to/dependency'`` parsed here
        as ``{'@import_name': 'path/to/dependency'}``.

        Returns:
            Dict[str, str]: Where the key is the import name, e.g. ``"@openzeppelin"`
            and the value is a stringified relative path (source ID) of the cached contract,
            e.g. `".cache/openzeppelin/4.4.2".
        """
        pm = project or self.local_project
        # Always get a fresh remapping when calling the top-level method.
        remapping = self._import_remapping_cache.get_import_remapping(pm)
        # Cache, so all lower-level methods don't have to recalculate.
        self._import_remapping_cache.add(pm, remapping)
        return remapping

    def get_compiler_settings(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
        **kwargs,
    ) -> dict[Version, dict]:
        pm = project or self.local_project
        paths = _validate_can_compile(contract_filepaths)
        imports = SourceTree.from_source_files(paths, pm)
        return self._get_settings_from_imports(paths, imports, project=pm, **kwargs)

    def _get_settings_from_imports(
        self,
        contract_filepaths: Iterable[Path],
        import_tree: SourceTree,
        project: Optional[ProjectManager] = None,
        **kwargs,
    ):
        pm = project or self.local_project
        files_by_solc_version = self.get_version_map_from_imports(
            contract_filepaths, import_tree, project=pm
        )
        return self._get_settings_from_version_map(
            files_by_solc_version,
            import_tree=import_tree,
            project=pm,
            **kwargs,
        )

    def _get_settings_from_version_map(
        self,
        version_map: dict[Version, set[Path]],
        import_tree: SourceTree,
        project: Optional[ProjectManager] = None,
        **kwargs,
    ) -> dict[Version, dict]:
        pm = project or self.local_project
        if not version_map:
            return {}

        config = self.get_config(project=pm)
        settings: dict = {}
        for solc_version, sources in version_map.items():
            version_settings: dict[str, Union[Any, list[Any]]] = {
                "optimizer": {
                    "enabled": config.optimize,
                    "runs": config.optimization_runs,
                },
                "outputSelection": {
                    str(get_relative_path(p, pm.path)): {
                        "*": OUTPUT_SELECTION,
                        "": ["ast"],
                    }
                    for p in sorted(sources)
                },
                **kwargs,
            }
            if remappings_used := import_tree.get_remappings_used(sources):
                remappings_str = [f"{k}={v}" for k, v in remappings_used.items()]

                # Standard JSON input requires remappings to be sorted.
                version_settings["remappings"] = sorted(remappings_str)

            if evm_version := config.evm_version:
                version_settings["evmVersion"] = evm_version

            if solc_version >= Version("0.7.5") and config.via_ir is not None:
                version_settings["viaIR"] = config.via_ir

            settings[solc_version] = version_settings

            # TODO: Filter out libraries that are not used for this version.
            if libs := self.libraries:
                version_settings["libraries"] = libs

        return settings

    def get_standard_input_json(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
        **overrides,
    ) -> dict[Version, dict]:
        pm = project or self.local_project
        paths = list(contract_filepaths)  # Handle if given generator=
        import_tree = SourceTree.from_source_files(paths, pm)
        version_map = self.get_version_map_from_imports(paths, import_tree, project=pm)
        return self.get_standard_input_json_from_version_map(
            version_map, project=pm, import_tree=import_tree, **overrides
        )

    def get_standard_input_json_from_version_map(
        self,
        version_map: dict[Version, set[Path]],
        import_tree: SourceTree,
        project: Optional[ProjectManager] = None,
        **overrides,
    ):
        pm = project or self.local_project
        settings = self._get_settings_from_version_map(
            version_map, import_tree, project=pm, **overrides
        )
        return self.get_standard_input_json_from_settings(settings, version_map, project=pm)

    def get_standard_input_json_from_settings(
        self,
        settings: dict[Version, dict],
        version_map: dict[Version, set[Path]],
        project: Optional[ProjectManager] = None,
    ):
        pm = project or self.local_project
        input_jsons: dict[Version, dict] = {}

        for solc_version, vers_settings in settings.items():
            if not list(version_map[solc_version]):
                continue

            cleaned_version = Version(solc_version.base_version)
            solc_binary = get_executable(version=cleaned_version)
            arguments = {"solc_binary": solc_binary, "solc_version": cleaned_version}

            if solc_version >= Version("0.6.9"):
                arguments["base_path"] = pm.path

            if missing_sources := [
                x for x in vers_settings["outputSelection"] if not (pm.path / x).is_file()
            ]:
                if dependencies_needed := [x for x in missing_sources if str(x).startswith("@")]:
                    missing_str = ", ".join(dependencies_needed)
                    raise CompilerError(
                        f"Missing required dependencies '{missing_str}'. "
                        "Install them using `dependencies:` "
                        "in an ape-config.yaml or using the `ape pm install` command."
                    )

                missing_src_str = ", ".join(missing_sources)
                raise CompilerError(
                    f"Sources '{missing_src_str}' not found in '{pm.name}' "
                    f"(project path: {pm.path})."
                )

            sources = {
                x: {"content": (pm.path / x).read_text(encoding="utf8")}
                for x in sorted(vers_settings["outputSelection"])
            }

            input_jsons[solc_version] = {
                "sources": sources,
                "settings": vers_settings,
                "language": "Solidity",
            }

        return {v: input_jsons[v] for v in sorted(input_jsons)}

    def compile(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
        settings: Optional[dict] = None,
    ) -> Iterator[ContractType]:
        pm = project or self.local_project
        settings = settings or {}
        paths = [(p if Path(p).is_absolute() else pm.path / p) for p in contract_filepaths]
        source_ids = [f"{get_relative_path(Path(p).absolute(), pm.path)}" for p in paths]
        _validate_can_compile(paths)

        # Compile in an isolated env so the .cache folder does not interfere with anything.
        with pm.isolate_in_tempdir() as isolated_project:
            filepaths = [isolated_project.path / src_id for src_id in source_ids]
            yield from self._compile(filepaths, project=isolated_project, settings=settings)
            compilers = isolated_project.manifest.compilers

        pm.update_manifest(compilers=compilers)

    def _compile(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
        settings: Optional[dict] = None,
    ):
        pm = project or self.local_project
        paths = list(contract_filepaths)  # Handle if given generator=
        import_tree = SourceTree.from_source_files(paths, pm)
        version_map = self.get_version_map_from_imports(paths, import_tree, project=pm)
        input_jsons = self.get_standard_input_json_from_version_map(
            version_map,
            import_tree,
            project=pm,
            **(settings or {}),
        )
        contract_versions: dict[str, Version] = {}
        contract_types: list[ContractType] = []
        for solc_version, input_json in input_jsons.items():
            keys = (
                "\n\t".join(sorted([x for x in input_json.get("sources", {}).keys()]))
                or "No input."
            )
            log_str = f"Compiling using Solidity compiler '{solc_version}'.\nInput:\n\t{keys}"
            logger.info(log_str)
            cleaned_version = Version(solc_version.base_version)
            solc_binary = get_executable(version=cleaned_version)
            arguments: dict = {
                "solc_binary": solc_binary,
                "solc_version": cleaned_version,
            }

            if solc_version >= Version("0.6.9"):
                arguments["base_path"] = pm.path

            # Allow empty contracts, like Vyper does.
            arguments["allow_empty"] = True

            try:
                output = compile_standard(input_json, **arguments)
            except SolcError as err:
                raise SolcCompileError(err) from err

            contracts = output.get("contracts", {})
            # Perf back-out.
            if not contracts:
                continue

            input_contract_names: list[str] = []
            for source_id, contracts_out in contracts.items():
                for name, _ in contracts_out.items():
                    # Filter source files that the user did not ask for, such as
                    # imported relative files that are not part of the input.
                    for input_file_path in paths:
                        if source_id in str(input_file_path):
                            input_contract_names.append(name)

            for source_id, contracts_out in contracts.items():
                for contract_name, ct_data in contracts_out.items():
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
                        continue

                    if contract_name in contract_versions:
                        # Already yield in smaller version. Must not yield again
                        # or else we will have a contract-type collision.
                        # (Sources that are required in multiple version-sets will
                        # hit this).
                        continue

                    ct_data["contractName"] = contract_name
                    ct_data["sourceId"] = source_id
                    ct_data["deploymentBytecode"] = {"bytecode": deployment_bytecode}
                    ct_data["runtimeBytecode"] = {"bytecode": runtime_bytecode}
                    ct_data["userdoc"] = load_dict(ct_data["userdoc"])
                    ct_data["devdoc"] = load_dict(ct_data["devdoc"])
                    ct_data["sourcemap"] = evm_data["bytecode"]["sourceMap"]
                    contract_type = ContractType.model_validate(ct_data)
                    yield contract_type
                    contract_types.append(contract_type)
                    contract_versions[contract_name] = solc_version

        # Output compiler data used.
        compilers_used: dict[Version, Compiler] = {}
        for ct in contract_types:
            if not ct.name:
                # Won't happen, but just for mypy.
                continue

            vers = contract_versions[ct.name]
            settings = input_jsons[vers]["settings"]
            if vers in compilers_used and ct.name not in (compilers_used[vers].contractTypes or []):
                compilers_used[vers].contractTypes = [
                    *(compilers_used[vers].contractTypes or []),
                    ct.name,
                ]

            elif vers not in compilers_used:
                compilers_used[vers] = Compiler(
                    name=self.name.lower(),
                    version=f"{vers}",
                    contractTypes=[ct.name],
                    settings=settings,
                )

        # Update compilers used in project manifest.
        # First, output compiler information to manifest.
        compilers_ls = list(compilers_used.values())
        pm.add_compiler_data(compilers_ls)

    def compile_code(
        self,
        code: str,
        project: Optional[ProjectManager] = None,
        **kwargs,
    ) -> ContractType:
        pm = project or self.local_project
        if settings_version := self._get_configured_version(project=pm):
            version = settings_version

        elif pragma := self._get_pragma_spec_from_str(code):
            if selected_version := select_version(pragma, self.installed_versions):
                version = selected_version
            else:
                if selected_version := select_version(pragma, self.available_versions):
                    version = selected_version
                    _install_solc(version)
                else:
                    raise SolcInstallError()

        elif latest_installed := self.latest_installed_version:
            version = latest_installed

        elif latest := self.latest_version:
            _install_solc(latest)
            version = latest

        else:
            raise SolcInstallError()

        version = add_commit_hash(version)
        cleaned_version = Version(version.base_version)
        executable = get_executable(cleaned_version)
        try:
            result = compile_source(
                code,
                import_remappings=self.get_import_remapping(project=pm),
                base_path=pm.path,
                solc_binary=executable,
                solc_version=cleaned_version,
                allow_empty=True,
            )
        except SolcError as err:
            raise SolcCompileError(err) from err

        output = result[next(iter(result.keys()))]
        return ContractType.model_validate(
            {
                "abi": output["abi"],
                "ast": output["ast"],
                "deploymentBytecode": {"bytecode": HexBytes(output["bin"])},
                "devdoc": load_dict(output["devdoc"]),
                "runtimeBytecode": {"bytecode": HexBytes(output["bin-runtime"])},
                "sourcemap": output["srcmap"],
                "userdoc": load_dict(output["userdoc"]),
                **kwargs,
            }
        )

    def get_imports(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
    ) -> dict[str, list[str]]:
        pm = project or self.local_project
        paths = _validate_can_compile(contract_filepaths)
        tree = SourceTree.from_source_files(paths, pm)
        return tree.model_dump(mode="json")["import_statements"]

    def get_version_map(
        self,
        contract_filepaths: Union[Path, Iterable[Path]],
        project: Optional[ProjectManager] = None,
    ) -> dict[Version, set[Path]]:
        pm = project or self.local_project
        paths = (
            [contract_filepaths]
            if isinstance(contract_filepaths, Path)
            else [p for p in contract_filepaths]
        )
        _validate_can_compile(paths)
        import_tree = SourceTree.from_source_files(paths, pm)
        return self.get_version_map_from_imports(paths, import_tree, project=pm)

    def get_version_map_from_imports(
        self,
        contract_filepaths: Union[Path, Iterable[Path]],
        import_tree: SourceTree,
        project: Optional[ProjectManager] = None,
    ) -> dict[Version, set[Path]]:
        pm = project or self.local_project
        paths = (
            [contract_filepaths]
            if isinstance(contract_filepaths, Path)
            else [p for p in contract_filepaths]
        )
        path_set: set[Path] = {p for p in paths}

        # Add imported source files to list of contracts to compile.
        for source_path in paths:
            if source_path not in import_tree or len(import_tree[source_path]) == 0:
                continue

            import_set = import_tree.get_imported_paths(source_path)
            path_set = path_set.union(import_set)

        # Use specified version if given one
        if _version := self._get_configured_version(project=pm):
            return {_version: path_set}
        # else: find best version per source file

        # Build map of pragma-specs.
        pragma_map = {p: get_pragma_spec_from_path(p) for p in path_set}

        # If no Solidity version has been installed previously while fetching the
        # contract version pragma, we must install a compiler, so choose the latest
        if (
            not self.installed_versions
            and not any(pragma_map.values())
            and (latest := self.latest_version)
        ):
            _install_solc(latest)

        # Select a compiler for each requested source plus the full transitive import closure
        # that solc must compile with it.
        files_by_solc_version: dict[Version, set[Path]] = defaultdict(set)
        required_imports_by_solc_version: dict[Version, set[Path]] = defaultdict(set)
        for source_file_path in paths:
            imported_source_paths = import_tree.get_imported_paths(source_file_path)
            source_closure = {source_file_path, *imported_source_paths}
            solc_version = self._get_best_version_for_source_set(source_closure, pragma_map, pm)
            files_by_solc_version[solc_version].update(source_closure)
            required_imports_by_solc_version[solc_version].update(imported_source_paths)

        # If a requested source also appears in a more constrained import closure, compile it in
        # the constrained closure only. If it is imported by roots in multiple version groups,
        # keep it in each group because solc needs it in each standard-json input.
        versions_by_file: dict[Path, set[Version]] = defaultdict(set)
        for solc_version, files in files_by_solc_version.items():
            for file in files:
                versions_by_file[file].add(solc_version)

        cleaned_mapped: dict[Version, set[Path]] = defaultdict(set)
        for solc_version, files in files_by_solc_version.items():
            for file in files:
                if (
                    len(versions_by_file[file]) > 1
                    and file not in required_imports_by_solc_version[solc_version]
                ):
                    continue

                cleaned_mapped[solc_version].add(file)

        result = {add_commit_hash(v): ls for v, ls in cleaned_mapped.items()}

        # Sort, so it is a nicer version map and the rest of the compilation flow
        # is more predictable. Also, remove any lingering empties.
        return {k: result[k] for k in sorted(result) if result[k]}

    def _get_best_version_for_source_set(
        self,
        source_paths: set[Path],
        source_by_pragma_spec: dict[Path, Optional[SolidityVersionSpecifier]],
        project: ProjectManager,
    ) -> Version:
        pragma_map = {
            path: pragma_spec
            for path in sorted(source_paths)
            if (pragma_spec := source_by_pragma_spec.get(path))
        }
        if not pragma_map:
            return self._get_best_version_without_pragma()

        if selected := self._select_version_for_pragmas(
            pragma_map.values(), self.installed_versions
        ):
            return add_commit_hash(selected)

        if selected := self._select_version_for_pragmas(
            pragma_map.values(), self.available_versions
        ):
            _install_solc(selected)
            return add_commit_hash(selected)

        source_ids = ", ".join(
            f"{get_relative_path(path, project.path)} ({pragma_spec})"
            for path, pragma_spec in pragma_map.items()
        )
        installed_versions = _format_versions(self.installed_versions)
        available_versions = _format_versions(self.available_versions)
        raise CompilerError(
            "No installed or available Solidity compiler version satisfies "
            f"the combined pragma constraints: {source_ids}. "
            f"Installed versions: {installed_versions}. Available versions: {available_versions}."
        )

    def _select_version_for_pragmas(
        self,
        pragma_specs: Iterable[SolidityVersionSpecifier],
        options: Iterable[Version],
    ) -> Optional[Version]:
        candidates = list(options)
        for pragma_spec in pragma_specs:
            candidates = list(pragma_spec.filter(candidates))
            if not candidates:
                return None

        return sorted(candidates, reverse=True)[0]

    def _get_best_version_without_pragma(self) -> Version:
        if latest_installed := self.latest_installed_version:
            compiler_version = latest_installed

        elif latest := self.latest_version:
            _install_solc(latest)
            compiler_version = latest

        else:
            raise SolcInstallError()

        return add_commit_hash(compiler_version)

    def _get_pragma_spec_from_str(self, source_str: str) -> Optional[SolidityVersionSpecifier]:
        if not (pragma_spec := get_pragma_spec_from_str(source_str)):
            return None

        # Check if we need to install specified compiler version
        if select_version(pragma_spec, self.installed_versions):
            return pragma_spec

        elif compiler_version := select_version(pragma_spec, self.available_versions):
            _install_solc(compiler_version)

        else:
            # Attempt to use the best-installed version.
            for _version in self.installed_versions:
                if _version not in pragma_spec:
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

    def enrich_error(self, err: ContractLogicError) -> ContractLogicError:
        if not is_0x_prefixed(err.revert_message):
            # Nothing to do.
            return err

        elif panic_cls := _get_sol_panic(err.revert_message):
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

        if not err.address:
            return err

        if not self.network_manager.active_provider:
            # Connection required.
            return err

        if (
            not (contract := self.chain_manager.contracts.instance_at(err.address))
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
        self,
        path: Union[Path, str],
        import_tree: SourceTree,
        project: Optional[ProjectManager] = None,
        raw_import_name: Optional[str] = None,
        handled: Optional[set[str]] = None,
    ) -> str:
        pm = project or self.local_project
        handled = handled or set()
        path = Path(path)
        source_id = f"{get_relative_path(path, pm.path)}" if path.is_absolute() else f"{path}"
        handled.add(source_id)
        relevant_imports = sorted(list(import_tree[path]), key=lambda x: x.raw_value)

        final_source = ""
        for import_metadata in relevant_imports:
            if import_metadata.source_id in handled:
                continue
            elif not (sub_path := import_metadata.path):
                continue

            sub_source = self._flatten_source(
                sub_path,
                import_tree,
                project=pm,
                handled=handled,
                raw_import_name=import_metadata.raw_value,
            )
            final_source += sub_source

        flattened_src = _get_flattened_source(path, name=raw_import_name)
        if flattened_src and final_source.rstrip():
            final_source = f"{final_source.rstrip()}\n\n{flattened_src}"
        elif flattened_src:
            final_source = flattened_src

        return final_source

    def flatten_contract(
        self, path: Path, project: Optional[ProjectManager] = None, **kwargs
    ) -> Content:
        pm = project or self.local_project
        tree = SourceTree.from_source_files((path,), pm)
        res = self._flatten_source(path, tree, project=pm)
        res = remove_imports(res)
        res = process_licenses(res)
        res = remove_version_pragmas(res)
        pragma = get_first_version_pragma(path.read_text(encoding="utf8"))
        res = "\n".join([pragma, res])

        # Simple auto-format.
        while "\n\n\n" in res:
            res = res.replace("\n\n\n", "\n\n")

        lines = res.splitlines()
        line_dict = {i + 1: line for i, line in enumerate(lines)}
        return Content(root=line_dict)

    def _import_str_to_source_id(
        self,
        _import_str: str,
        source_path: Path,
        project: Optional[ProjectManager] = None,
    ) -> str:
        pm = project or self.local_project
        quote = '"' if '"' in _import_str else "'"
        sep = "\\" if "\\" in _import_str else "/"

        try:
            end_index = _import_str.index(quote) + 1
        except ValueError as err:
            raise CompilerError(
                f"Error parsing import statement '{_import_str}' in '{source_path.name}'."
            ) from err

        import_str_prefix = _import_str[end_index:]
        import_str_value = import_str_prefix[: import_str_prefix.index(quote)]

        # Get all matches.
        valid_matches: list[tuple[str, str]] = []
        import_remap_key = None
        base_path = None
        import_remapping = self._import_remapping_cache[pm]
        for check_remap_key, check_remap_value in import_remapping.items():
            if check_remap_key not in import_str_value:
                continue

            valid_matches.append((check_remap_key, check_remap_value))

        if valid_matches:
            import_remap_key, import_remap_value = max(valid_matches, key=lambda x: len(x[0]))
            import_str_value = import_str_value.replace(import_remap_key, import_remap_value)

        if import_str_value.startswith("."):
            base_path = source_path.parent
        elif (pm.path / import_str_value).is_file():
            base_path = pm.path
        elif (pm.contracts_folder / import_str_value).is_file():
            base_path = pm.contracts_folder
        elif import_remap_key is not None and import_remap_key.startswith("@"):
            nm = import_remap_key[1:]
            for cfg_dep in pm.config.dependencies:
                if (
                    cfg_dep.get("name") == nm
                    and "project" in cfg_dep
                    and (Path(cfg_dep["project"]) / import_str_value).is_file()
                ):
                    base_path = Path(cfg_dep["project"])

        import_str_parts = import_str_value.split(sep)
        if base_path is None and ".cache" in import_str_parts:
            # No base_path. First, check if the `contracts/` folder is missing,
            # which is the case when compiling older Ape projects and some Foundry
            # projects as well.
            cache_index = import_str_parts.index(".cache")
            nm_index = cache_index + 1
            version_index = nm_index + 1
            if version_index >= len(import_str_parts):
                # Not sure.
                return import_str_value

            cache_folder_name = import_str_parts[nm_index]
            cache_folder_version = import_str_parts[version_index]
            dm = pm.dependencies
            dependency = dm.get_dependency(cache_folder_name, cache_folder_version)
            dep_project = dependency.project

            if not isinstance(dep_project, LocalProject):
                # TODO: Handle manifest-based projects as well.
                #   to work with old compiled manifests.
                return import_str_value

            contracts_dir = dep_project.contracts_folder
            dep_path = dep_project.path
            contracts_folder_name = f"{get_relative_path(contracts_dir, dep_path)}"
            prefix_pth = dep_path / contracts_folder_name
            start_idx = version_index + 1
            suffix = sep.join(import_str_parts[start_idx:])
            new_path = prefix_pth / suffix

            if not new_path.is_file():
                # Maybe this source is actually missing...
                return import_str_value

            adjusted_base_path = f"{sep.join(import_str_parts[:4])}{sep}{contracts_folder_name}"
            adjusted_src_id = f"{adjusted_base_path}{sep}{suffix}"

            # Also, correct import remappings now, since it didn't work.
            if key := import_remap_key:
                # Base path will now included the missing contracts name.
                import_remapping[key] = adjusted_base_path

            return adjusted_src_id

        elif base_path is None:
            # No base_path, return as-is.
            return import_str_value

        path = (base_path / import_str_value).resolve()
        return f"{get_relative_path(path.absolute(), pm.path)}"


def remove_imports(source_code: str) -> str:
    code = remove_comments(source_code)
    result_lines: list[str] = []
    in_multiline_import = False
    for line in code.splitlines():
        if line.lstrip().startswith("import ") or line.strip() == "import":
            if not line.rstrip().endswith(";"):
                in_multiline_import = True

            continue

        elif in_multiline_import:
            if line.rstrip().endswith(";"):
                in_multiline_import = False

            continue

        result_lines.append(line)

    return "\n".join(result_lines)


def remove_comments(source_code: str) -> str:
    in_multi_line_comment = False
    result_lines: list[str] = []

    lines = source_code.splitlines()
    for line in lines:
        # Check if we're entering a multi-line comment
        if MULTI_LINE_COMMENT_START_PATTERN.search(line):
            in_multi_line_comment = True

        # If inside a multi-line comment, just add the line to the result
        if in_multi_line_comment:
            result_lines.append(line)
            # Check if this line ends the multi-line comment
            if MULTI_LINE_COMMENT_END_PATTERN.search(line):
                in_multi_line_comment = False
            continue

        # Skip single-line comments
        if SINGLE_LINE_COMMENT_PATTERN.match(line):
            result_lines.append(line)
            continue

        # Add the line to the result if it's not an import statement
        result_lines.append(line)

    return "\n".join(result_lines)


def remove_version_pragmas(flattened_contract: str) -> str:
    return VERSION_PRAGMA_PATTERN.sub("", flattened_contract)


def get_first_version_pragma(source: str) -> str:
    match = VERSION_PRAGMA_PATTERN.search(source)
    if match:
        return match.group(0)
    return ""


def get_licenses(src: str) -> list[tuple[str, str]]:
    return LICENSES_PATTERN.findall(src)


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

    # The "root" license is most-likely last because import statements are
    # replaced with their sources typically at the top of the file
    license_line, root_license = extracted_licenses[-1]

    # Get the unique license identifiers. All licenses in a contract _should_ be the same.
    unique_license_identifiers = {lid for _, lid in extracted_licenses}

    # If we have more than one unique license identifier, warn the user and use the root.
    if len(unique_license_identifiers) > 1:
        licenses_str = ", ".join(sorted(unique_license_identifiers))
        logger.warning(
            f"Conflicting licenses found: '{licenses_str}'. "
            f"Using the root file's license '{root_license}'."
        )

    # Remove all of the license lines from the contract.
    contract_without_licenses = contract
    for license_tuple in extracted_licenses:
        line = license_tuple[0]
        contract_without_licenses = contract_without_licenses.replace(line, "")

    # Prepend the contract with only the root license line.
    contract_with_single_license = f"{license_line}\n{contract_without_licenses}"

    return contract_with_single_license


def _get_sol_panic(revert_message: str) -> Optional[type[RuntimeErrorUnion]]:
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


def _try_max(ls: list[Any]):
    return max(ls) if ls else None


def _format_versions(versions: Iterable[Version]) -> str:
    sorted_versions = sorted(versions, reverse=True)
    return ", ".join(str(version) for version in sorted_versions) or "none"


def _validate_can_compile(paths: Iterable[Path]) -> Sequence[Path]:
    path_ls = []
    valid_extensions = [e.value for e in Extension]

    for path in paths:
        ext = get_full_extension(path)
        if ext not in valid_extensions:
            raise CompilerError(f"Unable to compile '{path.name}' using Solidity compiler.")

        path_ls.append(path)

    return path_ls
