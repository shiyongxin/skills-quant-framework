# -*- coding: utf-8 -*-
"""
A-P1-4 回归: realtime_quote.get_quotes 按内容代码正则匹配 (不用行号)

旧行为: 行号 i 直接对应 codes[i] → API 少返回一只/夹杂空行时
后续全体错位 (静默污染), 或 i 越界 IndexError 吞掉整个结果。
"""

from realtime_quote import RealTimeQuoteAPI


class _Resp:
    status_code = 200
    encoding = 'gbk'

    def __init__(self, text):
        self.text = text


class _StubSession:
    def __init__(self, text):
        self._text = text

    def get(self, url, timeout=None):
        return _Resp(self._text)


def _quote_line(prefix, code, name, price, amount_wan=12345.6):
    parts = [''] * 40
    parts[0] = '51'
    parts[1] = name
    parts[2] = code
    parts[3] = str(price)        # 现价
    parts[4] = str(price - 1)    # 昨收
    parts[5] = str(price - 0.5)  # 今开
    parts[6] = '100'             # 成交量(手)
    parts[31] = '1.0'            # 涨跌额
    parts[32] = '1.5'            # 涨跌幅
    parts[33] = str(price + 0.5)  # 最高
    parts[34] = str(price - 1.5)  # 最低
    parts[37] = str(amount_wan)   # 成交额(万)
    return f'v_{prefix}{code}="{"~".join(parts)}";'


def _api(text):
    api = RealTimeQuoteAPI()
    api.session = _StubSession(text)
    return api


class TestGetQuotesContentMatching:
    def test_leading_junk_lines_do_not_shift(self):
        """夹杂非 v_ 行不再造成行号错位/越界 (旧行为: IndexError→返回{})"""
        text = '\n# comment line\n' + _quote_line('sh', '600519', '贵州茅台', 1700.0)
        res = _api(text).get_quotes(['600519', '000001'])
        assert set(res) == {'600519'}
        assert res['600519'].code == '600519'
        assert res['600519'].name == '贵州茅台'

    def test_middle_missing_code_does_not_pollute(self):
        """中间一只缺失 → 不得把后续行错记到缺失代码名下"""
        text = (_quote_line('sh', '600519', '贵州茅台', 1700.0) + '\n' +
                _quote_line('sz', '000858', '五粮液', 130.0))
        res = _api(text).get_quotes(['600519', '300750', '000858'])
        # 旧行为: i=1 的五粮液行被记到 300750 名下
        assert set(res) == {'600519', '000858'}
        assert '300750' not in res
        assert res['000858'].name == '五粮液'
        assert res['000858'].code == '000858'

    def test_parse_fields_and_amount_conversion(self):
        text = _quote_line('sh', '600519', '贵州茅台', 1700.0, amount_wan=12345.6)
        res = _api(text).get_quotes(['600519'])
        q = res['600519']
        assert q.price == 1700.0
        assert q.pre_close == 1699.0
        assert q.volume == 100.0
        assert q.change_pct == 1.5
        assert q.high == 1700.5
        assert q.low == 1698.5
        # 成交额: 万 → 元
        assert q.amount == 12345.6 * 10000

    def test_unrequested_code_ignored(self):
        """响应中出现未请求的代码 → 忽略, 不污染结果"""
        text = (_quote_line('sh', '600519', '贵州茅台', 1700.0) + '\n' +
                _quote_line('sz', '999999', '不存在', 1.0))
        res = _api(text).get_quotes(['600519'])
        assert set(res) == {'600519'}
