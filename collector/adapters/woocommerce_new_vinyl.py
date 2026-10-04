"""Conservative WooCommerce Store API adapter for public product listings."""
from __future__ import annotations
import re
from decimal import Decimal
from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source

class WooCommerceNewVinylAdapter:
    def __init__(self, domain: str): self.domain = domain
    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        import json
        public_source(source_url, self.domain); payload=json.loads(body)
        if not isinstance(payload,list): raise CollectionBlocked("WooCommerce feed contract changed")
        rows=[]; exclusions=[]
        for p in payload:
            if not isinstance(p,dict) or not isinstance(p.get('id'),int): continue
            url=p.get('permalink'); name=str(p.get('name','')); text=(name+' '+str(p.get('short_description',''))+' '+str(p.get('description',''))).lower()
            cats=' '.join(str(x.get('name','')) for x in p.get('categories',[]) if isinstance(x,dict)).lower()
            if not isinstance(url,str): continue
            used=bool(re.search(r'\b(used|pre[- ]?owned|second[- ]hand|vintage|graded|vg\+?|nm)\b',text+' '+cats))
            vinyl=bool(re.search(r'\b(vinyl|lp|12 inch|7 inch)\b',text+' '+cats))
            if used or not vinyl: exclusions.append({'url':url,'signal':'used' if used else 'new_vinyl_not_proven','at':observed_at}); continue
            price=p.get('prices',{}).get('price') if isinstance(p.get('prices'),dict) else p.get('price')
            try: price=Decimal(str(price))/100 if isinstance(price,(int,float)) or str(price).isdigit() else Decimal(str(price))
            except Exception: exclusions.append({'url':url,'signal':'price_not_proven','at':observed_at}); continue
            if price<=0: continue
            rows.append({'url':url,'artist':'','title':name,'identifier_raw':None,'identifier_type':'unknown','identifier_source_url':url,'price':f'{price:.2f}','base_price':f'{price:.2f}','sale_price':None,'currency':'USD','availability':'in_stock' if p.get('is_in_stock',True) else 'out_of_stock','observed_at':observed_at,'price_source_url':source_url,'price_source':'listing','availability_source':'listing','product_type':'vinyl','condition':'new','condition_source_url':url,'price_context':{'vat':'unknown','kind':'public','variant':str(p['id']),'buyable_variant':True,'units':1,'bundle':False,'membership':False,'mandatory_surcharge':'0','from_price':False},'source_fragment':json.dumps({'id':p['id'],'name':name})})
        return ListingPage(tuple(rows), None, tuple(exclusions))
