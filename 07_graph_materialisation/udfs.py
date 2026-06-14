import pandas as pd

def add_fragment(text, fragment) -> str:
    if isinstance(text, pd.Series):
        return text.apply(lambda t: '' if (not t or str(t) in ('nan', 'None', '')) else f"{t}#{fragment}")
    if not text or str(text) in ('nan', 'None', ''):
        return ''
    return f"{str(text)}#{fragment}"

def add_fragment_idx(text, fragment, idx) -> str:
    if not text or str(text) in ('nan', 'None', ''):
        return ''
    return f"{str(text)}#{fragment}{idx}"

try:
    udf('http://bnf.example.org/addFragment', text='text', fragment='fragment')(add_fragment)
    udf('http://bnf.example.org/addFragmentIdx', text='text', fragment='fragment', idx='idx')(add_fragment_idx)
except NameError:
    pass
