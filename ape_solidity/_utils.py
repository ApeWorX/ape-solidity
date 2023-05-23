import json
import os
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from ape.exceptions import CompilerError
from ape.logging import logger
from packaging.version import InvalidVersion
from packaging.version import Version as _Version
from pydantic import BaseModel, validator
from semantic_version import NpmSpec, Version  # type: ignore
from solcx.exceptions import SolcError  # type: ignore
from solcx.install import get_executable  # type: ignore
from solcx.wrapper import VERSION_REGEX  # type: ignore

from ape_solidity.exceptions import IncorrectMappingFormatError

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


class ImportRemapping(BaseModel):
    entry: str
    packages_cache: Path

    @validator("entry")
    def validate_entry(cls, value):
        if len((value or "").split("=")) != 2:
            raise IncorrectMappingFormatError()

        return value

    @property
    def _parts(self) -> List[str]:
        return self.entry.split("=")

    # path normalization needed in case delimiter in remapping key/value
    # and system path delimiter are different (Windows as an example)
    @property
    def key(self) -> str:
        return os.path.normpath(self._parts[0])

    @property
    def name(self) -> str:
        suffix_str = os.path.normpath(self._parts[1])
        return suffix_str.split(os.path.sep)[0]

    @property
    def package_id(self) -> Path:
        suffix = Path(self._parts[1])
        data_folder_cache = self.packages_cache / suffix

        try:
            _Version(suffix.name)
            if not suffix.name.startswith("v"):
                suffix = suffix.parent / f"v{suffix.name}"

        except InvalidVersion:
            # The user did not specify a version_id suffix in their mapping.
            # We try to smartly figure one out, else error.
            if len(Path(suffix).parents) == 1 and data_folder_cache.is_dir():
                version_ids = [d.name for d in data_folder_cache.iterdir()]
                if len(version_ids) == 1:
                    # Use only version ID available.
                    suffix = suffix / version_ids[0]

                elif not version_ids:
                    raise CompilerError(f"Missing dependency '{suffix}'.")

                else:
                    options_str = ", ".join(version_ids)
                    raise CompilerError(
                        "Ambiguous version reference. "
                        f"Please set import remapping value to {suffix}/{{version_id}} "
                        f"where 'version_id' is one of '{options_str}'."
                    )

        return suffix


class ImportRemappingBuilder:
    def __init__(self, contracts_cache: Path):
        self.import_map: Dict[str, str] = {}
        self.dependencies_added: Set[Path] = set()
        self.contracts_cache = contracts_cache

    def add_entry(self, remapping: ImportRemapping):
        path = remapping.package_id
        if not str(path).startswith(f".cache{os.path.sep}"):
            path = Path(".cache") / path

        self.import_map[remapping.key] = str(path)


def get_import_lines(source_paths: Set[Path]) -> Dict[Path, List[str]]:
    imports_dict: Dict[Path, List[str]] = {}

    for filepath in source_paths:
        import_set = set()
        if not filepath.is_file():
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


def load_dict(data: Union[str, dict]) -> Dict:
    return data if isinstance(data, dict) else json.loads(data)


def get_version_with_commit_hash(version: Union[str, Version]) -> Version:
    # Borrowed from:
    # https://github.com/iamdefinitelyahuman/py-solc-x/blob/master/solcx/wrapper.py#L15-L28
    if "+commit" in str(version):
        return Version(str(version))

    executable = get_executable(version)
    stdout_data = subprocess.check_output([str(executable), "--version"], encoding="utf8")
    try:
        match = next(re.finditer(VERSION_REGEX, stdout_data))
        version_str = "".join(match.groups())
    except StopIteration:
        raise SolcError("Could not determine the solc binary version")

    return Version.coerce(version_str)


def verify_contract_filepaths(contract_filepaths: List[Path]) -> Set[Path]:
    invalid_files = [p.name for p in contract_filepaths if p.suffix != Extension.SOL.value]
    if not invalid_files:
        return set(contract_filepaths)

    sources_str = "', '".join(invalid_files)
    raise CompilerError(f"Unable to compile '{sources_str}' using Solidity compiler.")
