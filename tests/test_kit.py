import configparser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engineering_kit.cli import main as cli_main, parse_rules
from engineering_kit.guard import (PolicyError, _canonical_sha256, check, load_policy, missing_modules,
                                   relaxation_changes, render_python, render_typescript, strict_policy_checks,
                                   validate_policy)


class KitTests(unittest.TestCase):
    def policy(self, lang="python"):
        return {
            "schema_version": 1, "language": lang,
            "package": "sample" if lang == "python" else None,
            "source": "src" if lang == "typescript" else None,
            "forbidden": [["learning", "publishing"]],
            "tests": [[sys.executable, "-c", "print('tested')"]],
        }

    def setup_example(self, root, lang="python"):
        p = self.policy(lang)
        folder = root / ("src/sample" if lang == "python" else "src")
        for name in ("learning", "publishing"):
            mod = folder / name
            mod.mkdir(parents=True)
            (mod / ("__init__.py" if lang == "python" else "index.ts")).write_text("", encoding="utf-8")
        config = root / ".agent-engineering" / "policy.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(p), encoding="utf-8")
        return p

    def git_repo_with_base(self, root, old_policy):
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
        config = root / ".agent-engineering" / "policy.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(old_policy), encoding="utf-8")
        (root / "app.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)

    def test_policies_are_validated(self):
        self.assertEqual(validate_policy(self.policy())["language"], "python")
        for change in ({"schema_version": 5}, {"tests": "pytest"},
                       {"forbidden": []}, {"forbidden": [["a", "a"]]},
                       {"package": "../bad"}):
            with self.subTest(change=change), self.assertRaises(PolicyError):
                validate_policy({**self.policy(), **change})

    def test_prevents_unsafe_source_and_rule_values(self):
        for path in ("../foo", "/absolute", "src/../bad", "src space"):
            with self.subTest(path=path), self.assertRaises(PolicyError):
                validate_policy({**self.policy("typescript"), "source": path})
        for rule in ("bad", "a:a", "../x:y", "a:b:c"):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                parse_rules([rule], "python")

    def test_supports_nested_module_paths(self):
        self.assertEqual(parse_rules(["domain.learning:adapters.x"], "python"),
                         [["domain.learning", "adapters.x"]])
        self.assertEqual(parse_rules(["features/learning:adapters/transport"], "typescript"),
                         [["features/learning", "adapters/transport"]])

    def test_python_config_parses(self):
        cfg = configparser.ConfigParser()
        cfg.read_string(render_python(self.policy()))
        self.assertEqual(cfg["importlinter"]["root_package"], "sample")
        self.assertEqual(cfg["importlinter:contract:boundary-1"]["source_modules"], "sample.learning")

    def test_python_cycle_contract_is_explicit_and_backwards_compatible(self):
        self.assertNotIn("acyclic_siblings", render_python(self.policy()))
        text = render_python({**self.policy(), "check_cycles": True})
        cfg = configparser.ConfigParser()
        cfg.read_string(text)
        self.assertEqual(cfg["importlinter:contract:no-sibling-cycles"]["type"], "acyclic_siblings")
        self.assertEqual(cfg["importlinter:contract:no-sibling-cycles"]["depth"], "0")
        with self.assertRaisesRegex(PolicyError, "check_cycles"):
            validate_policy({**self.policy(), "check_cycles": "false"})

    def test_typescript_config_is_valid_javascript(self):
        rendered = render_typescript(self.policy("typescript"))
        self.assertIn('"no-circular"', rendered)
        self.assertIn('"no-learning-to-publishing"', rendered)
        self.assertIn('"tsPreCompilationDeps": true', rendered)
        self.assertNotIn('"no-circular"', render_typescript({**self.policy("typescript"), "check_cycles": False}))
        if shutil.which("node"):
            with tempfile.TemporaryDirectory() as temp:
                config = Path(temp) / "test.cjs"
                config.write_text(rendered, encoding="utf-8")
                subprocess.run(["node", "--check", str(config)], check=True)

    def test_guard_refuses_empty_module_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.policy()
            self.assertEqual(missing_modules(root, p), ["learning", "publishing"])
            with self.assertRaises(PolicyError):
                check(root, p)

    def test_guard_detects_nested_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            p["forbidden"] = [["learning.adapters", "publishing"]]
            (root / "src/sample/learning/adapters").mkdir()
            self.assertEqual(missing_modules(root, p), [])

    def test_init_generates_single_policy_and_ci(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ret = cli_main(["init", str(root), "--language", "python", "--package", "sample",
                            "--forbid", "learning:publishing", "--test", "python -m unittest"])
            self.assertEqual(ret, 0)
            policy = load_policy(root)
            self.assertEqual(policy["tests"], [["python", "-m", "unittest"]])
            self.assertTrue(policy["check_cycles"])
            self.assertTrue((root / "AGENTS.md").exists())
            self.assertIn("@AGENTS.md", (root / "CLAUDE.md").read_text())
            self.assertTrue((root / ".agent-engineering/guard.py").exists())
            ci = (root / ".github/workflows/engineering-guard.yml").read_text()
            self.assertIn("python .agent-engineering/guard.py check", ci)
            self.assertIn("import-linter", ci)
            self.assertNotIn("pip install agent-engineering-kit", ci)
            self.assertFalse((root / ".importlinter").exists())
            self.assertFalse((root / ".dependency-cruiser.cjs").exists())

    def test_init_never_overwrites_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "AGENTS.md"
            existing.write_text("CUSTOM", encoding="utf-8")
            ret = cli_main(["init", str(root), "--language", "python", "--package", "sample",
                            "--forbid", "learning:publishing", "--test", "python -m unittest"])
            self.assertEqual(ret, 2)
            self.assertEqual(existing.read_text(), "CUSTOM")

    def test_typescript_scaffold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ret = cli_main(["init", str(root), "--language", "typescript", "--source", "src",
                            "--forbid", "features/learning:infra/transport", "--test", "npm test"])
            self.assertEqual(ret, 0)
            self.assertEqual(load_policy(root)["forbidden"], [["features/learning", "infra/transport"]])
            workflow = (root / ".github/workflows/engineering-guard.yml").read_text()
            self.assertIn("npm ci", workflow)

    def test_check_runs_architecture_and_behavior(self):
        if os.name == "nt":
            self.skipTest("fake POSIX executable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            binpath = root / "bin"
            binpath.mkdir()
            fake = binpath / "lint-imports"
            fake.write_text("#!/bin/sh\ncase \"$1\" in --config) test -f \"$2\";; *) exit 7;; esac\n", encoding="utf-8")
            fake.chmod(0o755)
            old = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = str(binpath) + os.pathsep + old
                result = check(root, p)
            finally:
                os.environ["PATH"] = old
            self.assertTrue(result["passed"])
            self.assertEqual([c["name"] for c in result["checks"]], ["architecture", "behavior-1"])

    def test_behavior_failure_fails_gate_even_if_architecture_passes(self):
        if os.name == "nt":
            self.skipTest("fake POSIX executable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            p["tests"] = [[sys.executable, "-c", "import sys; sys.exit(4)"]]
            fake = root / "lint-imports"
            fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            old = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = str(root) + os.pathsep + old
                result = check(root, p)
            finally:
                os.environ["PATH"] = old
            self.assertFalse(result["passed"])
            self.assertEqual(result["checks"][1]["exit_code"], 4)

    def test_missing_tests_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            p["tests"] = []
            with self.assertRaisesRegex(PolicyError, "behavior tests"):
                check(root, p)

    def test_cli_invalid_rule_is_a_parse_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit) as cm:
                cli_main(["init", temp, "--language", "python", "--package", "ok",
                          "--forbid", "x:y;rm -rf /"])
            self.assertEqual(cm.exception.code, 2)


    def test_sync_safe_and_does_not_change_project_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = ["init", str(root), "--language", "python", "--package", "sample",
                    "--forbid", "learning:publishing", "--test", "python -m unittest"]
            self.assertEqual(cli_main(args), 0)
            policy_path = root / ".agent-engineering/policy.json"
            before = policy_path.read_text()
            self.assertEqual(cli_main(["sync", str(root)]), 0)
            self.assertEqual(policy_path.read_text(), before)
            ci = root / ".github/workflows/engineering-guard.yml"
            ci.write_text(ci.read_text() + "# local customization\n")
            self.assertEqual(cli_main(["sync", str(root)]), 2)
            self.assertIn("local customization", ci.read_text())
            self.assertEqual(policy_path.read_text(), before)

    def test_installed_standalone_guard_renders_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.setup_example(root)
            args = ["init", str(root), "--language", "python", "--package", "sample",
                    "--forbid", "learning:publishing", "--test", "python -m unittest"]
            self.assertEqual(cli_main(args), 2)  # Existing policy must not be clobbered
            result = subprocess.run([sys.executable, str(root / ".agent-engineering/guard.py"),
                                     "render-config", "--root", str(root)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("root_package = sample", result.stdout)

    def test_architecture_failure_fails_gate_even_when_behavior_passes(self):
        if os.name == "nt":
            self.skipTest("fake POSIX executable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            fake = root / "lint-imports"
            fake.write_text("#!/bin/sh\nexit 5\n", encoding="utf-8")
            fake.chmod(0o755)
            old = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = str(root) + os.pathsep + old
                result = check(root, p)
            finally:
                os.environ["PATH"] = old
            self.assertFalse(result["passed"])
            self.assertEqual([x["passed"] for x in result["checks"]], [False, True])

    def test_typescript_scans_files_not_just_directory(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = self.setup_example(root, 'typescript')
            extra = root / 'src/learning/detail.ts'
            extra.write_text('export const answer = 42;\n')
            with patch('engineering_kit.guard._run', return_value={'name': 'check', 'passed': True, 'exit_code': 0}) as mocked:
                result = check(root, policy)
            argv = mocked.call_args_list[0].args[1]
            self.assertTrue(result['passed'])
            self.assertIn('src/learning/index.ts', argv)
            self.assertIn('src/learning/detail.ts', argv)
            self.assertIn('src/publishing/index.ts', argv)
            self.assertNotIn('src', argv)

    def test_typescript_empty_scan_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = self.setup_example(root, 'typescript')
            (root / 'src/learning/index.ts').unlink()
            (root / 'src/publishing/index.ts').unlink()
            with self.assertRaisesRegex(PolicyError, 'empty architecture scan'):
                check(root, policy)

    def test_typescript_check_invokes_native_tool(self):
        if os.name == "nt":
            self.skipTest("fake POSIX executable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root, "typescript")
            (root / "tsconfig.json").write_text('{"compilerOptions": {}}')
            fake = root / "npx"
            fake.write_text("#!/bin/sh\n[ \"$1\" = \"--no-install\" ] || exit 8\n"
                            "[ \"$2\" = \"depcruise\" ] || exit 9\nexit 0\n")
            fake.chmod(0o755)
            old = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = str(root) + os.pathsep + old
                result = check(root, p)
            finally:
                os.environ["PATH"] = old
            self.assertTrue(result["passed"])

    def test_allowlist_expands_to_forbidden_edges(self):
        from engineering_kit.guard import forbidden_pairs
        policy = self.policy()
        policy["forbidden"] = []
        policy["modules"] = ["learning", "publishing", "contracts"]
        policy["allowed_dependencies"] = [["learning", "contracts"], ["publishing", "contracts"]]
        validate_policy(policy)
        forbidden = forbidden_pairs(policy)
        self.assertEqual(len(forbidden), 4)
        self.assertIn(["learning", "publishing"], forbidden)
        self.assertIn(["contracts", "learning"], forbidden)
        self.assertNotIn(["learning", "contracts"], forbidden)
        self.assertIn("sample.contracts", render_python(policy))
        self.assertIn('no-contracts-to-learning', render_typescript({**policy, "language": "typescript", "package": None, "source": "src"}))

    def test_allowlist_rejects_unknown_conflicting_and_duplicate_edges(self):
        policy = self.policy()
        policy["modules"] = ["learning", "publishing"]
        for allowed in ([["learning", "publishing"]], [["missing", "learning"]],
                        [["learning", "learning"]], [["publishing", "learning"], ["publishing", "learning"]]):
            with self.subTest(allowed=allowed), self.assertRaises(PolicyError):
                validate_policy({**policy, "allowed_dependencies": allowed})

    def test_cli_initializes_allowlist_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            result = cli_main(["init", temp, "--language", "python", "--package", "sample",
                               "--module", "learning", "--module", "publishing",
                               "--allow", "learning:publishing", "--test", "python -m unittest"])
            self.assertEqual(result, 0)
            policy = load_policy(Path(temp))
            self.assertEqual(policy["allowed_dependencies"], [["learning", "publishing"]])
            self.assertEqual(policy["forbidden"], [])

    def test_allowlist_detects_new_untracked_module(self):
        from engineering_kit.guard import ungoverned_modules
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            p["forbidden"] = []
            p["modules"] = ["learning", "publishing"]
            p["allowed_dependencies"] = []
            (root / "src/sample/rogue.py").write_text("VALUE = 1")
            self.assertEqual(ungoverned_modules(root, p), ["rogue"])
            with self.assertRaisesRegex(PolicyError, "unguarded"):
                check(root, p)
            p["unmanaged_modules"] = ["rogue"]
            self.assertEqual(ungoverned_modules(root, p), [])
            p["module_coverage"] = "off"
            self.assertEqual(ungoverned_modules(root, p), [])

    def test_allowlist_rejects_invalid_coverage_exceptions(self):
        p = self.policy()
        p["modules"] = ["learning", "publishing"]
        p["allowed_dependencies"] = []
        for change in ({"unmanaged_modules": ["learning"]},
                       {"module_coverage": "maybe"},
                       {"unmanaged_modules": ["../bad"]}):
            with self.subTest(change=change), self.assertRaises(PolicyError):
                validate_policy({**p, **change})

    def test_json_report_contains_policy_hash(self):
        from engineering_kit.guard import policy_fingerprint
        p = self.policy()
        self.assertEqual(len(policy_fingerprint(p)), 64)
        self.assertEqual(policy_fingerprint(p), policy_fingerprint(dict(reversed(list(p.items())))))

    def test_typescript_untracked_module_is_reported(self):
        from engineering_kit.guard import ungoverned_modules
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root, "typescript")
            p["forbidden"] = []
            p["modules"] = ["learning", "publishing"]
            p["allowed_dependencies"] = []
            (root / "src/rogue.ts").write_text("export const value = 1;", encoding="utf-8")
            self.assertEqual(ungoverned_modules(root, p), ["rogue"])

    def test_check_policy_error_overwrites_stale_success_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / 'report.json'
            report.write_text('{"passed": true}', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'engineering_kit/guard.py'),
                                     'check', '--root', str(root), '--json-report', str(report)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            payload = json.loads(report.read_text(encoding='utf-8'))
            self.assertFalse(payload['passed'])
            self.assertIn('error', payload)

    def test_command_timeout_policy_is_validated(self):
        for invalid in (0, -1, 3601, True, 1.5, '1'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(PolicyError, 'command_timeout_seconds'):
                validate_policy({**self.policy(), 'command_timeout_seconds': invalid})
        self.assertEqual(validate_policy({**self.policy(), 'command_timeout_seconds': 3})['command_timeout_seconds'], 3)

    def test_timeout_fails_closed_and_behavior_tests_still_run(self):
        if os.name == 'nt':
            self.skipTest('fake POSIX executable')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = self.setup_example(root)
            policy['command_timeout_seconds'] = 1
            policy['tests'] = [['/bin/true']]
            fake = root / 'lint-imports'
            fake.write_text('#!/bin/sh\nsleep 3\n', encoding='utf-8')
            fake.chmod(0o755)
            old = os.environ.get('PATH', '')
            try:
                os.environ['PATH'] = str(root) + os.pathsep + old
                result = check(root, policy)
            finally:
                os.environ['PATH'] = old
            self.assertFalse(result['passed'])
            self.assertEqual(result['checks'][0]['exit_code'], 124)
            self.assertTrue(result['checks'][1]['passed'])

    def test_typescript_doctor_requires_the_real_adapter(self):
        from engineering_kit.guard import doctor
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = self.setup_example(root, 'typescript')
            (root / '.github/workflows').mkdir(parents=True)
            (root / '.github/workflows/engineering-guard.yml').write_text('name: test\n')
            with patch('engineering_kit.guard.shutil.which', return_value='/usr/bin/npx'):
                with patch('engineering_kit.guard.subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
                    self.assertEqual(doctor(root, policy), 1)

    def test_strict_and_relaxations_are_validated(self):
        self.assertEqual(validate_policy({**self.policy(), "strict": True})["strict"], True)
        self.assertEqual(validate_policy({**self.policy(), "strict": False})["strict"], False)
        with self.assertRaises(PolicyError):
            validate_policy({**self.policy(), "strict": "yes"})
        entry = {"date_utc": "2026-10-11T08:00:00+00:00", "reason": "r", "changes": ["cycles_disabled"],
                 "prev_entry_sha256": "0" * 64}
        self.assertEqual(validate_policy({**self.policy(), "relaxations": [entry]})["relaxations"], [entry])
        for change in ({**entry, "reason": "  "}, {**entry, "changes": []},
                       {**entry, "changes": ["", "ok"]}, {**entry, "prev_entry_sha256": "xyz"},
                       {**entry, "date_utc": "not-a-date"}, {**entry, "date_utc": 5}):
            with self.subTest(change=change), self.assertRaises(PolicyError):
                validate_policy({**self.policy(), "relaxations": [change]})

    def test_relaxation_chain_detects_tampering(self):
        first = {"date_utc": "2026-10-11T08:00:00+00:00", "reason": "first",
                 "changes": ["removed_forbidden: a:b"], "prev_entry_sha256": "0" * 64}
        second = {"date_utc": "2026-10-11T09:00:00+00:00", "reason": "second",
                  "changes": ["cycles_disabled"], "prev_entry_sha256": _canonical_sha256(first)}
        self.assertEqual(
            validate_policy({**self.policy(), "relaxations": [first, second]})["relaxations"],
            [first, second])
        for tampered in ([second],
                         [{**first, "reason": "edited"}, second],
                         [second, first]):
            with self.subTest(relaxations=tampered), self.assertRaises(PolicyError):
                validate_policy({**self.policy(), "relaxations": tampered})

    def test_relaxation_changes_enumerates_all_eight_types(self):
        old = {"schema_version": 1, "language": "python", "package": "sample", "source": None,
               "forbidden": [["learning", "publishing"], ["publishing", "memory"]],
               "allowed_dependencies": [["learning", "memory"]],
               "modules": ["learning", "publishing", "memory"],
               "unmanaged_modules": ["scripts"], "module_coverage": "top_level",
               "check_cycles": True, "strict": True,
               "tests": [["python", "-m", "pytest", "-q"]]}
        new = {"schema_version": 1, "language": "python", "package": "sample", "source": None,
               "forbidden": [["learning", "publishing"]], "allowed_dependencies": [],
               "modules": ["learning", "publishing"],
               "unmanaged_modules": ["scripts", "tools"], "module_coverage": "off",
               "check_cycles": False, "strict": False, "tests": []}
        self.assertEqual(relaxation_changes(old, new), [
            "coverage_off", "cycles_disabled", "removed_allowed: learning:memory",
            "removed_forbidden: publishing:memory", "removed_module: memory",
            "removed_test: [\"python\",\"-m\",\"pytest\",\"-q\"]", "strict_disabled", "unmanaged: tools"])
        self.assertEqual(relaxation_changes(new, old), [])

    def test_relaxation_changes_tolerates_sparse_and_empty_bases(self):
        self.assertEqual(relaxation_changes({}, self.policy()), [])
        old = {**self.policy(), "forbidden": [["a", "b"], ["c", "d"], ["e", "f"]]}
        self.assertEqual(relaxation_changes(old, {**old, "forbidden": [["c", "d"]]}),
                         ["removed_forbidden: a:b", "removed_forbidden: e:f"])
        off = {**self.policy(), "modules": ["learning", "publishing"], "module_coverage": "off"}
        self.assertEqual(relaxation_changes(off, self.policy()),
                         ["removed_module: learning", "removed_module: publishing"])

    def test_cycles_default_differs_by_language(self):
        base = {"schema_version": 1, "language": "python", "package": "sample", "source": None,
                "forbidden": [["a", "b"]], "tests": [["x"]]}
        ts = {**base, "language": "typescript", "package": None, "source": "src"}
        self.assertEqual(relaxation_changes(ts, {**ts, "check_cycles": False}), ["cycles_disabled"])
        self.assertEqual(relaxation_changes(base, {**base, "check_cycles": False}), [])
        self.assertEqual(relaxation_changes({**base, "check_cycles": True}, {**base, "check_cycles": False}),
                         ["cycles_disabled"])

    def test_strict_checks_block_naked_relaxation_and_mixed_pr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = {**self.policy(), "strict": True,
                   "forbidden": [["learning", "publishing"], ["publishing", "memory"]]}
            new = {**old, "forbidden": [["learning", "publishing"]]}
            self.git_repo_with_base(root, old)
            (root / ".agent-engineering" / "policy.json").write_text(json.dumps(new), encoding="utf-8")
            (root / "feature.py").write_text("y = 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "loosen plus code"], cwd=root, check=True)
            result = strict_policy_checks(root, new, "HEAD~1")
            self.assertFalse(result[0]["passed"])
            self.assertIn("removed_forbidden: publishing:memory", result[0]["detail"])
            self.assertIn("feature.py", result[0]["detail"])
            entry = {"date_utc": "2026-10-11T08:00:00+00:00", "reason": "memory retired",
                     "changes": ["removed_forbidden: publishing:memory"], "prev_entry_sha256": "0" * 64}
            isolated = {**new, "relaxations": [entry]}
            (root / ".agent-engineering" / "policy.json").write_text(json.dumps(isolated), encoding="utf-8")
            result = strict_policy_checks(root, isolated, "HEAD~1")
            self.assertFalse(result[0]["passed"])
            self.assertNotIn("naked relaxation", result[0]["detail"])
            self.assertIn("isolated PR", result[0]["detail"])
            subprocess.run(["git", "add", ".agent-engineering"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "policy only"], cwd=root, check=True)
            # 累积 diff 语义：base...HEAD 是整个 PR 的累计变更，早前混入的 feature.py 无法被
            # 后续纯 policy 提交洗白——分支整体仍是混合 PR，必须保持红。
            result = strict_policy_checks(root, isolated, "HEAD~2")
            self.assertFalse(result[0]["passed"])
            self.assertIn("isolated PR", result[0]["detail"])
            # 全绿场景需要真正隔离的 PR：在干净仓库里从同一 base 只提交 policy
            # （连同两份白名单文件，钉住 whitelist 的每个子句）。
            with tempfile.TemporaryDirectory() as clean_temp:
                clean = Path(clean_temp)
                self.git_repo_with_base(clean, old)
                (clean / ".agent-engineering" / "policy.json").write_text(json.dumps(isolated), encoding="utf-8")
                (clean / "ARCHITECTURE.md").write_text("boundaries\n", encoding="utf-8")
                workflows = clean / ".github" / "workflows"
                workflows.mkdir(parents=True)
                (workflows / "engineering-guard.yml").write_text("on: push\n", encoding="utf-8")
                subprocess.run(["git", "add", "."], cwd=clean, check=True)
                subprocess.run(["git", "commit", "-qm", "policy only"], cwd=clean, check=True)
                result = strict_policy_checks(clean, isolated, "HEAD~1")
                self.assertTrue(result[0]["passed"])
            # 纯截断历史：base 带 [entry]、current 原样删掉条目——物质未变、链仍合法，
            # 唯有"条目数少于 base"能拦住这种植除。
            with tempfile.TemporaryDirectory() as trunc_temp:
                trunc = Path(trunc_temp)
                history = {**old, "relaxations": [entry]}
                self.git_repo_with_base(trunc, history)
                truncated = {k: v for k, v in history.items() if k != "relaxations"}
                (trunc / ".agent-engineering" / "policy.json").write_text(json.dumps(truncated), encoding="utf-8")
                subprocess.run(["git", "add", ".agent-engineering"], cwd=trunc, check=True)
                subprocess.run(["git", "commit", "-qm", "erase history"], cwd=trunc, check=True)
                result = strict_policy_checks(trunc, truncated, "HEAD~1")
                self.assertFalse(result[0]["passed"])
                self.assertIn("truncated", result[0]["detail"])
            result = strict_policy_checks(root, isolated, "no-such-ref")
            self.assertFalse(result[0]["passed"])

    def test_strict_checks_fail_closed_on_malformed_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.git_repo_with_base(root, {"schema_version": 1, "language": "python",
                                           "package": "sample", "forbidden": [["a"]]})
            result = strict_policy_checks(root, self.policy(), "HEAD")
            self.assertFalse(result[0]["passed"])
            self.assertIn("cannot compare", result[0]["detail"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.git_repo_with_base(root, self.policy())
            result = strict_policy_checks(root, {**self.policy(), "modules": None,
                                                 "allowed_dependencies": None}, "HEAD")
            self.assertFalse(result[0]["passed"])
            self.assertIn("cannot compare", result[0]["detail"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.git_repo_with_base(root, {**self.policy(), "relaxations": [
                {"date_utc": "2026-10-11T08:00:00+00:00", "reason": "r",
                 "changes": ["removed_forbidden: a:b"], "prev_entry_sha256": "0" * 64}]})
            result = strict_policy_checks(root, {**self.policy(), "relaxations": None}, "HEAD")
            self.assertFalse(result[0]["passed"])
            self.assertIn("truncated", result[0]["detail"])

    def test_strict_policy_with_base_fails_closed_outside_git(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            p["strict"] = True
            result = check(root, p, arch_only=True, ci_base="HEAD")
            self.assertFalse(result["passed"])
            self.assertEqual(result["checks"][0]["name"], "strict-policy")
            result = check(root, p, arch_only=True, ci_base="0" * 40)
            self.assertNotIn("strict-policy", [c["name"] for c in result["checks"]])

    def test_strict_policy_without_base_only_notes(self):
        if os.name == "nt":
            self.skipTest("fake POSIX executable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = self.setup_example(root)
            p["strict"] = True
            binpath = root / "bin"
            binpath.mkdir()
            fake = binpath / "lint-imports"
            fake.write_text("#!/bin/sh\ncase \"$1\" in --config) test -f \"$2\";; *) exit 7;; esac\n",
                            encoding="utf-8")
            fake.chmod(0o755)
            old = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = str(binpath) + os.pathsep + old
                result = check(root, p, arch_only=True)
            finally:
                os.environ["PATH"] = old
            self.assertTrue(result["passed"])
            self.assertEqual([c["name"] for c in result["checks"]], ["architecture"])


if __name__ == "__main__":
    unittest.main()
