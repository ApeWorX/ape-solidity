import re
from pathlib import Path
from typing import List, Optional, Set

import solcx  # type: ignore
from ape.api.compiler import CompilerAPI
from ape.types import Bytecode, ContractType
from ape.utils import cached_property
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


class SolidityCompiler(CompilerAPI):
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

    def compile(self, contract_filepaths: List[Path]) -> List[ContractType]:
        # todo: move this to solcx
        contract_types = []
        for path in contract_filepaths:
            source = path.read_text()
            pragma_spec = get_pragma_spec(source)
            # check if we need to install specified compiler version
            if pragma_spec:
                if pragma_spec is not pragma_spec.select(self.installed_versions):
                    solc_version = pragma_spec.select(self.available_versions)
                    if solc_version:
                        solcx.install_solc(solc_version, show_progress=False)
                    else:
                        raise Exception("No available version to install")
                else:
                    solc_version = pragma_spec.select(self.installed_versions)
            else:
                solc_version = max(self.installed_versions)
            for result in solcx.compile_source(
                source,
                output_values=[
                    "abi",
                    "bin",
                    "bin-runtime",
                    "devdoc",
                    "userdoc",
                ],
                solc_version=solc_version,
            ).values():
                contract_types.append(
                    ContractType(
                        # NOTE: Vyper doesn't have internal contract type declarations, use filename
                        contractName=Path(path).stem,
                        sourceId=str(path),
                        deploymentBytecode=Bytecode(bytecode=result["bin"]),  # type: ignore
                        runtimeBytecode=Bytecode(bytecode=result["bin-runtime"]),  # type: ignore
                        abi=result["abi"],
                        userdoc=result["userdoc"],
                        devdoc=result["devdoc"],
                    )
                )

        return contract_types
