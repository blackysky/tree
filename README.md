# tree

A lightweight Python CLI tool that inspects a project directory, detects its development
environment, and writes an annotated file tree to an output file.

---

## Why this tool exists

Per-project tree scripts tend to accumulate in repositories and diverge over
time. This tool replaces them with a single reusable utility that understands
common project structures, excludes noise directories automatically, and
produces consistent, deterministic output suitable for version control and
code review.

## Features

- Heuristic environment detection (Java, Web, or Unknown)
- Environment-aware file filtering and directory exclusion
- File annotations: type labels for Java sources, component and hook labels
  for TypeScript/React files
- Collapsed display of large dependency directories (e.g. `node_modules`)
- JSON output via `--json`
- Unicode tree characters by default; ASCII fallback available
- Manual environment override via `--env`
- Detection diagnostics via `--debug-detect`
- Full exclusion of `node_modules` via `--no-node-modules`
- Deterministic output: identical input always produces identical output

## Supported environments

| Environment | Detected by                                                          | Included extensions                                           | Annotations                                                              |
|-------------|----------------------------------------------------------------------|---------------------------------------------------------------|--------------------------------------------------------------------------|
| Java        | `pom.xml`, `build.gradle`, `src/main/java`, `.java` files            | `.java` `.sql` `.properties` `.yaml` `.yml`                   | `[class]` `[interface]` `[enum]` `[record]` `[annotation]` `[commented]` |
| Web         | `package.json`, `tsconfig.json`, `node_modules/`, `.ts`/`.tsx` files | `.tsx` `.ts` `.html` `.css` `.js` `.json` `.md` `.svg` `.png` | `[component]` `[hook]`                                                   |
| Unknown     | fallback when no confident match is found                            | `.py` `.js` `.ts` `.java` `.md` `.txt` `.yml` `.yaml` `.json` | none                                                                     |

Detection is heuristic. Each clue contributes a weighted score. A result is
reported as confident only when one environment's score exceeds the other by
at least 2 points. Ambiguous or zero-score cases fall back to the Unknown
profile with a warning printed to stderr.

---

## Quick start

**Requirements:** Python 3.11 or later.

Run from the project root you want to inspect:

```bash
python tree_cli.py
```

This detects the environment, scans the current directory, and writes
`Structure.txt` to the project root.

**Scan a specific directory:**

```bash
python tree_cli.py --root /path/to/project
```

**Override environment detection:**

```bash
python tree_cli.py --env java
python tree_cli.py --env web
```

**Write output to a specific file:**

```bash
python tree_cli.py --output /tmp/my-tree.txt
```

**Use ASCII characters instead of Unicode:**

```bash
python tree_cli.py --ascii
```

**Exclude additional directories:**

```bash
python tree_cli.py --exclude generated --exclude fixtures
```

**Inspect what detection decided and why:**

```bash
python tree_cli.py --debug-detect
```

**Exclude `node_modules` entirely instead of collapsing it:**

```bash
python tree_cli.py --no-node-modules
```

**Write JSON output instead of plain text:**

```bash
python tree_cli.py --json
```

## CLI options

| Option              | Default                                                    | Description                                                                                      |
|---------------------|------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `--root PATH`       | current directory                                          | Root directory to scan                                                                           |
| `--env {java,web}`  | auto-detected                                              | Override environment detection entirely                                                          |
| `--output PATH`     | `<root>/Structure.txt` (or `Structure.json` with `--json`) | Output file path                                                                                 |
| `--ascii`           | off                                                        | Use ASCII tree characters instead of Unicode                                                     |
| `--exclude DIR`     | none                                                       | Additional directory names to exclude (by name, not path). Repeatable.                           |
| `--debug-detect`    | off                                                        | Print detection scores, confidence, and matched clues to stderr. No effect on output file.       |
| `--no-node-modules` | off                                                        | Exclude `node_modules` entirely instead of collapsing it. No effect on Java or Unknown profiles. |
| `--json`            | off                                                        | Write JSON output instead of plain text. Default filename becomes `Structure.json`.              |

Warnings and errors are written to stderr. The output file is the only thing
written to disk.

## Example output (Unicode)

```
Project: /home/user/projects/my-service
Environment: Java (confident)

my-service/
├── pom.xml
├── src/
│   └── main/
│       └── java/
│           └── com/example/
│               ├── Application.java [class]
│               ├── UserService.java [interface]
│               ├── Role.java [enum]
│               └── legacy/
│                   └── OldClient.java [class] [commented]
└── README.md
```

Annotations appear in brackets after the filename. A file may carry more than
one annotation - for example, a fully-commented Java interface receives both
`[interface]` and `[commented]`.

When the environment could not be detected confidently:

```
Project: /home/user/projects/misc
Environment: Unknown (unknown)
```

When `--env` was used:

```
Project: /home/user/projects/my-service
Environment: Java (manual override)
```

`--debug-detect` output:

```
Detection detail:
  java score : 5
  web score  : 0
  confidence : confident
  clues matched:
    - pom.xml present at root
    - src/main/java path exists
    - .java files found at root or one level deep
```

When `--debug-detect` is combined with `--env`:

```
Detection skipped: --env override was provided.
```

---

## Notes on heuristics

Environment detection uses a fixed set of weighted clues evaluated against
the project root. It is not guaranteed to be correct. If the detected
environment looks wrong, pass `--env` to override it. Pass `--debug-detect`
to see which clues fired and what scores were accumulated.

File annotations are heuristic classifiers, not static analysis.

- `[class]`, `[interface]`, `[enum]`, `[record]`, `[annotation]`: detected by
  searching for the first declaration keyword in a `.java` file. Comment
  syntax is stripped before the search, so a declaration keyword inside a
  comment is still detected. This allows a fully-commented file to receive
  both a type label and `[commented]`.

- `[commented]`: applied when at least 80% of non-blank lines in a `.java`
  file start with a comment marker (`//`, `*`, `/*`, `*/`). Heuristic - not
  a guarantee of complete comment coverage.

- `[component]`: applied to `.tsx` files that declare a capitalised function
  or const and contain a JSX return expression. Conservative - files that
  export capitalised names without JSX are not labelled.

- `[hook]`: applied to `.ts` and `.tsx` files that export a function or const
  whose name begins with `use` followed by an uppercase letter.

- `[empty]`: applied to any zero-byte file, regardless of environment.

- `[symlink]`: applied to symlink entries. Symlinks are always recorded as
  structural facts and are never followed during traversal.

Under the Web profile, `node_modules` is
collapsed rather than excluded by default. Up to 20 entries are shown by
name; if more exist, a summary line (`... N more entries`) is appended. The
directory is never traversed for annotation purposes. Pass `--no-node-modules`
to exclude it entirely and omit it from the output altogether.

---

## Project structure

```
tree_cli.py          CLI entry point and orchestration
tree/
    shared_types.py  Node dataclass; AnnotationRule type alias
    config.py        Config dataclass; Environment and Confidence enums
    profiles.py      EnvironmentProfile constants (JAVA, WEB, UNKNOWN)
    detect.py        Heuristic environment detection
    scan.py          Directory traversal and node construction
    annotate.py      Annotation pipeline and rule implementations
    render.py        Tree formatting and output writing
```

The normal pipeline is `detect -> scan -> annotate -> render`. When `--env` is
provided, detection is skipped. `Config` is constructed once and never mutated.
No global mutable state exists.

## JSON output format

When `--json` is active, the output is a hierarchical JSON document. The
environment block always uses stable lowercase identifiers. `confidence` is
omitted when `--env` was used.

```json
{
  "project": "/home/user/projects/my-service",
  "environment": {
    "name": "java",
    "display_name": "Java",
    "manual_override": false,
    "confidence": "confident"
  },
  "root": {
    "name": "my-service",
    "type": "directory",
    "children": [
      {
        "name": "pom.xml",
        "type": "file",
        "annotations": []
      },
      {
        "name": "src",
        "type": "directory",
        "children": [
          {
            "name": "main",
            "type": "directory",
            "children": [
              {
                "name": "Application.java",
                "type": "file",
                "annotations": [
                  "class"
                ]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

Node types: `"file"`, `"directory"`, `"summary"`. Optional fields: `"symlink": true`,
`"collapsed": true` (for entries inside a collapsed directory). The plain-text
output format is not affected by `--json`.