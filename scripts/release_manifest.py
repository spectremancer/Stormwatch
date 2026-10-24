"""Write source identity and checksums without modifying packaged source files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from version import VERSION, BUILD, IDENTITY

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--self-test-report',type=Path,required=True)
args = parser.parse_args()
report = json.loads(args.self_test_report.read_text(encoding='utf-8'))
files = list(Path('dist').glob('*.exe'))
if not Path('dist/main.exe').exists():
    raise SystemExit('Build and test dist/main.exe before producing a release manifest.')
checksums = {}
for path in files:
    with path.open('rb') as stream:
        checksums[path.name] = hashlib.file_digest(stream,'sha256').hexdigest()
if (report.get('status')!='passed' or report.get('application')!=IDENTITY or
        report.get('executable_sha256')!=checksums['main.exe']):
    raise SystemExit('The packaged acceptance report does not match this exact executable and build.')
try:
    commit = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
except (OSError,subprocess.CalledProcessError):
    commit = 'unknown'
if commit=='unknown' or report.get('source_commit')!=commit or report.get('source_dirty') is not False:
    raise SystemExit('The release requires a clean source checkout matching the packaged acceptance report.')
manifest = dict(version=VERSION,build=BUILD,commit=commit,signing='unsigned unless separately signed and verified',
                files=checksums)
Path('dist/release-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
Path('dist/SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for name,digest in manifest['files'].items()),encoding='utf-8',newline='\n')
