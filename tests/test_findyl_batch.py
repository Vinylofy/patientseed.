import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collector import progress, quality_store
from collector.manual_run import load_queue, queue_digest
from collector.recon import shopify_currency, probe
from collector.contracts import CollectionBlocked
from collector.build_scrapers import build
from collector.execute_generated import load_profile
from collector.quality_gate import run_batch

class FindylBatchTests(unittest.TestCase):
    def test_queue_appends_exact_source_group_without_resetting_original_prefix(self):
        q=load_queue(Path('collector/public-queue.json'))
        manifest=json.loads(Path('collector/sources/findyl-online-2026-10-25.json').read_text())
        entries=manifest['entries'];self.assertEqual(len(entries),50)
        self.assertEqual([x['row'] for x in q[-50:]],[x['row'] for x in entries])
        self.assertEqual([x['domain'] for x in q[-50:]],[x['domain'] for x in entries])
        self.assertEqual(sum(x['source_status']=='SHARED_PLATFORM' for x in entries),3)
        state={'schema_version':1,'queue_size':3303,'queue_sha256':queue_digest(q[:3303]),'next_start_index':3303}
        self.assertEqual(progress.next_index(state,q),3303)

    def test_progress_reads_large_file_by_blob_and_preserves_sha(self):
        state={'schema_version':1,'history':[]};raw=json.dumps(state).encode();sha='a'*40
        obj={'size':1_100_000,'sha':sha,'encoding':'none','content':''}
        blob={'sha':sha,'encoding':'base64','content':base64.b64encode(raw).decode()}
        with patch.object(progress,'request',side_effect=[obj,blob]) as api:
            result,returned_sha=progress.read_remote()
        self.assertEqual(result,state);self.assertEqual(returned_sha,sha)
        self.assertEqual(api.call_args.args,('GET',f'git/blobs/{sha}'))
        with patch.object(progress,'request',side_effect=[obj,{**blob,'sha':'b'*40}]):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):progress.read_remote()

    def test_quality_store_large_file_and_budget_limit(self):
        obj={'size':1_100_000,'sha':'a'*40,'encoding':'none','content':''}
        blob={'sha':'a'*40,'encoding':'base64','content':base64.b64encode(b'{}').decode()}
        with patch.object(quality_store,'api',side_effect=[obj,blob]):
            self.assertEqual(quality_store.read('quality/state.json'),('{}','a'*40))
        with patch.object(progress,'request',return_value={**obj,'size':10_000_001}):
            with self.assertRaisesRegex(ValueError,'size'):progress.read_remote()

    def test_append_publish_preserves_recheck_evidence(self):
        q=load_queue(Path('collector/public-queue.json'))[:2]
        state={'schema_version':1,'queue_size':1,'queue_sha256':queue_digest(q[:1]),'next_start_index':1,
               'batch_number':1,'history':[{'row':q[0]['row'],'status':'SOURCE_REVIEW'}],
               'rechecks':[{'row':q[0]['row'],'status':'SCRAPER_BUILT_TESTED'}]}
        result={'schema_version':1,'queue_sha256':queue_digest(q),'complete':True,'start_index':1,
                'next_start_index':2,'processed':1,'results':[{**q[1],'status':'SOURCE_REVIEW'}]}
        with tempfile.TemporaryDirectory() as tmp:
            queue=Path(tmp)/'q.json';output=Path(tmp)/'r.json';queue.write_text(json.dumps(q));output.write_text(json.dumps(result))
            with patch.object(progress,'read_remote',return_value=(state,'sha')),patch.object(progress,'request') as api,patch.dict(os.environ,{'GITHUB_RUN_ID':'test','GITHUB_SHA':'a'*40}):
                progress.publish(queue,output)
            saved=progress.unpack_state(json.loads(base64.b64decode(api.call_args.args[2]['content'])))
            self.assertEqual(saved['rechecks'],state['rechecks'])
            self.assertEqual(saved['history'][0],state['history'][0])

    def test_explicit_currency_does_not_guess_from_country(self):
        self.assertEqual(shopify_currency('Shopify.currency = {"active":"GBP","rate":"1.0"};'),'GBP')
        self.assertIsNone(shopify_currency('Prices in pounds; United Kingdom'))
        self.assertIsNone(shopify_currency('Shopify.currency={"active":"GBP"};Shopify.currency={"active":"USD"};'))

    def test_generated_wrapper_keeps_proven_gbp_without_changing_global_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'run.json';dest=root/'collector/generated'
            source.write_text(json.dumps({'schema_version':1,'complete':True,'results':[{
                'row':3310,'domain':'shop.example','platform':'shopify','status':'ADAPTER_TESTED',
                'source_url':'https://shop.example/products.json?limit=20&page=1','detail_checked':1,
                'currency':'GBP','currency_source':'public_storefront_Shopify.currency'}]}))
            build(source,dest);profile,scraper=load_profile(dest/'shop_example.json')
            body=json.dumps({'products':[{'handle':'album','title':'Artist - Album LP','product_type':'Vinyl',
                'variants':[{'id':1,'price':'25.00','available':True}]}]})
            page=scraper.parse_listing(body,observed_at='today')
            self.assertEqual(page.listings[0]['currency'],'GBP')
            self.assertEqual(profile['currency'],'GBP')

    def test_blocked_route_stops_before_trying_another_route(self):
        class Transport:
            calls=[]
            def __init__(self,*args):pass
            def get(self,url):
                self.calls.append(url)
                if len(self.calls)==1:return 'cdn.shopify.com'
                raise CollectionBlocked('HTTP_429')
        with patch.dict(os.environ,{},clear=True):
            result=probe({'row':1,'name':'shop','domain':'shop.example','source_status':'READY'},Transport)
        self.assertEqual(result['status'],'SOURCE_BLOCKED');self.assertEqual(len(Transport.calls),2)

    def test_targeted_quality_batch_does_not_touch_other_domains(self):
        from test_quality_gate import QualityTests
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);profiles=QualityTests().profiles(root)
            result=run_batch(profiles,root/'quality',domains={'b.example'},validator=lambda *a,**k:{'status':'REVIEW','reason':'test'})
            self.assertEqual([x['slug'] for x in result['processed']],['b'])
