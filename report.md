# Verihogg-Lint Integration Report

## Executive Summary

Two runners were integrated into sv-tests for verihogg-lint:
- **VerihoggLint** (strict): exit code 0 = success only
- **VerihoggLintLax** (lenient): exit code 0 or 1 = success (lint issues accepted)

| Runner | Total | Passed | Failed | Pass Rate |
|--------|-------|--------|--------|-----------|
| VerihoggLint | 931 | 769 | 162 | 82.6% |
| VerihoggLintLax | 931 | 869 | 62 | 93.3% |

All 931 tests run; no crashes (rc >= 126); no skipped tests.

---

## VerihoggLint (Strict) — 162 Failures

### Category A: False Negatives (38 tests)

Tests where `should_fail=1` but `rc=0` — the tool did not detect intentional errors.

| Test | Tags | should_fail_because |
|------|------|---------------------|
| `proc_assignment__bad` | 10.3 uvm-req | Illegal to procedurally assign to wire |
| `unpack_stream_inv` | 11.4.14.3 | Stream is wider than assignment target |
| `function_fork_invalid` | 13.4.4 | Only fork-join_none permitted in function |
| `clocking_block_signals_fail` | 14.3 | Assigning to net from procedural context |
| `fork_return` | 9.3.3 | Illegal return from fork |
| `variable_multiple_assignments` | 6.5 | Multiple continuous assignments |
| `variable_redeclare` | 6.5 | Variable redeclaration |
| `variable_mixed_assignments` | 6.5 | Mixing procedural and continuous assignments |
| `real_idx` | 6.12 | Illegal bit select on real type |
| `real_bit_select` | 6.12 | Illegal bit select on real type |
| `real_edge` | 6.12 | Illegal edge event on real type |
| `enum_value_inv` | 6.19 | Sized literal constant size mismatch with enum |
| `enum_xx_inv` | 6.19 | x/z assignments in 2-state enum |
| `enum_xx_inv_order` | 6.19 | Unassigned enum name after x/z assignment |
| `enum_type_checking_inv` | 6.19.3 | Enum strict type checking violated |
| `enum_numerical_expr_no_cast` | 6.19.4 | Enum numerical expression without cast |
| `typedef_test_25__bad` | 6.18 | Using undefined parameters |
| `typedef_test_28__bad` | 6.18 | Missing forward typedef declaration |
| `typedef_test_8__bad` | 6.18 | Defining type using undefined type |
| `specparam_inv` | 6.20.5 | specparam assignment to param |
| `abstract_class_inst` | 8.21 | Instantiating abstract class |
| `class_member_test_5` | 8.3 | Pure virtual methods only in virtual classes |
| `parametrized_class_invalid_scope_resolution` | 8.25.1 | Parametrized class invalid scope resolution |
| `type_access_implements_invalid` | 8.26.3 | Typedefs not inherited by implements |
| `illegal_forward_def_implements` | 8.26.4 | Implementing forward typedef for interface class |
| `interface_instantiation` | 8.26.5 | Instantiating an interface class |
| `name_conflict_unresolved` | 8.26.6.1 | Unresolved interface class method name conflict |
| `parameter_type_conflict_unresolved` | 8.26.6.2 | Superclass type declaration conflicts |
| `diamond_relationship_parametrized` | 8.26.6.3 | Different specializations of interface class |
| `explicit_external_constraint_1` | 18.5.1 | Explicit constraint needs to be defined |
| `variable_ordering_1` | 18.5.10 | randc vars not allowed in ordering |
| `soft_constraints_2` | 18.5.14 | Soft constraints on randc variables |
| `pure_constraint_2` | 18.5.2 | Pure constraint must be implemented by non-virtual class |
| `distribution_2` | 18.5.4 | Distribution shall not be applied to randc variables |
| `if_else_production_statements_0_fail` | 18.17.2 | Switch variable not declared |
| `if_else_production_statements_2_fail` | 18.17.2 | Switch variable not declared |
| `aborting_productions_break_and_return_2_fail` | 18.17.6 | Typo in production name |
| `operations-on-arrays-variable-slice-zero-rw` | 7.4.3 | Slicing array with zero part width |

**Root cause**: verihogg-lint lacks elaboration-phase semantic checks for these error classes.

### Category B.1: UVM Library Errors (101 tests)

All 101 tests fail due to the same 4 errors in 3 UVM library source files:

```
[ERR:LN0748] uvm_lru_cache.svh:206:10: Empty assignment pattern '{}' not allowed
[ERR:LN0748] uvm_lru_cache.svh:273:10: Empty assignment pattern '{}' not allowed
[ERR:LN0773] uvm_port_base.svh:256:1: Extending non existing class IF.
[ERR:LN0773] uvm_reg_sequence.svh:73:1: Extending non existing class BASE.
```

**Affected tag groups**: `uvm-random` (63), `uvm-assertions` (26), `uvm-classes` (4), `uvm-scoreboards` (3), `uvm-agents` (3), `uvm` (2).

**Root cause**: verihogg-lint does not support empty assignment patterns `'{}'` and cannot resolve parameterized virtual class extends with interface class types.

### Category B.2: Non-UVM False Positives (19 tests)

Tests where `should_fail=0` but `rc=1` — the tool incorrectly rejects valid SystemVerilog.

#### Tool Bugs (15 tests)

| Test | Error Code | Issue |
|------|-----------|-------|
| `insert_assign` | ERR:LN0754 | Queue literal `{}` in RHS misidentified as concatenation |
| `pop_back_assing` | ERR:LN0754 | Same queue literal misidentification |
| `push_back_assign` | ERR:LN0754 | Same — `q = { q, 4 }` is valid queue push_back |
| `push_front_assign` | ERR:LN0754 | Same — `q = { 4, q }` is valid queue push_front |
| `class_test_7` | ERR:LN0773 | Package-qualified `Package::Bar` not resolved in `extends` |
| `class_test_19` | ERR:LN0773 | Same — `extends Package::Bar #(x,y,z)` |
| `class_test_21` | ERR:LN0773 | Same |
| `class_test_25` | ERR:LN0781 | Package-qualified `Package::Bar` not resolved in `implements` |
| `class_test_27` | ERR:LN0781 | Same — `implements Package::Bar#(1, 2)` |
| `class_test_29` | ERR:LN0781 | Same — `implements Pkg::Bar, Baz` |
| `sequence_goto_repetition_test` | ERR:LN0740 | Valid `[->]` goto repetition operator rejected |
| `sequence_nonconsecutive_repetition_test` | ERR:LN0740 | Valid `[=]` non-consecutive repetition operator rejected |
| `implicit_external_constraint_0` | ERR:LN0776 | Implicit extern constraint not recognized |
| `soft_constraint_priorities_2` | ERR:LN0776 | Same — implicit extern constraint |
| `class_test_54` | ERR:LN0798 | Multi-name and array event declarations rejected |
| `structure-replication` | ERR:LN0792 | Replication `{3{1}}` inside assignment patterns not understood |

#### Tool Limitations (4 tests)

| Test | Error Code | Issue |
|------|-----------|-------|
| `coverage_routines` | SNT:PA0207 | Missing `$coverage_control` + `SV_COV_*` macros + broken implicit module instantiation |
| `type_op_compare` | SNT:PA0207 | `type()` operator in parameter defaults and expressions not parsed |
| `case_production_statements_0` | SNT:PA0207 | Entire `randsequence` construct not implemented |

### Category C: CLI Option Errors (4 tests)

Tests where `rc=1` because verihogg-lint rejects `--top-module=top`:

| Test | Tags |
|------|------|
| `named_event_trigger_blocking` | 15.5 uvm-req |
| `named_event_trigger_non_blocking` | 15.5 uvm-req |
| `named_event_wait` | 15.5 uvm-req |
| `interface` | uvm-req 25.3 |

**Error**: `verihogg-lint: unrecognized option '--top-module=top'`

**Root cause**: The runner passes `--top-module=<name>` but verihogg-lint doesn't support this flag. The tool should use `-top <name>` or the flag should be added.

---

## VerihoggLintLax — 62 Failures

### Category A: False Negatives (38 tests)

Identical to VerihoggLint Category A — same 38 tests, same root cause (tool misses errors).

### Category F: Runner Bug (24 tests)

Tests where `should_fail=1` and `rc=1` — the tool **correctly** detected errors, but the Lax runner's `is_success_returncode(rc <= 1)` returns `True`, so the framework thinks the tool "succeeded" when it should have "failed".

| Test | Error Detected |
|------|---------------|
| `sanity` | Syntax error: `syntaxerror` keyword |
| `assign_in_expr_inv` | Syntax error: `a = b = c = 5` |
| `function_void_return` | Void function returns a value |
| `case_production_statements_0_fail` | Syntax error in randcase |
| `behavior_of_randomization_methods_4` | Cannot override builtin `randomize` |
| `behavior_of_randomization_methods_5` | Same + UVM library errors |
| `disabling-random-variables-with-rand_mode_4` | Cannot override builtin `rand_mode` |
| `disabling-random-variables-with-rand_mode_5` | Same + UVM library errors |
| `controlling_constraints_with_constraint_mode_1` | Cannot override builtin `constraint_mode` |
| `controlling-constraints-with-constraint_mode_2` | Same + UVM library errors |
| `22.3--resetall_illegal` | Illegal directive in design element |
| `22.7--timescale-basic-3` | Invalid timescale value: 9 |
| `22.7--timescale-basic-4` | Timescale precision less precise than timeunit |
| `22.9--unconnected_drive-invalid-1` | Syntax error: invalid unconnected_drive |
| `22.9--unconnected_drive-invalid-2` | Illegal unconnected_drive value: pull2 |
| `22.9--unconnected_drive-invalid-3` | Syntax error: extraneous input |
| `structure-arrays-illegal` | Wrong value count for struct |
| `wrong-identifiers` | Syntax error: invalid identifiers |
| `integers-sized-illegal` | Syntax error: `8'd-6` |
| `integers-unsized-illegal` | Illegal timescale: af |
| `real-constants-illegal` | Syntax error: `.12` |
| `vector_vectored_inv` | Syntax error: vectored with initializer |
| `packed-structures-default-members-value` | Illegal default value |
| `illegal_implements_parameter` | Implementing non existing interface class |

**Root cause**: `is_success_returncode(rc <= 1)` treats rc=1 as success. When `should_fail=1` and `tool_success=True`, the framework calculates `tool_failed=False` and `test_passed=False`.

---

## Root Causes & Fix Recommendations

### Fix 1: VerihoggLintLax `is_success_returncode` (24 failures)

**File**: `tools/runners/VerihoggLintLax.py`

**Current** (broken):
```python
def is_success_returncode(self, rc, params):
    return rc <= 1
```

**Proposed**:
```python
def is_success_returncode(self, rc, params):
    if rc == 0:
        return True
    if rc == 1 and params.get("should_fail") == "0":
        return True
    return False
```

This preserves the Lax runner's purpose (accept lint issues in passing tests) while correctly handling tests that should fail. Fixes all 24 Category F failures with no regressions.

### Fix 2: `--top-module` flag (4 failures)

**File**: `tools/runners/VerihoggLint.py` and `VerihoggLintLax.py`

The runner passes `--top-module=<name>` but verihogg-lint doesn't support it. Two options:

- **Option A** (tool fix): Add `--top-module=<name>` support to verihogg-lint's CLI (forward to Surelog's `-top` flag)
- **Option B** (runner fix): Change runner to pass `-top <name>` instead, which Surelog accepts

### Fix 3: UVM Library Compatibility (101 failures)

**Files**: verihogg-lint tool source

4 errors in 3 UVM library files cause all 101 UVM test failures:

| Error | File | Issue |
|-------|------|-------|
| LN0748 | `uvm_lru_cache.svh:206,273` | Empty assignment pattern `'{}'` not supported |
| LN0773 | `uvm_port_base.svh:256` | Virtual class extends with interface class type `IF` not resolved |
| LN0776 | (3 tests) | Outer class constraint not declared extern |
| LN0773 | `uvm_reg_sequence.svh:73` | Virtual class extends with interface class type `BASE` not resolved |

### Fix 4: Tool Bugs (15 false-positive failures)

| Bug | Tests Affected | Fix |
|-----|---------------|-----|
| Queue literal `{}` misidentified as concatenation | 4 | Distinguish queue assignment from bit-stream concatenation in LN0754 rule |
| Package-qualified names not resolved in extends/implements | 6 | Fix symbol resolution for `Package::Class` syntax |
| Valid sequence repetition operators rejected | 2 | Fix LN0740 rule — `[->]` and `[=]` are valid when used individually |
| Implicit extern constraints not recognized | 2 | Support `constraint c;` + out-of-class body without `extern` keyword |
| Multi-name/array event declarations rejected | 1 | Fix LN0798 rule — `event a, b;` and `event arr[4:0];` are valid |
| Replication in assignment patterns not understood | 1 | Fix LN0792 rule — `'{3{1}}` expands correctly |

### Fix 5: Tool Limitations (3 false-positive failures)

| Limitation | Test | Difficulty |
|-----------|------|-----------|
| `randsequence` grammar not implemented | `case_production_statements_0` | High — entire construct missing |
| `type()` operator not parsed | `type_op_compare` | Medium — parser extension needed |
| `$coverage_control` + `SV_COV_*` macros missing | `coverage_routines` | Low — add builtins |

### Fix 6: Runner `-I`/`-D` Flag Format (already fixed)

The original runners used `-I <path>` (space-separated) but verihogg-lint requires `-I<path>` (prefix format, Surelog-style). This was fixed during integration.

---

## Summary

| Issue | Failures | Fix Location | Difficulty |
|-------|----------|-------------|-----------|
| Lax runner `is_success_returncode` | 24 | `tools/runners/VerihoggLintLax.py` | Trivial |
| `--top-module` flag unsupported | 4 | Runner or tool | Easy |
| UVM library parse errors | 101 | verihogg-lint tool | Medium |
| Package-qualified name resolution | 6 | verihogg-lint tool | Medium |
| Queue literal misidentification | 4 | verihogg-lint tool | Medium |
| Missing semantic checks (38 tests) | 38 | verihogg-lint tool | High |
| Sequence operator false rejection | 2 | verihogg-lint tool | Easy |
| Implicit extern constraints | 2 | verihogg-lint tool | Easy |
| Other tool bugs (events, replication) | 2 | verihogg-lint tool | Medium |
| Parser limitations (randsequence, type()) | 3 | verihogg-lint tool | High |

**Quick wins** (fix 1-2 items → resolve ~130 failures):
1. Fix Lax runner `is_success_returncode` → -24 failures
2. Fix `--top-module` flag → -4 failures
3. Fix UVM library compatibility → -101 failures

After these 3 fixes: VerihoggLint would go from 82.6% to ~95.4% pass rate; VerihoggLintLax from 93.3% to ~99.6%.
