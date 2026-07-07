import json
from pathlib import Path


def test_aiinfra_no_bad_yahoo_candidates():
    data = json.loads(Path('config/portfolio.json').read_text())
    ai = next(i for i in data['instruments'] if i['key'] == 'AIINFRA')
    assert ai['yf_symbol'] == 'AIFS.DE'
    assert ai.get('yf_symbol_candidates', []) == []
