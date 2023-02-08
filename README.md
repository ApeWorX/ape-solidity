# Quick Start

Compile Solidity contracts.

## Dependencies

- [python3](https://www.python.org/downloads) version 3.8 or greater, python3-dev

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

To link libraries, add them to your `ape-config.yaml` file:

```yaml
solidity:
  libraries:
    subfolder/MySolidityFile.sol:
      MyLibrary: "0x3387FE7316B9418152F338E5A90D3a2C2888a1FF"
```

**WARNING**: If your library address changes across networks, you have to edit your config to use the new address and force re-compile.
Additionally, if you first had to compile and deploy your library, you will have to add the configuration and force a re-compile.

When using libraries in local projects, make sure to deploy and add your libraries using the `set_library()` method:

```python
import pytest


@pytest.fixture
def contract(accounts, project):
    account = accounts[0]
    library = project.Set.deploy(sender=account)
    solidity = project.compiler_manager.registered_compilers[".sol"]
    solidity.set_library(library)
    
    # Would not work without first deploying / adding the library it needs.
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
