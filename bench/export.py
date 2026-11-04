"""Create a whitelist-only standalone benchmark candidate, never publish it."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FILES=('__init__.py','run_model.py','score.py','privacy.py','model_transport.py',
       'model_fixture.py','run_ingress.py','corpus.py','measure.py','artifacts.py',
       'ingress_fixture.py','README.md','LICENSE','export.py')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args(argv)
    root=Path(__file__).resolve().parent
    paths=[root/name for name in FILES]+sorted((root/'corpus/v1.0').glob('*'))
    assert all(path.is_file() for path in paths)
    args.out.mkdir(parents=True,exist_ok=False)
    hashes={path.relative_to(root.parent).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    with zipfile.ZipFile(args.out/'DecoyBench-v1-candidate.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for path in paths:archive.write(path,path.relative_to(root.parent).as_posix())
        archive.writestr('SHA256-MANIFEST.json',json.dumps(hashes,indent=2)+'\n')
    result={'publication_approved':False,'files':hashes,'archive_sha256':hashlib.sha256((args.out/'DecoyBench-v1-candidate.zip').read_bytes()).hexdigest()}
    (args.out/'EXPORT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(paths),'archive_sha256':result['archive_sha256'],'publication_approved':False}))
    return 0


if __name__=='__main__':raise SystemExit(main())
