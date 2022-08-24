import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from ape.logging import logger
from semantic_version import NpmSpec, Version  # type: ignore
from solcx.install import get_executable  # type: ignore
from solcx.wrapper import _get_solc_version  # type: ignore


def get_import_lines(source_paths: Set[Path]) -> Dict[Path, List[str]]:
    imports_dict: Dict[Path, List[str]] = {}

    for filepath in source_paths:
        import_set = set()
        source_lines = filepath.read_text().splitlines()
        line_number = 0
        for ln in source_lines:
            if not ln.startswith("import"):
                continue

            if ";" in ln:
                import_str = ln

            else:
                # Is multi-line.
                import_str = ln
                start_index = line_number + 1
                for next_ln in source_lines[start_index:]:
                    import_str += f" {next_ln.strip()}"

                    if ";" in next_ln:
                        break

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


def strip_commit_hash(version: Version) -> Version:
    return Version(str(version).split("+")[0].strip())


def get_version_with_commit_hash(version: Union[str, Version]) -> Version:
    executable = get_executable(version)
    return _get_solc_version(executable, with_commit_hash=True)
