"""Tiny synthetic metadata for contract tests; does not require a licensed 1C installation."""
import json
from pathlib import Path

BINDING={'schema_version':1,'objects':{'items':'Catalog.Items','warehouses':'Catalog.Warehouses','receipt':'Document.Receipt','sale':'Document.Sale','manual':'Document.Manual','ledger':'AccountingRegister.Ledger','accounts':'ChartOfAccounts.Accounts'},'fields':{'items':{'article':'Article'},'receipt':{'warehouse':'Warehouse','item':'Lines.Item','quantity':'Lines.Qty','price':'Lines.Price','amount':'Lines.Amount'},'sale':{'warehouse':'Warehouse','item':'Lines.Item','quantity':'Lines.Qty','price':'Lines.Price','amount':'Lines.Amount'},'ledger':{'item_debit':'Item','item_credit':'Item','warehouse_debit':'Warehouse','warehouse_credit':'Warehouse','quantity_debit':'QtyДт','quantity_credit':'QtyКт','amount':'Amount'}},'account_codes':{'goods':'41','suppliers':'60','customers':'62','profit':'90'},'analogs':{'mode':'information_register','object':'InformationRegister.Analogs','left':'LinkA','right':'LinkB'}}


def source(root):
    def attr(kind,name,typ,balance=''):
        return f'<{kind}><Properties><Name>{name}</Name><Type><v8:Type>{typ}</v8:Type></Type>{balance}</Properties></{kind}>'
    def put(group,kind,name,props='',children=''):
        p=root/group/(name+'.xml');p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(f'<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core"><{kind}><Properties><Name>{name}</Name>{props}</Properties><ChildObjects>{children}</ChildObjects></{kind}></MetaDataObject>')
    root.mkdir(parents=True)
    (root/'Configuration.xml').write_text('<Configuration/>')
    put('Catalogs','Catalog','Items',children=attr('Attribute','Article','xs:string'))
    put('Catalogs','Catalog','Warehouses')
    put('ChartsOfAccounts','ChartOfAccounts','Accounts')
    for name in ('Receipt','Sale','Manual'):
        cols=''.join(attr('Attribute',n,t) for n,t in [('Item','cfg:CatalogRef.Items'),('Qty','xs:decimal'),('Price','xs:decimal'),('Amount','xs:decimal')])
        put('Documents','Document',name,props='<RegisterRecords><Item>AccountingRegister.Ledger</Item></RegisterRecords>',children=attr('Attribute','Warehouse','cfg:CatalogRef.Warehouses')+'<TabularSection><Properties><Name>Lines</Name></Properties><ChildObjects>'+cols+'</ChildObjects></TabularSection>')
    cols=''.join(attr(k,n,t,'<Balance>'+balance+'</Balance>') for k,n,t,balance in [('Dimension','Item','cfg:CatalogRef.Items','true'),('Dimension','Warehouse','cfg:CatalogRef.Warehouses','true'),('Resource','Amount','xs:decimal','true'),('Resource','Qty','xs:decimal','false')])
    put('AccountingRegisters','AccountingRegister','Ledger',props='<ChartOfAccounts>ChartOfAccounts.Accounts</ChartOfAccounts><Correspondence>true</Correspondence>',children=cols)
    put('InformationRegisters','InformationRegister','Analogs',children=attr('Dimension','LinkA','cfg:CatalogRef.Items')+attr('Dimension','LinkB','cfg:CatalogRef.Items'))
