# tree

A small Python CLI for scanning a project tree and writing the result to a file.

## Features

- Java, Web, and Unknown profiles
- File filtering by environment
- Basic annotations for Java and React/TypeScript files
- Collapsed `node_modules` on Web projects
- Text or JSON output
- Unicode or ASCII tree drawing

## Quick start

**Requirements:** Python 3.11 or later.

Run this from the project root you want to inspect:

```bash
python tree_cli.py
```

This writes `Structure.txt` in the current project directory.

## Options

```bash
python tree_cli.py --root /path/to/project
python tree_cli.py --output /tmp/my-tree.txt
python tree_cli.py --ascii
python tree_cli.py --json
python tree_cli.py --env java
python tree_cli.py --env web
python tree_cli.py --no-node-modules
python tree_cli.py --exclude generated --exclude fixtures
python tree_cli.py --debug-detect
```

Warnings and errors go to stderr.
