"""A release must describe the exact packaged executable that passed acceptance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from version import IDENTITY


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_rejects_stale_binary_and_accepts_matching_packaged_report(self):
        script=Path(__file__).resolve().parents[1]/'scripts/release_manifest.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'dist').mkdir()
            subprocess.run(['git','init','-q'],cwd=root,check=True,capture_output=True)
            subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.invalid','-c',
                'core.hooksPath='+str(root/'no-hooks'),'commit','--allow-empty','-m','Fixture'],cwd=root,check=True,capture_output=True)
            commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            executable=root/'dist/main.exe';executable.write_bytes(b'packaged fixture')
            report=root/'acceptance.json'
            payload=dict(status='passed',application=IDENTITY,source_commit=commit,source_dirty=False,
                executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
            report.write_text(json.dumps(payload))
            result=subprocess.run([sys.executable,str(script),'--self-test-report',str(report)],cwd=root,
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            manifest=json.loads((root/'dist/release-manifest.json').read_text())
            self.assertEqual(manifest['files']['main.exe'],hashlib.sha256(executable.read_bytes()).hexdigest())
            self.assertEqual(manifest['commit'],commit)
            for change in ({'source_commit':'another-commit'},{'source_dirty':True}):
                with self.subTest(change=change):
                    report.write_text(json.dumps(payload | change))
                    result=subprocess.run([sys.executable,str(script),'--self-test-report',str(report)],cwd=root,
                                          capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('clean source checkout',result.stderr)
            report.write_text(json.dumps(payload))
            executable.write_bytes(b'a different binary')
            result=subprocess.run([sys.executable,str(script),'--self-test-report',str(report)],cwd=root,
                                  capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('exact executable',result.stderr)
