"""Conservative BigCommerce storefront catalog adapter."""
from __future__ import annotations
import json,re
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urljoin
from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source

class BigCommerceNewVinylAdapter:
    def __init__(self, domain: str): self.domain=domain
    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url,self.domain); payload=json.loads(body)
        products=payload.get('data',payload.get('products')) if isinstance(payload,dict) else payload
        if not isinstance(products,list): raise CollectionBlocked('BigCommerce feed contract changed')
        rows=[]; exclusions=[]
        for p in products:
            if not isinstance(p,dict): continue
            name=str(p.get('name','')); url=urljoin(f'https://{self.domain}/', p.get('custom_url',{}).get('url') if isinstance(p.get('custom_url'),dict) else p.get('url') or ''); text=(name+' '+str(p.get('description',''))).lower()
            if not isinstance(url,str): continue
            used=bool(re.search(r'\b(used|pre[- ]?owned|second[- ]hand|vintage|graded|vg\+?|nm)\b',text)); vinyl=bool(re.search(r'\b(vinyl|lp|12 inch|7 inch)\b',text))
            if used or not vinyl: exclusions.append({'url':url,'signal':'used' if used else 'new_vinyl_not_proven','at':observed_at});continue
            raw=p.get('sale_price') or p.get('price')
            try: price=Decimal(str(raw))
            except Exception: continue
            if price<=0: continue
            rows.append({'url':url,'artist':'','title':name,'identifier_raw':None,'identifier_type':'unknown','identifier_source_url':url,'price':f'{price:.2f}','base_price':f'{price:.2f}','sale_price':None,'currency':'USD','availability':'in_stock','observed_at':observed_at,'price_source_url':source_url,'price_source':'listing','availability_source':'listing','product_type':'vinyl','condition':'new','condition_source_url':url,'price_context':{'vat':'unknown','kind':'public','variant':str(p.get('id',url)),'buyable_variant':True,'units':1,'bundle':False,'membership':False,'mandatory_surcharge':'0','from_price':False},'source_fragment':json.dumps({'name':name,'id':p.get('id')})})
        return ListingPage(tuple(rows),None,tuple(exclusions))

    def parse_detail(self, body: str, *, source_url: str, listing: dict) -> dict:
        public_source(source_url, self.domain)
        if source_url.split('?', 1)[0].rstrip('/') != listing['url'].split('?', 1)[0].rstrip('/'):
            raise CollectionBlocked('Detail product mismatch')
        parser = _JsonLd(); parser.feed(body); codes = set()
        for raw in parser.items:
            try: value = json.loads(raw)
            except ValueError: continue
            for node in value if isinstance(value, list) else [value]:
                if isinstance(node, dict) and node.get('@type') == 'Product':
                    codes.update(node[key] for key in ('gtin','gtin12','gtin13','gtin14') if isinstance(node.get(key), str))
        if len(codes) != 1: return {}
        code = next(iter(codes)); kind = {12:'UPC-A',13:'EAN-13',14:'GTIN-14'}.get(len(code))
        return {'identifier_raw': code, 'identifier_type': kind, 'identifier_source_url': source_url} if kind and code.isdigit() else {}


class _JsonLd(HTMLParser):
    def __init__(self): super().__init__(); self.active=False; self.parts=[]; self.items=[]
    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type') == 'application/ld+json': self.active=True; self.parts=[]
    def handle_data(self, data):
        if self.active: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.active: self.items.append(''.join(self.parts)); self.active=False
