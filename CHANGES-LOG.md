# Changes log (fork: lewisfab/kicad-mcp-pro)

Fixes for gaps in kicad-mcp-pro found while designing a 2-layer KiCad 10 board
with the server, each on its own branch. This file is for merging these branches
with another contributor's work later, so every entry stands on its own: the
problem, the fix, the test, the files touched, and which of the board project's
helper scripts (`tools/*.py`) it replaces.

Common to every branch:

- **Base:** upstream release tag `mcp-server-v4.7.0` (commit `96e69cdc`). Each
  branch holds one commit on top of it and does not depend on any other branch.
- **Commits:** Conventional Commits, DCO-signed (`git commit -s`) as
  `lewisfab <78671258+lewisfab@users.noreply.github.com>`, co-authored by Claude.
- **Tests:** each branch adds a test that fails on the base tag (on the bug, not
  on an import or setup error) and passes with the fix. Checked with
  `pytest`, `ruff format --check`, `ruff check` and `mypy src/kicad_mcp/`.
- **Not run:** `pnpm run docs:tools` (Node is not installed on the machine used).
  Branches that change a tool contract say so; regenerate the tool docs there.
- **Known test-environment failures, present without these changes:** modules
  that import `httpx` (not installed), Windows symlink tests, and a few timing or
  shared-state tests that fail only under `pytest -n auto` and pass alone
  (`test_visual_qa_large_board_runtime_and_memory`, `test_schematic_surface`,
  `test_router_isolates_two_granted_projects_and_denies_foreign_tools`).
- **Upstream:** no pull request or issue has been opened for any of these.

| Item | Branch | Commit | Replaces |
|---|---|---|---|
| 17 | `fix/validation-loops-respect-profile` | `feaffc03` | deny-list entries for two tools |
| 1 | `fix/pcb-file-tools-open-board-guard` | `b5f8bba9` | manual "close the board first" rule |
| 2 | `fix/child-sheet-instance-paths` | `39203038` | `tools/fix_instance_paths.py` |
| 3 | `fix/unique-power-references` | `235848ec` | `tools/renumber_power_refs.py` (uniqueness part) |
| 4 | `fix/freerouting-privacy-flags` | `8e4c8ede` | privacy flags in `tools/autoroute.py` |
| 5 | `fix/freerouting-exclude-nets` | `64613754` | net removal in `tools/autoroute.py` |
| 18 | `fix/stackup-mask-layer-types` | `b3b474fe` | leaving masks out of `pcb_set_stackup` |

---

## Item 17: validation loops apply the server's tool filters to auto fixers

- **Branch:** `fix/validation-loops-respect-profile`, commit `feaffc03`.
- **Problem:** `project_auto_fix_loop` and `project_full_validation_loop` run the
  "auto-applicable" fixers for failing gates (`sch_annotate`,
  `sch_add_missing_junctions`, `pcb_refill_zones`) by importing and calling their
  Python functions directly. That bypasses the server's profile filter and
  operating mode: on a `pcb_only` server the loops still edited the schematic.
- **Fix:** `ProjectValidationLoopService` takes a `tool_allowed` predicate
  (default: allow all, for standalone use). `tools/project.py` wires it to the
  server's `allowed_tool_names`, `execution_tool_names` and
  `is_tool_allowed_in_mode`. A fixer whose tool is not enabled is skipped and the
  loop logs "Skipped auto-fix {tool} for '{gate}': {tool} is not enabled on this
  server (profile or operating mode)."; it is still reported as the action to take.
- **Test:** `tests/unit/test_project_validation_loop_service.py::test_loops_skip_auto_fixers_whose_tool_is_not_allowed`,
  plus two `pcb_only` integration tests in
  `tests/integration/test_project_validation_loop.py` (full loop and auto-fix
  loop). On the base tag the blocked fixers run.
- **Files:** `src/kicad_mcp/project/validation_loops.py`,
  `src/kicad_mcp/tools/project.py`, the two test files.
- **Replaces:** no script. The board project denied both tools in
  `.claude/settings.json`; with this fix they can be allowed again on a
  `pcb_only` server.
- **Merge notes:** `_resolve_full_auto_fix` gained a `log` parameter.

## Item 1: file-based PCB writers refuse while the board is open

- **Branch:** `fix/pcb-file-tools-open-board-guard`, commit `b5f8bba9`.
- **Problem:** `pcb_add_barcode`, `pcb_add_bitmap_board_art`,
  `add_footprint_inner_layer_graphic`, `pcb_block_place` and `pcb_set_stackup`
  rewrite `.kicad_pcb` on disk with no check that KiCad has the board open. An
  open session then overwrites the change on its next save, or, for
  `pcb_set_stackup`, which always asked KiCad to revert, loses its unsaved edits.
  Other file tools (`pcb_sync_from_schematic`, `pcb_add_mounting_holes`, ...)
  already refused.
- **Fix:** the five tools take `allow_open_board: bool = False` and use the
  existing `_guard_file_based_board_edit` / `_finalize_file_based_board_edit`
  pair: refuse while the board is open unless the caller opts in, and only then
  ask KiCad to reload. `PcbStackupManagementService` gained optional
  `guard_file_based_board_edit` / `finalize_file_based_board_edit` hooks
  (`None` keeps the old behaviour for standalone use).
- **Test:** `tests/integration/test_pcb_file_tools_open_board_guard.py`,
  parametrized over the five tools. Each sets up valid inputs with the board
  closed, then opens it and checks for a refusal, unchanged file bytes and no
  reload; one more test checks the opt-in path writes and reloads once. On the
  base tag every case writes the file.
- **Files:** `src/kicad_mcp/tools/pcb.py`, `src/kicad_mcp/pcb/stackup_management.py`,
  `src/kicad_mcp/tools/pcb_stackup_management.py`, the new test,
  `tests/integration/test_pcb_tools.py` (the stackup test mocked a closed board
  yet expected a reload; it now covers the open-board opt-in), and
  `docs/evidence/progressive-disclosure-profile-snapshot.json` (regenerated with
  `scripts/profile_surface_report.py`).
- **Tool contract change:** new `allow_open_board` parameter on five tools.
  Regenerate the tool docs (`pnpm run docs:tools`).
- **Replaces:** no script. The board project kept a manual rule to close the
  board in KiCad before calling any of these five tools.
- **Merge notes:** item 18 also edits `src/kicad_mcp/tools/pcb.py`, in the
  stackup helpers near the top, not these tool bodies.

## Item 2: child-sheet symbols get hierarchical instance paths

- **Branch:** `fix/child-sheet-instance-paths`, commit `39203038`.
- **Problem:** KiCad keys each placed symbol by its sheet path from the
  top-level schematic: `/<root uuid>` on the root sheet and
  `/<root uuid>/<sheet uuid>[/...]` below it, where `<sheet uuid>` is the UUID of
  the `(sheet ...)` block in the parent. `sch_add_symbol`, `sch_build_circuit`,
  the power symbols of `sch_add_pin_labels` and `sch_add_jumper` used the UUID of
  the file being edited (or a fresh random UUID). Every symbol in a child sheet
  landed on `/<child file uuid>`, a path not in the hierarchy, so KiCad treats it
  as unannotated and can drop unlabelled nets.
- **Fix:** new module `src/kicad_mcp/schematic/instance_paths.py`
  (`find_instance_path(root_file, target)`) walks the hierarchy depth-first and
  returns the path of the target file's first occurrence. `SheetBlock` (in
  `schematic/sheet_pins.py`) now carries the sheet's own `uuid`, and
  `schematic_uuid(text)` reads a file's top-level UUID. `tools/schematic.py` finds
  the hierarchy root from `<project>.kicad_sch`, even when a child sheet is the
  active schematic, and passes an `instance_path_for` resolver to the basic,
  circuit-compilation, connectivity and lifecycle services. `place_symbol_block`
  takes `instance_path`; callers pass it only when known, so injected builders
  that predate the parameter keep working. `sch_build_circuit` on the root keeps
  its fresh root UUID. Files not reachable from the root keep the old path.
- **Test:** `tests/integration/test_child_sheet_instance_paths.py`, with a root,
  a child and a grandchild sheet: `sch_add_symbol` into each (via `sheet_file`),
  and `sch_build_circuit` with the child set as the active schematic. On the base
  tag the child gets `/<child file uuid>` and the build gets a random UUID. The
  existing root-sheet test still passes.
- **Files:** `schematic/instance_paths.py` (new), `schematic/sheet_pins.py`,
  `schematic/basic_authoring.py`, `schematic/circuit_compilation.py`,
  `schematic/connectivity_authoring.py`, `schematic/lifecycle_authoring.py`,
  `tools/schematic.py`, the new test.
- **Replaces:** `tools/fix_instance_paths.py`, which rewrote every child-sheet
  instance path to `/<root uuid>/<sheet uuid>` after each MCP edit.
- **Limits:** a sheet used more than once gets the path of its first instance;
  KiCad's annotation adds the others.
- **Merge notes:** item 3 threads another optional field through the same three
  services and adds a similar root-schematic helper in `tools/schematic.py`
  (`_project_root_schematic`; this branch's is `_hierarchy_root_file`). Expect
  textual conflicts; keep both fields and merge the two helpers into one.

## Item 3: power references are unique across the project

- **Branch:** `fix/unique-power-references`, commit `235848ec`.
- **Problem:** KiCad annotates `#PWR`/`#FLG` references project-wide, so the same
  reference on two sheets is an annotation error. `sch_build_circuit` numbered
  power symbols `#PWR001...` from 1 on every build, so every sheet built with it
  repeated them, and `PWR_FLAG` got `#PWR` instead of KiCad's `#FLG`.
  `sch_add_power_symbol` and the power terminals of `sch_add_pin_labels` took 16
  bits of a fresh UUID (`#PWR{int(uuid[:4], 16)}`), which can repeat.
- **Fix:** `schematic/references.py` gains `PowerReferenceAllocator` (lowest free
  `#PWR<nnn>`, or `#FLG<nnn>` for `PWR_FLAG`), `hierarchy_files(root)` and
  `project_references(root, target, include_target=...)`. The three writers take
  an optional `used_references` resolver (`None` keeps the old numbering);
  `tools/schematic.py` wires it to every schematic reachable from
  `<project>.kicad_sch`. `sch_build_circuit` leaves out the sheet it is replacing,
  so a rebuild can reuse its own numbers; the incremental tools include their
  target sheet.
- **Test:** `tests/integration/test_power_reference_uniqueness.py`: builds two
  child sheets, rebuilds the first, and adds power symbols to three sheets with
  a forced repeating UUID prefix. Checks for no duplicates and `#FLG` for flags.
  On the base tag both sheets carry `#PWR001-003` and the added symbols all get
  `#PWR43981`. Also `tests/unit/test_power_reference_allocator.py`.
- **Files:** `schematic/references.py`, `schematic/basic_authoring.py`,
  `schematic/circuit_compilation.py`, `schematic/connectivity_authoring.py`,
  `tools/schematic.py`, the new tests, and
  `tests/integration/test_schematic_pin_labels_power_symbols.py` (its pattern
  now accepts `#FLG`, since the PWR_FLAG it adds is now `#FLG001`).
- **Behaviour change:** `PWR_FLAG` symbols added by the server use `#FLG`.
- **Replaces:** the uniqueness part of `tools/renumber_power_refs.py`. That
  script also numbered by sheet (`#PWR<sheet>001`), a house style this fix does
  not reproduce; it allocates one project-wide sequence instead.
- **Merge notes:** see item 2 (same services, similar root helper).

## Item 4: Freerouting runs with analytics, telemetry, GUI and servers off

- **Branch:** `fix/freerouting-privacy-flags`, commit `8e4c8ede`.
- **Problem:** Freerouting 2.x sends usage analytics and telemetry by default and
  can start a GUI, a REST API server and an MCP server. The runner launched it
  (Docker image or JAR) without switching any of these off, so a headless batch
  route of a private board could phone home or open listening ports.
- **Fix:** `FREEROUTING_PRIVACY_ARGS` in `src/kicad_mcp/utils/freerouting.py`,
  added to both the Docker and the JAR command:
  `--usage_and_diagnostic_data.disable_analytics=true`,
  `--profile.allow_telemetry=false`, `--gui.enabled=false`,
  `--api_server.enabled=false`, `--mcp_server.enabled=false` (the same
  `--<section>.<key>=<value>` form the runner already used for
  `--router.max_passes`).
- **Test:** `tests/unit/test_freerouting_privacy_flags.py`, parametrized over
  Docker and JAR; it checks each flag in the command actually run. On the base
  tag none is present.
- **Files:** `src/kicad_mcp/utils/freerouting.py`, the new test.
- **Replaces:** the `PRIVACY` flag list in `tools/autoroute.py`. That script's
  proxy workaround (JVM proxy options to block network access) is deliberately
  not included.
- **Merge notes:** item 5 edits the same file near these lines (the `-inc`
  argument and `run_freerouting`); the changes do not overlap.

## Item 5: `exclude_nets` really excludes nets from Freerouting

- **Branch:** `fix/freerouting-exclude-nets`, commit `64613754`.
- **Problem:** `run_freerouting` merged `exclude_nets` into the `-inc` argument,
  which Freerouting reads as net *class* names. A net name there matches no
  class, so the "excluded" nets were routed anyway, and the autoroute summary
  listed them as ignored net classes.
- **Fix:** `-inc` carries `net_classes_to_ignore` only. With `exclude_nets`, the
  runner writes `<stem>.excluded.dsn` next to the export with those nets removed
  from the network: their `(net ...)` blocks and their names in each `(class ...)`
  member list, matched string-aware so names such as `Net-(D1-A)` work. Their pads
  stay as netless obstacles, so nothing routes them. The exported DSN is not
  changed. `FreeRoutingResult.excluded_nets` (new, default `()`) lists the names
  actually removed; names not found are logged
  (`freerouting_excluded_nets_not_found`). The autoroute summary shows them on
  their own `Excluded nets:` line.
- **Test:** `tests/unit/test_freerouting_exclude_nets.py`, parametrized over
  Docker and JAR, with a DSN holding a quoted net name and two classes. It checks
  the DSN that reaches Freerouting, the `-inc` value, the untouched export,
  `excluded_nets` and `total_nets`, plus a no-exclusion case that routes the
  export directly. On the base tag the excluded nets reach Freerouting.
- **Files:** `src/kicad_mcp/utils/freerouting.py`,
  `src/kicad_mcp/routing/autorouter.py`, the new test,
  `tests/unit/test_freerouting.py` (asserted the old `-inc` value
  `GND,PWR,SHIELD`), and `tests/unit/test_routing_autorouter_service.py`
  (summary text).
- **Replaces:** the `IGNORE_NETS` part of `prepare_dsn` in `tools/autoroute.py`
  (remove the net from the net list and from `kicad_default`). The script's
  other DSN edits (keep-outs over pours, layer limits per class, routing only a
  chosen subset of nets) are not covered.
- **Limits:** wires already in the DSN `(wiring ...)` section that name an
  excluded net are left as they are.
- **Merge notes:** see item 4 (same file, no overlap).

## Item 18: solder mask and silk stackup layers are not dielectrics

- **Branch:** `fix/stackup-mask-layer-types`, commit `b3b474fe`.
- **Problem:** `pcb_set_stackup` wrote every non-copper layer as
  `(layer dielectric N`, numbered by list position. A stackup that listed
  `F_Mask`/`B_Mask` came back from KiCad 10 as extra dielectric layers with FR4
  defaults and no mask layers. `StackupLayerSpec` defaults `material` to
  `"Copper"`, so a mask or silk layer given without a material was classed as
  copper and written as a signal layer. The impedance helper took the nearest
  non-copper neighbour as an outer trace's dielectric, so a 0.01 mm mask above
  `F.Cu` became the reference height.
- **Fix:** in `src/kicad_mcp/tools/pcb.py`, `F_SilkS`, `F_Mask`, `B_Mask` and
  `B_SilkS` are technical layers. They are never copper and are skipped when
  finding a trace's dielectric. They are written in KiCad's form,
  `(layer "F.Mask" N (type "Top Solder Mask") (thickness ...) ...)`, with the
  material only when given, and read back with their KiCad type names.
  Dielectrics are numbered 1..n among dielectrics.
- **Test:** `tests/integration/test_pcb_stackup_technical_layers.py`: silk, mask,
  copper, core, copper, mask. It checks each block's name and type, that there is
  no inherited material, the dielectric numbering, and the F.Cu impedance
  (microstrip over the 1.51 mm core). On the base tag silk and mask are written
  as copper and the core as `dielectric 3`. Also checked by hand: the output
  round-tripped through KiCad 10 (`pcbnew.LoadBoard` then `SaveBoard`) keeps
  `F.Mask`/`B.Mask` as solder-mask layers with one dielectric. The base tag's
  output turns into three dielectrics there.
- **Files:** `src/kicad_mcp/tools/pcb.py`, the new test.
- **Replaces:** no script. The board project left the mask layers out of the
  `pcb_set_stackup` input (copper, core, copper only).
- **Limits:** paste layers are not covered. The server's layer table has no
  `F_Paste`/`B_Paste`, so `pcb_set_stackup` rejects them before rendering.
- **Merge notes:** item 1 also edits `src/kicad_mcp/tools/pcb.py` (tool bodies,
  not these helpers).

---

## Found while fixing, not fixed

- `pcb_set_stackup` on a board file without a `(setup ...)` section rebuilds the
  file from a template and drops its other contents (seen on a bare
  `(kicad_pcb (footprint ...))`; a board saved by KiCad is fine).
- No `F_Paste`/`B_Paste` in the server's layer table (see item 18).
- `sch_add_jumper` writes the default project name `KiCadMCP` into the symbol
  instance instead of the active project's name.
- `sch_build_circuit` writes a `(sheet_instances (path "/" ...))` section into
  child-sheet files as well as the root.
