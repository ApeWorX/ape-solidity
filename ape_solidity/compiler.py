import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

import solcx  # type: ignore
from ape.api import CompilerAPI, ConfigItem
from ape.exceptions import CompilerError, ConfigError
from ape.types import ContractType
from ape.utils import cached_property, get_relative_path
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


class SolidityConfig(ConfigItem):
    # Configure re-mappings using a `=` separated-str,
    # e.g. '@import_name=path/to/dependency'
    import_remapping: List[str] = []


def _try_add_packages_path_prefix(path: Path) -> Path:
    packages_path = Path.home() / ".ape" / "packages"
    if not path.exists() and packages_path not in path.parents:
        # Check if user is referencing a '.ape/packages' dependency.
        test_path = packages_path / path
        if test_path.exists():
            return test_path

    return path


class IncorrectMappingFormatError(ConfigError):
    def __init__(self):
        super().__init__(
            "Incorrectly formatted 'solidity.remapping' config property. "
            "Expected '@value_1=value2'."
        )


class SolidityCompiler(CompilerAPI):
    config: SolidityConfig

    @property
    def name(self) -> str:
        return "solidity"

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

    @property
    def import_remapping(self) -> Dict[str, str]:
        """
        Specify the remapping using a ``=`` separated str
        e.g. ``'@import_name=path/to/dependency'``.
        """
        items = self.config.import_remapping
        import_map: Dict[str, str] = {}

        if not items:
            return import_map

        if not isinstance(items, (list, tuple)) or not isinstance(items[0], str):
            raise IncorrectMappingFormatError()

        for item in items:
            item_parts = item.split("=")
            if len(item_parts) != 2:
                raise IncorrectMappingFormatError()

            mapped_path = _try_add_packages_path_prefix(Path(item_parts[1]))
            import_map[item_parts[0]] = str(mapped_path)

        return import_map

    def compile(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        # todo: move this to solcx
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

        output = solcx.compile_files(
            files,
            base_path=base_path,
            output_values=[
                "abi",
                "bin",
                "bin-runtime",
                "devdoc",
                "userdoc",
            ],
            solc_version=solc_version,
            import_remappings=self.import_remapping,
        )

        def load_dict(data: Union[str, dict]) -> Dict:
            return data if isinstance(data, dict) else json.loads(data)

        for contract_name, contract_type in output.items():
            contract_id_parts = contract_name.split(":")
            contract_path = Path(contract_id_parts[0])
            contract_type["contractName"] = contract_id_parts[-1]
            contract_type["sourceId"] = (
                str(get_relative_path(contract_path, base_path))
                if base_path and contract_path.is_absolute()
                else str(contract_path)
            )
            contract_type["deploymentBytecode"] = {"bytecode": contract_type["bin"]}
            contract_type["runtimeBytecode"] = {"bytecode": contract_type["bin-runtime"]}

            contract_types.append(ContractType.parse_obj(contract_type))

        return contract_types
