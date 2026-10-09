"""Real adapter black-box tests: executed by CI after installing dependencies.

Set AEGKIT_REQUIRE_ADAPTERS=1 to fail rather than skip when the adapter is missing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'engineering_kit' / 'guard.py'


def adapter_available(name: str) -> bool:
    found = shutil.which('lint-imports' if name == 'python' else 'npx')
    if not found:
        return False
    if name == 'typescript':
        # Exercise the actual CLI installed by npm, not Node's package export map.
        return subprocess.run(['npx', '--no-install', 'depcruise', '--version'],
                              cwd=ROOT, capture_output=True, timeout=20).returncode == 0
    return True


class RealAdapterTests(unittest.TestCase):
    def _check(self, base: Path, name: str, expected: int) -> None:
        outcome = subprocess.run([sys.executable, str(RUNNER), 'check', '--root', str(base)],
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(outcome.returncode, expected,
                         f'{name}: expected exit {expected}\n{outcome.stdout}\n{outcome.stderr}')

    def _require(self, name: str) -> None:
        if not adapter_available(name):
            if os.getenv('AEGKIT_REQUIRE_ADAPTERS') == '1':
                self.fail(f'{name} adapter not installed; CI must run real adapter tests')
            self.skipTest(f'{name} adapter unavailable')

    def test_real_python_forbidden_import(self):
        self._require('python')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for package in ('sample', 'sample/learning', 'sample/publishing'):
                p = base / package
                p.mkdir(parents=True)
                (p / '__init__.py').write_text('', encoding='utf-8')
            policy = {'schema_version': 1, 'language': 'python', 'package': 'sample',
                      'source': None, 'forbidden': [['learning', 'publishing']],
                      'tests': [[sys.executable, '-c', 'print("behavior ok")']]}
            (base / '.agent-engineering').mkdir()
            (base / '.agent-engineering/policy.json').write_text(json.dumps(policy))
            self._check(base, 'python clean', 0)
            bad = base / 'sample/learning/impl.py'
            bad.write_text('from sample.publishing import api\n', encoding='utf-8')
            (base / 'sample/publishing/api.py').write_text('VALUE = 1\n', encoding='utf-8')
            self._check(base, 'python forbidden import', 1)
            bad.unlink()
            self._check(base, 'python clean again', 0)

    def test_real_python_cycle_check(self):
        self._require('python')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ('sample', 'sample/learning', 'sample/publishing', 'sample/contracts'):
                folder = base / name
                folder.mkdir(parents=True)
                (folder / '__init__.py').write_text('', encoding='utf-8')
            policy = {'schema_version': 1, 'language': 'python', 'package': 'sample',
                      'check_cycles': True, 'forbidden': [['learning', 'contracts']],
                      'tests': [[sys.executable, '-c', 'print("behavior ok")']]}
            (base / '.agent-engineering').mkdir()
            (base / '.agent-engineering/policy.json').write_text(json.dumps(policy))
            (base / 'sample/learning/api.py').write_text('VALUE = 1\n', encoding='utf-8')
            (base / 'sample/publishing/api.py').write_text('VALUE = 2\n', encoding='utf-8')
            self._check(base, 'Python acyclic', 0)
            (base / 'sample/learning/api.py').write_text('from sample.publishing import api\n', encoding='utf-8')
            (base / 'sample/publishing/api.py').write_text('from sample.learning import api\n', encoding='utf-8')
            self._check(base, 'Python cycle', 1)
            (base / 'sample/learning/api.py').write_text('VALUE = 1\n', encoding='utf-8')
            (base / 'sample/publishing/api.py').write_text('VALUE = 2\n', encoding='utf-8')
            self._check(base, 'Python cycle repaired', 0)

    def test_real_typescript_forbidden_import(self):
        self._require('typescript')
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            base = Path(tmp)
            for folder in ('src/learning', 'src/publishing'):
                (base / folder).mkdir(parents=True)
            policy = {'schema_version': 1, 'language': 'typescript', 'package': None,
                      'source': 'src', 'forbidden': [['learning', 'publishing']],
                      'tests': [[sys.executable, '-c', 'print("behavior ok")']]}
            (base / '.agent-engineering').mkdir()
            (base / '.agent-engineering/policy.json').write_text(json.dumps(policy))
            (base / 'src/publishing/index.ts').write_text('export const x = 1;\n')
            (base / 'src/learning/index.ts').write_text('export const y = 2;\n')
            # npx resolves tools from parent node_modules when tests are inside the repo.
            self._check(base, 'TS clean', 0)
            (base / 'src/learning/index.ts').write_text("import { x } from '../publishing';\nexport const y = x;\n")
            self._check(base, 'TS forbidden import', 1)
            (base / 'src/learning/index.ts').write_text('export const y = 2;\n')
            self._check(base, 'TS clean again', 0)
            (base / 'src/publishing/index.ts').write_text('export type PublishingId = string;\n')
            (base / 'src/learning/index.ts').write_text(
                "import type { PublishingId } from '../publishing';\n"
                'export type LearningId = PublishingId;\n')
            self._check(base, 'TS forbidden type-only import', 1)
            (base / 'src/learning/index.ts').write_text('export const y = 2;\n')
            self._check(base, 'TS type import repaired', 0)


if __name__ == '__main__':
    unittest.main()
