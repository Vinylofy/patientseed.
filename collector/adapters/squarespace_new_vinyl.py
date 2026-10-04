"""Bounded Squarespace JSON product adapter; schema changes fail closed."""
from __future__ import annotations
import json,re
from decimal import Decimal
from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source

class SquarespaceNewVinylAdapter:
    def __init__(self, domain: str): self.domain=domain
    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url,self.domain); payload=json.loads(body)
        products=payload.get('products') if isinstance(payload,dict) else payload
        if not isinstance(products,list): raise CollectionBlocked('Squarespace feed contract changed')
        rows=[]; exclusions=[]
        for p in products:
            if not isinstance(p,dict): continue
            url=p.get('url') or p.get('fullUrl'); name=str(p.get('title') or p.get('name') or '')
            text=(name+' '+str(p.get('description',''))+' '+str(p.get('category',''))).lower()
            if not isinstance(url,str): continue
            used=bool(re.search(r'\b(used|pre[- ]?owned|second[- ]hand|vintage|graded|vg\+?|nm)\b',text)); vinyl=bool(re.search(r'\b(vinyl|lp|12 inch|7 inch)\b',text))
            if used or not vinyl: exclusions.append({'url':url,'signal':'used' if used else 'new_vinyl_not_proven','at':observed_at});continue
            raw=p.get('price') or (p.get('pricing',{}).get('basePrice') if isinstance(p.get('pricing'),dict) else None)
            try: price=Decimal(str(raw))
            except Exception: exclusions.append({'url':url,'signal':'price_not_proven','at':observed_at});continue
            if price<=0: continue
            rows.append({'url':url,'artist':'','title':name,'identifier_raw':None,'identifier_type':'unknown','identifier_source_url':url,'price':f'{price:.2f}','base_price':f'{price:.2f}','sale_price':None,'currency':'USD','availability':'in_stock','observed_at':observed_at,'price_source_url':source_url,'price_source':'listing','availability_source':'listing','product_type':'vinyl','condition':'new','condition_source_url':url,'price_context':{'vat':'unknown','kind':'public','variant':str(p.get('id',url)),'buyable_variant':True,'units':1,'bundle':False,'membership':False,'mandatory_surcharge':'0','from_price':False},'source_fragment':json.dumps({'title':name,'url':url})})
        return ListingPage(tuple(rows),None,tuple(exclusions))
