import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.supplemental_acceptance import normalize


class IndexedSubconto(unittest.TestCase):
    def test_goods_account_order_is_preserved_and_original_not_changed(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td); p=src/'ChartsOfAccounts/Accounts/Ext/Predefined.xml';p.parent.mkdir(parents=True)
            p.write_text('<PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef"><Item><Code>goods</Code><ExtDimensionTypes>'
                '<ExtDimensionType name="ChartOfCharacteristicTypes.Kinds.Item"/>'
                '<ExtDimensionType name="ChartOfCharacteristicTypes.Kinds.Warehouse"/>'
                '</ExtDimensionTypes></Item></PredefinedData>')
            original={'objects':{'accounts':'ChartOfAccounts.Accounts'},'account_codes':{'goods':'goods'},
                      'fields':{'ledger':{'item_debit':'СубконтоДт1','item_credit':'СубконтоКт1',
                                'warehouse_debit':'СубконтоДт2','warehouse_credit':'СубконтоКт2'}}}
            with patch('exam_bench.submission.strip_extras',side_effect=lambda b: (__import__('copy').deepcopy(b),[])), \
                 patch('exam_bench.submission.subconto_kinds',return_value={'Kinds.Item':{},'Kinds.Warehouse':{}}), \
                 patch('exam_bench.submission.canonical_ledger',side_effect=lambda s,b:(b,[])), \
                 patch('exam_bench.submission.check_bindings') as check:
                b,changes=normalize(src,original)
                self.assertEqual(b['fields']['ledger']['warehouse_credit'],'Kinds.Warehouse')
                self.assertEqual(len(changes),4)
                self.assertEqual(original['fields']['ledger']['item_debit'],'СубконтоДт1')
                check.assert_called_once_with(src,b)
                original['fields']['ledger']['item_debit']='СубконтоКт1'
                with self.assertRaisesRegex(ValueError,'side'):normalize(src,original)
