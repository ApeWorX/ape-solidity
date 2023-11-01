# Quick Start

Compile Solidity contracts.

## Dependencies

- [python3](https://www.python.org/downloads) version 3.8 up to 3.11.

## Installation

### via `pip`

You can install the latest release via [`pip`](https://pypi.org/project/pip/):

```bash
pip install ape-solidity
```

### via `setuptools`

You can clone the repository and use [`setuptools`](https://github.com/pypa/setuptools) for the most up-to-date version:

```bash
git clone https://github.com/ApeWorX/ape-solidity.git
cd ape-solidity
python3 setup.py install
```

## Quick Usage

In your project, make sure you have a `contracts/` directory containing Solidity files (`.sol`).

Then, while this plugin is installed, compile your contracts:

```bash
ape compile
```

The byte-code and ABI for your contracts should now exist in a `__local__.json` file in a `.build/` directory.

### Solidity Versioning

By default, `ape-solidity` tries to use the best versions of Solidity by looking at all the source files' pragma specifications.
However, it is often better to specify a version directly.
If you know the best version to use, set it in your `ape-config.yaml`, like this:

```yaml
solidity:
  version: 0.8.14
```

### Dependency Mapping

To configure import remapping, use your project's `ape-config.yaml` file:

```yaml
solidity:
  import_remapping:
    - "@openzeppelin=path/to/open_zeppelin/contracts"
```

If you are using the `dependencies:` key in your `ape-config.yaml`, `ape` can automatically
search those dependencies for the path.

```yaml
dependencies:
  - name: OpenZeppelin
    github: OpenZeppelin/openzeppelin-contracts
    version: 4.4.2

solidity:
  import_remapping:
    - "@openzeppelin=OpenZeppelin/4.4.2"
```

Once you have your dependencies configured, you can import packages using your import keys:

```solidity
import "@openzeppelin/token/ERC721/ERC721.sol";
```

### Library Linking

To compile contracts that use libraries, you need to add the libraries first.
Use the `add_library()` method from the `ape-solidity` compiler class to add the library.
A typical flow is:

1. Deploy the library.
2. Call `add_library()` using the Solidity compiler plugin, which will also re-compile contracts that need the library.
3. Deploy and use contracts that require the library.

For example:

```python
import pytest


@pytest.fixture
def contract(accounts, project, compilers):
    # Deploy the library.
    account = accounts[0]
    library = project.Set.deploy(sender=account)
    
    # Add the library to Solidity (re-compiles contracts that use the library).
    compilers.solidity.add_library(library)

    # Deploy the contract that uses the library.
    return project.C.deploy(sender=account)
```

### Compiler Settings

When using `ape-solidity`, your project's manifest's compiler settings will include standard JSON output.
You should have one listed `compiler` per `solc` version used in your project.
You can view your current project manifest, including the compiler settings, by doing:

```python
from ape import project

manifest = project.extract_manifest()

for compiler_entry in manifest.compilers:
    print(compiler_entry.version)
    print(compiler_entry.settings)
```

**NOTE**: These are the settings used during contract verification when using the [Etherscan plugin](https://github.com/ApeWorX/ape-etherscan).

#### `--via-IR` Yul IR Compilation Pipeline

You can enable `solc`'s `--via-IR` flag by adding the following values to your `ape-config.yaml`

```yaml
solidity:
  via_ir: True
```
