import json
import re
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from ape.exceptions import CompilerError
from ape.utils import pragma_str_to_specifier_set
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from solcx.install import get_executable
from solcx.wrapper import get_solc_version as get_solc_version_from_binary

OUTPUT_SELECTION = [
    "abi",
    "bin-runtime",
    "devdoc",
    "userdoc",
    "evm.bytecode.object",
    "evm.bytecode.sourceMap",
    "evm.deployedBytecode.object",
]


class Extension(Enum):
    SOL = ".sol"


def get_import_lines(source_paths: Iterable[Path]) -> dict[Path, list[str]]:
    imports_dict: dict[Path, list[str]] = {}
    for filepath in source_paths:
        import_set = set()
        if not filepath or not filepath.is_file():
            continue

        source_lines = filepath.read_text().splitlines()
        num_lines = len(source_lines)
        for line_number, ln in enumerate(source_lines):
            if not ln.startswith("import"):
                continue

            import_str = ln
            second_line_number = line_number
            while ";" not in import_str:
                second_line_number += 1
                if second_line_number >= num_lines:
                    raise CompilerError("Import statement missing semicolon.")

                next_line = source_lines[second_line_number]
                import_str += f" {next_line.strip()}"

            import_set.add(import_str)
            line_number += 1

        imports_dict[filepath] = list(import_set)

    return imports_dict


def get_pragma_spec_from_path(source_file_path: Union[Path, str]) -> Optional[SpecifierSet]:
    """
    Extracts pragma information from Solidity source code.

    Args:
        source_file_path (Union[Path, str]): Solidity source file path.

    Returns:
        ``Optional[packaging.specifiers.SpecifierSet]``
    """
    path = Path(source_file_path)
    if not path.is_file():
        return None

    source_str = path.read_text()
    return get_pragma_spec_from_str(source_str)


def get_pragma_spec_from_str(source_str: str) -> Optional[SpecifierSet]:
    if not (
        pragma_match := next(
            re.finditer(r"(?:\n|^)\s*pragma\s*solidity\s*([^;\n]*)", source_str), None
        )
    ):
        return None  # Try compiling with latest

    return pragma_str_to_specifier_set(pragma_match.groups()[0])


def load_dict(data: Union[str, dict]) -> dict:
    return data if isinstance(data, dict) else json.loads(data)


def add_commit_hash(version: Union[str, Version]) -> Version:
    vers = Version(f"{version}") if isinstance(version, str) else version
    has_commit = len(f"{vers}") > len(vers.base_version)
    if has_commit:
        # Already added.
        return vers

    solc = get_executable(version=vers)
    return get_solc_version_from_binary(solc, with_commit_hash=True)


def get_versions_can_use(pragma_spec: SpecifierSet, options: Iterable[Version]) -> list[Version]:
    return sorted(list(pragma_spec.filter(options)), reverse=True)


def select_version(pragma_spec: SpecifierSet, options: Iterable[Version]) -> Optional[Version]:
    choices = get_versions_can_use(pragma_spec, options)
    return choices[0] if choices else None


def strip_commit_hash(version: Union[str, Version]) -> Version:
    """
    Version('0.8.21+commit.d9974bed') => Version('0.8.21')> the simple way.
    """
    return Version(f"{str(version).split('+')[0].strip()}")
