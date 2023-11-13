import json
import os
import re
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Union

from ape._pydantic_compat import BaseModel, validator
from ape.exceptions import CompilerError
from ape.logging import logger
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion
from packaging.version import Version
from packaging.version import Version as _Version
from solcx.install import get_executable
from solcx.wrapper import get_solc_version as get_solc_version_from_binary

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


def get_pragma_spec_from_path(source_file_path: Union[Path, str]) -> Optional[SpecifierSet]:
    """
    Extracts pragma information from Solidity source code.

    Args:
        source_file_path (Union[Path, str]): Solidity source file path.

    Returns:
        ``packaging.specifiers.SpecifierSet``
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

    # The following logic handles the case where the user puts a space
    # between the operator and the version number in the pragma string,
    # such as `solidity >= 0.4.19 < 0.7.0`.
    pragma_parts = pragma_match.groups()[0].split()

    def _to_spec(item: str) -> str:
        item = item.replace("^", "~=")
        if item and item[0].isnumeric():
            return f"=={item}"
        elif item and len(item) >= 2 and item[0] == "=" and item[1] != "=":
            return f"={item}"

        return item

    pragma_parts_fixed = []
    builder = ""
    for sub_part in pragma_parts:
        if not any(c.isnumeric() for c in sub_part):
            # Handle pragma with spaces between constraint and values
            # like `>= 0.6.0`.
            builder += sub_part
            continue
        elif builder:
            spec = _to_spec(f"{builder}{sub_part}")
            builder = ""
        else:
            spec = _to_spec(sub_part)

        pragma_parts_fixed.append(spec)

    try:
        return SpecifierSet(",".join(pragma_parts_fixed))
    except ValueError as err:
        logger.error(str(err))
        return None


def load_dict(data: Union[str, dict]) -> Dict:
    return data if isinstance(data, dict) else json.loads(data)


def add_commit_hash(version: Union[str, Version]) -> Version:
    vers = Version(f"{version}") if isinstance(version, str) else version
    has_commit = len(f"{vers}") > len(vers.base_version)
    if has_commit:
        # Already added.
        return vers

    solc = get_executable(version=vers)
    return get_solc_version_from_binary(solc, with_commit_hash=True)


def verify_contract_filepaths(contract_filepaths: List[Path]) -> Set[Path]:
    invalid_files = [p.name for p in contract_filepaths if p.suffix != Extension.SOL.value]
    if not invalid_files:
        return set(contract_filepaths)

    sources_str = "', '".join(invalid_files)
    raise CompilerError(f"Unable to compile '{sources_str}' using Solidity compiler.")


def select_version(pragma_spec: SpecifierSet, options: Sequence[Version]) -> Optional[Version]:
    choices = sorted(list(pragma_spec.filter(options)), reverse=True)
    return choices[0] if choices else None


def strip_commit_hash(version: Union[str, Version]) -> Version:
    """
    Version('0.8.21+commit.d9974bed') => Version('0.8.21')> the simple way.
    """
    return Version(f"{str(version).split('+')[0].strip()}")
