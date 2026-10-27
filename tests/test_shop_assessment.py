from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collector.shop_assessment import classify, assess_shop
from collector.artist_title import identity
from collector.assessment_batch import run, shops, csv_text, section
from collector import assessment_store
from collector.contracts import CollectionBlocked
from collector.recon import valid_gtin

ITEM={'row':1,'name':'Example Records','domain':'example.test','source_status':'READY'}
GOOD={'vinyl':True,'new_used_distinguishable':True,'public_prices':True,'availability':True,
      'stable_urls':True,'detail_checked':3,'detail_price_proven':3,'ean_valid':0,
      'identity_details_proven':3,'identity_listing_ratio':1}


def fixture(codes=None, condition=True, mismatch=False, robots='User-agent: *\nAllow: /'):
    home='https://example.test/'
    responses={home:'Shopify.theme = {}; Shopify.currency = {"active":"USD"};', home+'robots.txt':robots}
    products=[]
    for i,(artist,title) in enumerate([('Alpha','One'),('Beta','Two'),('Gamma','Three')],1):
        name=f'{artist} - {title} (LP)';url=home+'products/album-'+str(i)
        products.append({'handle':'album-'+str(i),'title':name,'product_type':'Vinyl',
                         'variants':[{'id':i,'available':True,'price':str(20+i)+'.00','barcode':codes[i-1] if codes else None}]})
        data={'@type':'Product','url':url,'name':name,'offers':{
              '@type':'Offer','url':url+'?variant='+str(i), 'price':str(999 if mismatch else 20+i), 'priceCurrency':'USD'}}
        if condition:data['itemCondition']='https://schema.org/NewCondition'
        if codes:data['gtin']=codes[i-1]
        html='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        responses[url]=html;responses[url+'?variant='+str(i)]=html
    body=json.dumps({'products':products})
    responses[home+'products.json?limit=20&page=1']=body
    responses[home+'collections/all/products.json?limit=20&page=1']=body
    return responses


class FakeTransport:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def get(self,url):
        self.calls.append(url)
        if url not in self.responses:raise CollectionBlocked('HTTP_404')
        return self.responses[url]


class ClassificationTests(unittest.TestCase):
    def test_missing_ean_can_be_artist_title_and_ean_has_priority(self):
        self.assertEqual(classify(GOOD)[0],'ARTIST_TITLE')
        self.assertEqual(classify(dict(GOOD,ean_valid=3))[0],'EAN')

    def test_artist_title_without_vinyl_price_stock_or_new_used_proof_is_not_enough(self):
        for field in ('vinyl','public_prices','availability','stable_urls','new_used_distinguishable'):
            for value in (None,False):
                with self.subTest(field=field,value=value):
                    self.assertEqual(classify(dict(GOOD,**{field:value}))[0],'MANUAL_REVIEW')

    def test_small_or_inconsistent_samples_do_not_become_suitable(self):
        self.assertEqual(classify(dict(GOOD,detail_checked=1))[0],'MANUAL_REVIEW')
        self.assertEqual(classify(dict(GOOD,identity_listing_ratio=.5))[0],'MANUAL_REVIEW')
        self.assertEqual(classify(dict(GOOD,identity_details_proven=2))[0],'MANUAL_REVIEW')

    def test_used_only_is_unsuitable_but_access_blocks_are_manual(self):
        self.assertEqual(classify(dict(GOOD,secondhand_only=True))[0],'UNSUITABLE')
        self.assertEqual(classify(dict(GOOD,access_problem='HTTP_403'))[0],'MANUAL_REVIEW')

    def test_existing_ean_admission_is_retained(self):
        self.assertEqual(classify({'existing_ean_approved':True})[0],'EAN')

    def test_numerical_product_ids_are_not_eans(self):
        for value in ('123456','1234567890123','https://example.test/products/4006381333931'):
            self.assertFalse(valid_gtin(value))
        self.assertTrue(valid_gtin('4006381333931'))

    def test_artist_parser_does_not_guess_vendor_or_multiple_delimiters(self):
        self.assertIsNone(identity({'title':'Album'}, {'vendor':'Universal'}))
        self.assertIsNone(identity({'title':'Artist - Album - Format'}))
        self.assertEqual(identity({'title':'Alpha - Album'})['artist'],'Alpha')


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)

    def assess(self,responses,**kwargs):
        transport=FakeTransport(responses)
        result=assess_shop(ITEM,transport_factory=lambda *_:transport,**kwargs)
        return result,transport

    def test_actual_artist_title_evidence_and_country_are_stored_without_invented_counts(self):
        result,_=self.assess(fixture(),country='NL')
        self.assertEqual(result['scraper_type'],'ARTIST_TITLE')
        self.assertEqual(result['evidence']['detail_checked'],3)
        self.assertTrue(result['assessment_ready'])
        self.assertIsNone(result['product_count'])
        self.assertEqual(result['country'],'NL')
        self.assertFalse(result['database_write'])
        self.assertEqual(len(result['examples']),3)

    def test_valid_own_product_eans_win_and_fallback_is_recorded(self):
        result,_=self.assess(fixture(['4006381333931','5901234123457','036000291452']),country='NL')
        self.assertEqual(result['scraper_type'],'EAN')
        self.assertTrue(result['supports_artist_title_fallback'])

    def test_invalid_or_repeated_barcode_is_never_approved_as_ean(self):
        for codes in [['1234567890123']*3,['4006381333931']*3]:
            result,_=self.assess(fixture(codes))
            self.assertEqual(result['scraper_type'],'MANUAL_REVIEW')

    def test_unknown_condition_and_wrong_product_price_require_review(self):
        for responses in [fixture(condition=False),fixture(mismatch=True)]:
            result,_=self.assess(responses)
            self.assertEqual(result['scraper_type'],'MANUAL_REVIEW')
            self.assertFalse(result['build_eligible'])

    def test_robots_denial_is_not_bypassed(self):
        result,transport=self.assess(fixture(robots='User-agent: *\nDisallow: /'))
        self.assertEqual(result['scraper_type'],'MANUAL_REVIEW')
        self.assertEqual(transport.calls,['https://example.test/robots.txt'])

    def test_approved_existing_ean_profile_is_not_rebuilt_or_refetched(self):
        result=assess_shop(ITEM,existing=True,existing_approved=True,
                          transport_factory=lambda *_:self.fail('no requests needed'))
        self.assertEqual(result['scraper_type'],'EAN')
        self.assertEqual(result['build_status'],'EXISTING_EAN_RETAINED')

    def test_unknown_country_does_not_block_candidate_but_is_not_transfer_ready(self):
        result,_=self.assess(fixture())
        self.assertEqual(result['scraper_type'],'ARTIST_TITLE')
        self.assertTrue(result['build_eligible'])
        self.assertFalse(result['assessment_ready'])

    def test_existing_builder_creates_separate_working_artist_title_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            progress={'history':[{'row':1,'status':'DETAIL_GATE_BLOCKED'}]};original=deepcopy(progress)
            def assessor(item,**kwargs):return self.assess(fixture(),country='NL')[0]
            state,records=run([ITEM],progress,{}, {'shops':{}},published=root/'old',quality={},
                              output=root/'new',run_id='test-1',limit=1,assessor=assessor)
            self.assertEqual(progress,original)
            self.assertEqual(records[0]['build_status'],'BUILT_AWAITING_MANUAL_TEST')
            self.assertEqual(records[0]['scraper_type'],'ARTIST_TITLE')
            self.assertEqual(records[0]['build_test_records'],3)
            self.assertEqual(len(list((root/'new').rglob('example_test.py'))),1)
            resumed,_=run([ITEM],progress,state,{},published=root/'old',quality={},
                          output=root/'next',run_id='test-2',limit=1,
                          assessor=lambda *_:self.fail('already assessed'))
            self.assertEqual(resumed,state)

    def test_duplicate_domains_share_one_identity_and_all_source_rows_are_kept(self):
        values=shops([ITEM,dict(ITEM,row=2)],{})
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['queue_rows'],[1,2])

    def test_distinct_social_media_shops_are_not_merged_by_shared_platform_domain(self):
        source=dict(ITEM,domain='facebook.com',source_status='SHARED_PLATFORM')
        values=shops([source,dict(source,row=2,name='Another Store')],{})
        self.assertEqual(len(values),2)
        self.assertNotEqual(values[0]['shop_id'],values[1]['shop_id'])

    def test_historical_assessment_is_immutable(self):
        def update(path,transform,**kwargs):transform('{"old":true}')
        with patch.object(assessment_store.quality_store,'update',side_effect=update),self.assertRaises(ValueError):
            assessment_store.immutable('assessments/v2/old.json','{"new":true}')

    def test_export_is_parseable_with_unknown_counts_and_no_spreadsheet_formula(self):
        text=csv_text([{'name':'=HYPERLINK("bad")','country':'NL','product_count':None}])
        row=next(csv.DictReader(io.StringIO(text)))
        self.assertTrue(row['name'].startswith("'="))
        self.assertEqual(row['country'],'NL')
        self.assertEqual(row['product_count'],'')
        self.assertIn('public_prices',row)

    def test_central_section_does_not_claim_pending_shops_were_evaluated(self):
        text=section([{'name':'One','country':None}])
        self.assertIn('Beoordeeld: **0**',text)
        self.assertIn('Nog te beoordelen',text)


if __name__=='__main__':unittest.main()
