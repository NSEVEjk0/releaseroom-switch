import json
from pathlib import Path
from releaseroom.demo import verify
bundle=json.loads(Path('reports/reference-release.json').read_text());verify(bundle)
folder=Path('web/examples');folder.mkdir(parents=True,exist_ok=True)
(folder/'reference-release.json').write_text(json.dumps(bundle,indent=2))
(folder/'reference-site.html').write_text(bundle['artifact'])
print('Checked local reference published with explicit no-Switch/no-AI provenance.')
