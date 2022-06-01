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
from eth_utils import add_0x_prefix
from ethpm_types import PackageManifest
from packaging import version
from packaging.version import Version as _Version
from semantic_version import NpmSpec, Version  # type: ignore


def get_pragma_spec(source_path: Path) -> Optional[NpmSpec]:
    """
    Extracts pragma information from Solidity source code.
    Args:
        source: Solidity source code
    Returns: NpmSpec object or None, if no valid pragma is found
    """
    if not source_path.is_file():
        return None

    source = source_path.read_text()
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
    # e.g. '@import_name=path/to/Dependency'
    import_remapping: List[str] = []
    optimize: bool = True


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
        return solcx.get_installable_solc_versions()

    @property
    def installed_versions(self) -> List[Version]:
        return solcx.get_installed_solc_versions()

    def get_import_remapping(self, base_path: Optional[Path] = None) -> Dict[str, str]:
        """
        Specify the remapping using a ``=`` separated str
        e.g. ``'@import_name=path/to/Dependency'``.
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
                    raise CompilerError(f"Missing Dependency '{suffix}'.")
                else:
                    options_str = ", ".join(version_ids)
                    raise CompilerError(
                        "Ambiguous version reference. "
                        f"Please set import remapping value to {suffix}/{{version_id}} "
                        f"where 'version_id' is one of '{options_str}'."
                    )

            # Re-build a downloaded Dependency manifest into the .cache directory for imports.
            sub_contracts_cache = contracts_cache / suffix
            if not sub_contracts_cache.exists() or not list(sub_contracts_cache.iterdir()):
                cached_manifest_file = data_folder_cache / f"{name}.json"
                if not cached_manifest_file.exists():
                    raise CompilerError(f"Unable to find dependency '{suffix}'.")

                # NOTE: Purposely skip Pydantic validation here.
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

    def compile(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        input_file_paths = [p for p in contract_filepaths]
        contracts_path = base_path or self.config_manager.contracts_folder
        contract_types: List[ContractType] = []
        files_by_solc_version: Dict[Version, Set[Path]] = {}
        solc_version_by_path: Dict[Path, Version] = {}
        solc_versions_by_source_id: Dict[str, Version] = {}

        # NOTE: Must load imports using *all* source files available.
        imports = self.get_imports(get_all_files_in_directory(contracts_path), contracts_path)

        def _get_pragma_spec(path: Path) -> Optional[NpmSpec]:
            pragma_spec = get_pragma_spec(path)
            if not pragma_spec:
                return None

            # Check if we need to install specified compiler version
            if pragma_spec is pragma_spec.select(self.installed_versions):
                return pragma_spec

            solc_version = pragma_spec.select(self.available_versions)
            if solc_version:
                solcx.install_solc(solc_version, show_progress=False)
            else:
                raise CompilerError(
                    f"Solidity version specification '{pragma_spec}' could not be met."
                )

            return pragma_spec

        def find_best_version(path: Path, gathered_imports: Optional[List[Path]] = None) -> Version:
            gathered_imports = gathered_imports or []
            pragma_spec = _get_pragma_spec(path)
            if path in solc_version_by_path:
                return solc_version_by_path[path]

            solc_version = pragma_spec.select(self.installed_versions) if pragma_spec else None

            source_id = str(get_relative_path(path, contracts_path))
            imported_source_paths = [
                contracts_path / p
                for p in imports.get(source_id, [])
                if p and contracts_path / p not in gathered_imports
            ]

            # Handle circular imports by ignoring already-visited imports.
            gathered_imports += imported_source_paths
            # Check import versions. If any *require* a lower version, use that instead.

            if (
                pragma_spec
                and not pragma_spec.expression.startswith("=")
                and not pragma_spec.expression[0].isnumeric()
            ):
                # NOTE: Pick the lowest version in the imports. This is not guarranteed to work.
                imported_versions = [
                    v
                    for v in [
                        find_best_version(i, gathered_imports=gathered_imports)
                        for i in imported_source_paths
                    ]
                    if v
                ]
                for import_version in imported_versions:
                    if not import_version:
                        continue

                    if not solc_version:
                        solc_version = import_version
                        continue

                    if import_version < solc_version:
                        solc_version = import_version

            if not solc_version:
                solc_version = max(self.installed_versions)

            # By this point, we have found the largest version we can use for this file
            # and all of its imports.
            if solc_version not in files_by_solc_version:
                files_by_solc_version[solc_version] = set()

            files_to_compile = [
                i
                for i in [path, *imported_source_paths]
                if ".cache" not in [p.name for p in i.parents]
            ]
            for src_path in files_to_compile:
                files_by_solc_version[solc_version].add(src_path)
                solc_version_by_path[src_path] = solc_version

            return solc_version

        while contract_filepaths:
            source_path = contract_filepaths.pop()
            if source_path in solc_version_by_path:
                # Already found.
                continue

            find_best_version(source_path)

        base_kwargs = {
            "output_values": [
                "abi",
                "bin",
                "bin-runtime",
                "devdoc",
                "userdoc",
            ],
            "optimize": self.config.optimize,
        }

        for solc_version, files in files_by_solc_version.items():
            cli_base_path = contracts_path if solc_version >= Version("0.6.9") else None
            import_remappings = self.get_import_remapping(base_path=contracts_path)

            kwargs = {
                **base_kwargs,
                "solc_version": solc_version,
                "import_remappings": import_remappings,
            }

            if cli_base_path:
                kwargs["base_path"] = cli_base_path

            output = solcx.compile_files(files, **kwargs)

            def parse_contract_name(value: str) -> Tuple[Path, str]:
                parts = value.split(":")
                return Path(parts[0]), parts[1]

            # Filter source files that the user did not ask for, such as
            # imported relative files that are not part of the input.
            input_contract_names: List[str] = []
            for contract_id in output.keys():
                path, name = parse_contract_name(contract_id)
                for input_file_path in input_file_paths:
                    if str(path) in str(input_file_path):
                        input_contract_names.append(name)

            for contract_name, contract_type in output.items():
                contract_path, contract_name = parse_contract_name(contract_name)

                if contract_name not in input_contract_names:
                    # Only return ContractTypes explicitly asked for.
                    continue

                source_id = str(get_relative_path(contracts_path / contract_path, contracts_path))
                previously_compiled_version = solc_versions_by_source_id.get(source_id)
                if previously_compiled_version:
                    # Don't add previously compiled contract type unless it was compiled
                    # using a greater Solidity version.
                    if previously_compiled_version >= solc_version:
                        continue
                    else:
                        contract_types = [ct for ct in contract_types if ct.source_id != source_id]

                # NOTE: Experimental ABI encode V2 does not use 0x prefixed bins.
                bin = add_0x_prefix(contract_type["bin"])
                runtime_bin = add_0x_prefix(contract_type["bin-runtime"])

                contract_type["contractName"] = contract_name
                contract_type["sourceId"] = source_id
                contract_type["deploymentBytecode"] = {"bytecode": bin}
                contract_type["runtimeBytecode"] = {"bytecode": runtime_bin}
                contract_type["userdoc"] = _load_dict(contract_type["userdoc"])
                contract_type["devdoc"] = _load_dict(contract_type["devdoc"])
                from pydantic import ValidationError

                try:
                    contract_type_obj = ContractType.parse_obj(contract_type)
                except ValidationError:
                    breakpoint()

                contract_types.append(contract_type_obj)
                solc_versions_by_source_id[source_id] = solc_version

        return contract_types

    def get_imports(
        self, contract_filepaths: List[Path], base_path: Optional[Path]
    ) -> Dict[str, List[str]]:
        contracts_path = base_path or self.config_manager.contracts_folder
        import_remapping = self.get_import_remapping(base_path=contracts_path)

        def import_str_to_source_id(import_str: str, source_path: Path) -> str:
            quote = '"' if '"' in import_str else "'"
            end_index = import_str.index(quote) + 1
            import_str_prefix = import_str[end_index:]
            import_str = import_str_prefix[: import_str_prefix.index(quote)]
            path = (source_path.parent / import_str).resolve()
            source_id = str(get_relative_path(path, contracts_path))

            # Convert remappings back to source
            for key, value in import_remapping.items():
                if key not in source_id:
                    continue

                sections = [s for s in source_id.split(key) if s]
                depth = len(sections) - 1
                source_id = ""

                index = 0
                for section in sections:
                    if index == depth:
                        source_id += value
                        source_id += section
                    elif index >= depth:
                        source_id += section

                    index += 1

                break

            return source_id

        imports_dict: Dict[str, List[str]] = {}

        for filepath in contract_filepaths:
            import_set = set()
            for ln in filepath.read_text().splitlines():
                if ln.startswith("import"):
                    import_item = import_str_to_source_id(import_str=ln, source_path=filepath)
                    import_set.add(import_item)

            source_id = str(get_relative_path(filepath, contracts_path))
            imports_dict[str(source_id)] = list(import_set)

        return imports_dict


def _load_dict(data: Union[str, dict]) -> Dict:
    return data if isinstance(data, dict) else json.loads(data)
