import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Union, cast

import solcx  # type: ignore
from ape.api import CompilerAPI, PluginConfig
from ape.exceptions import CompilerError, ConfigError
from ape.types import ContractType
from ape.utils import cached_property, get_relative_path
from ethpm_types import PackageManifest
from packaging import version
from packaging.version import Version as _Version
from semantic_version import NpmSpec, Version  # type: ignore


def get_pragma_spec(source: str) -> Optional[NpmSpec]:
    """
    Extracts pragma information from Solidity source code.
    Args:
        source: Solidity source code
    Returns: NpmSpec object or None, if no valid pragma is found
    """
    pragma_match = next(re.finditer(r"(?:\n|^)\s*pragma\s*solidity\s*([^;\n]*)", source), None)
    if pragma_match is None:
        return None  # Try compiling with latest

    pragma_string = pragma_match.groups()[0]
    pragma_string = " ".join(pragma_string.split())

    try:
        return NpmSpec(pragma_string)

    except ValueError:
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
    @property
    def name(self) -> str:
        return "solidity"

    @cached_property
    def config(self) -> SolidityConfig:
        return cast(SolidityConfig, self.config_manager.get_config(self.name))

    def get_versions(self, all_paths: List[Path]) -> Set[str]:
        versions = set()
        for path in all_paths:
            source = path.read_text()

            # Make sure we have the compiler available to compile this
            version_spec = get_pragma_spec(source)
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
        items = self.config.import_remapping
        import_map: Dict[str, str] = {}
        contracts_cache = base_path / ".cache" if base_path else Path(".cache")
        packages_cache = Path.home() / ".ape" / "packages"

        if not items:
            return import_map

        if not isinstance(items, (list, tuple)) or not isinstance(items[0], str):
            raise IncorrectMappingFormatError()

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

            contracts_cache = contracts_cache / suffix
            if not contracts_cache.exists() or not list(contracts_cache.iterdir()):
                cached_manifest_file = data_folder_cache / f"{name}.json"
                if not cached_manifest_file.exists():
                    # Dependency should have gotten installed prior to this.
                    raise CompilerError(f"Missing dependency '{suffix}'.")

                manifest_dict = json.loads(cached_manifest_file.read_text())
                manifest = PackageManifest(**manifest_dict)

                contracts_cache.mkdir(parents=True)
                sources = manifest.sources or {}
                for source_name, source in sources.items():
                    cached_source = contracts_cache / source_name

                    # NOTE: Cached source may included sub-directories.
                    cached_source.parent.mkdir(parents=True, exist_ok=True)

                    if source.content:
                        cached_source.touch()
                        cached_source.write_text(source.content)

            contracts_cache = (
                get_relative_path(contracts_cache, base_path) if base_path else contracts_cache
            )
            import_map[item_parts[0]] = str(contracts_cache)

        return import_map

    def compile(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        # TODO: move this to solcx
        contract_types = []
        files = []
        solc_version = None

        for path in contract_filepaths:
            files.append(path)
            source = path.read_text()
            pragma_spec = get_pragma_spec(source)
            # check if we need to install specified compiler version
            if pragma_spec:
                if pragma_spec is not pragma_spec.select(self.installed_versions):
                    solc_version = pragma_spec.select(self.available_versions)
                    if solc_version:
                        solcx.install_solc(solc_version, show_progress=False)
                    else:
                        raise CompilerError(f"Solidity version '{solc_version}' is not available.")
                else:
                    solc_version = pragma_spec.select(self.installed_versions)
            else:
                solc_version = max(self.installed_versions)

        if not base_path:
            # Does support base_path
            from ape import config

            base_path = config.contracts_folder

        cli_base_path = base_path if solc_version >= Version("0.6.9") else None
        import_remappings = self.get_import_remapping(base_path=cli_base_path)

        kwargs = {
            "output_values": [
                "abi",
                "bin",
                "bin-runtime",
                "devdoc",
                "userdoc",
            ],
            "solc_version": solc_version,
            "import_remappings": import_remappings,
            "optimize": self.config.optimize,
        }

        if cli_base_path:
            kwargs["base_path"] = cli_base_path

        output = solcx.compile_files(files, **kwargs)

        def load_dict(data: Union[str, dict]) -> Dict:
            return data if isinstance(data, dict) else json.loads(data)

        for contract_name, contract_type in output.items():
            contract_id_parts = contract_name.split(":")
            contract_path = Path(contract_id_parts[0])
            contract_type["contractName"] = contract_id_parts[-1]
            contract_type["sourceId"] = (
                str(get_relative_path(base_path / contract_path, base_path))
                if base_path and contract_path.is_absolute()
                else str(contract_path)
            )
            contract_type["deploymentBytecode"] = {"bytecode": contract_type["bin"]}
            contract_type["runtimeBytecode"] = {"bytecode": contract_type["bin-runtime"]}
            contract_type["userdoc"] = load_dict(contract_type["userdoc"])
            contract_type["devdoc"] = load_dict(contract_type["devdoc"])

            contract_types.append(ContractType.parse_obj(contract_type))

        # Fix source IDs for when compiler did not account for base_path,
        # such as solidity<0.6.9.
        for contract_type in contract_types:
            if contract_type.source_id:
                source_id_path = Path(contract_type.source_id)
                if source_id_path.is_absolute():
                    contract_type.source_id = str(get_relative_path(source_id_path, base_path))

        return contract_types
