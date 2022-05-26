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
from ape.utils import cached_property, get_relative_path
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
    # e.g. '@import_name=path/to/dependency'
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
        e.g. ``'@import_name=path/to/dependency'``.
        """
        import_map: Dict[str, str] = {}
        items = self.config.import_remapping

        if not items:
            return import_map

        if not isinstance(items, (list, tuple)) or not isinstance(items[0], str):
            raise IncorrectMappingFormatError()

        contracts_cache = (
            base_path / ".cache"
            if base_path
            else self.config_manager.contracts_folder / Path(".cache")
        )

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
                    raise CompilerError(f"Unable to find dependency '{suffix}'.")

                manifest_dict = json.loads(cached_manifest_file.read_text())
                manifest = PackageManifest(**manifest_dict)

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
        base_path = base_path or self.config_manager.contracts_folder
        contract_types: List[ContractType] = []
        files_by_solc_version: Dict[Version, Set[Path]] = {}
        solc_version_by_file_name: Dict[Version, Path] = {}
        imports = self.get_imports(contract_filepaths, base_path)

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

        for path in contract_filepaths:
            pragma_spec = _get_pragma_spec(path)

            # Check import versions. If any *must* be a specific version, use that instead.
            source_id = str(get_relative_path(path, base_path))
            source_import_paths = [base_path / p for p in imports.get(source_id, [])]
            imported_version_specs = [_get_pragma_spec(s) for s in source_import_paths]
            solc_version = None
            for imported_version_spec in [s for s in imported_version_specs if s]:

                # Check if expression is like '=0.8.0' or '0.8.0'
                expression_prefix = imported_version_spec.expression[0]
                if expression_prefix == "=" or expression_prefix not in ("^", ">", "<"):
                    solc_version = imported_version_spec.select(self.installed_versions)

            if not solc_version and pragma_spec:
                solc_version = pragma_spec.select(self.installed_versions)
            elif not solc_version:
                solc_version = max(self.installed_versions)

            if solc_version not in files_by_solc_version:
                files_by_solc_version[solc_version] = set()

            version_meeting_same_file = solc_version_by_file_name.get(path)
            if version_meeting_same_file:
                if solc_version > version_meeting_same_file:
                    # Compile file using lateset version it can.
                    files_by_solc_version[version_meeting_same_file].remove(path)

                    if len(files_by_solc_version[version_meeting_same_file]) == 0:
                        del files_by_solc_version[version_meeting_same_file]

                    files_by_solc_version[solc_version].add(path)
                # else: do nothing
            else:
                files_by_solc_version[solc_version].add(path)
                solc_version_by_file_name[path] = solc_version

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
            cli_base_path = base_path if solc_version >= Version("0.6.9") else None
            import_remappings = self.get_import_remapping(base_path)

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
                for input_file_path in files:
                    if str(path) in str(input_file_path):
                        input_contract_names.append(name)

            def load_dict(data: Union[str, dict]) -> Dict:
                return data if isinstance(data, dict) else json.loads(data)

            for contract_name, contract_type in output.items():
                contract_path, contract_name = parse_contract_name(contract_name)

                if contract_name not in input_contract_names:
                    # Contract was either not specified or was compiled
                    # previously from a later-solidity version.
                    continue

                contract_type["contractName"] = contract_name
                contract_type["sourceId"] = str(
                    get_relative_path(base_path / contract_path, base_path)
                )
                contract_type["deploymentBytecode"] = {"bytecode": contract_type["bin"]}
                contract_type["runtimeBytecode"] = {"bytecode": contract_type["bin-runtime"]}
                contract_type["userdoc"] = load_dict(contract_type["userdoc"])
                contract_type["devdoc"] = load_dict(contract_type["devdoc"])
                contract_types.append(ContractType.parse_obj(contract_type))

        return contract_types

    def get_imports(
        self, contract_filepaths: List[Path], base_path: Optional[Path]
    ) -> Dict[str, List[str]]:
        contracts_path = base_path or self.config_manager.contracts_folder

        def import_str_to_source_id(self, import_str: str, source_path: Path) -> str:
            quote = '"' if '"' in import_str else "'"
            import_str = import_str[import_str.index(quote) + 1 :]  # noqa:E203
            import_str = import_str[: import_str.index(quote)]
            path = (source_path.parent / import_str).resolve()
            source_id = str(get_relative_path(path, contracts_path))

            # Convert remappings back to source
            for key, value in self.get_import_remapping(contracts_path).items():
                if key not in source_id:
                    continue

                source_id = source_id.replace(key, value)
                break

            return source_id

        imports_dict: Dict[str, List[str]] = {}

        for filepath in contract_filepaths:
            import_set = set()
            for ln in filepath.read_text().splitlines():
                if ln.startswith("import"):
                    import_set.add(
                        import_str_to_source_id(self, import_str=ln, source_path=filepath)
                    )

            source_id = str(get_relative_path(filepath, contracts_path))
            imports_dict[str(source_id)] = list(import_set)

        return imports_dict
