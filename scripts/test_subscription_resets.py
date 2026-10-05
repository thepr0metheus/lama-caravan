#!/usr/bin/env python3
"""Banked resets and remote OAuth, exclusively with fake provider transport."""
import copy
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix='caravan-resets-'))
os.environ['CARAVAN_DATA_DIR'] = str(TMP)
sys.path.insert(0, str(ROOT))
from caravan.admin.subscription_resets import SubscriptionResetDesk
from caravan.admin.cloud_pools import CloudPoolDesk
from caravan.common.subscription_resets import SubscriptionResetJournal
from caravan.common.cloud_sources import CloudSources
from caravan.common.errors import AppError
from caravan.proxy.subscription_pool import SubscriptionPools
from caravan.proxy.subscription_usage import SubscriptionUsage, ReserveGate
from caravan.admin import oauth

class Resets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.journal = SubscriptionResetJournal(Path(self.dir.name)/'resets.json')
        self.now = 1000
        self.sources = CloudSources({'accounts': [
            {'id': 'a', 'accountType': 'openai-subscription'},
            {'id': 'alias', 'testAliasOf': 'a'},
            {'id': 'b', 'accountType': 'openai-subscription'}]})
        self.payload = {'available_count': 3, 'credits': [{'id': 'c', 'reset_type': 'codex_rate_limits', 'status': 'available', 'expires_at': '2030-01-01T00:00:00Z'}]}
        self.calls, self.outcome, self.fail = [], 'reset', False
        self.desk = SubscriptionResetDesk(sources=lambda: self.sources, request=self.request,
                                          journal=self.journal, clock=lambda: self.now)
        self.key = str(uuid.uuid4())

    def tearDown(self): self.dir.cleanup()

    def request(self, account, method, payload=None):
        self.calls.append((account['id'], method, payload))
        if method == 'GET': return copy.deepcopy(self.payload)
        if self.fail: raise AppError('timeout', 502)
        return {'code': self.outcome}

    def consume(self, key=None, account='a', credit='c'):
        return self.desk.consume(account, credit, key or self.key, True)

    def test_listing_never_posts_and_keeps_authoritative_count(self):
        result = self.desk.list('alias')
        self.assertEqual(result['availableCount'], 3)  # capped details != count
        self.assertEqual(result['accountId'], 'a')
        self.assertTrue(result['credits'][0]['usable'])
        self.assertEqual([c[1] for c in self.calls], ['GET'])
        self.assertFalse(self.journal.path.exists())

    def test_bad_unknown_expired_details_are_not_available(self):
        for field, value in [('status','redeeming'),('reset_type','unknown'),('expires_at','1970-01-01T00:00:00Z')]:
            saved = copy.deepcopy(self.payload)
            self.payload['credits'][0][field] = value
            self.assertFalse(self.desk.list('a')['credits'][0]['usable'])
            with self.assertRaises(AppError): self.consume()
            self.payload = saved
        self.assertFalse(any(c[1]=='POST' for c in self.calls))
        self.payload.pop('credits')
        with self.assertRaises(AppError): self.desk.list('a')

    def test_requires_confirmation_uuid_and_known_credit(self):
        for args in [('a','c',self.key,False),('a','c','oops',True),('a','missing',self.key,True),('missing','c',self.key,True)]:
            with self.assertRaises(AppError): self.desk.consume(*args)
        self.assertFalse(any(c[1]=='POST' for c in self.calls))

    def test_success_repeat_alias_and_concurrent_calls_spend_once(self):
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(lambda _: self.consume(account='alias'), range(6)))
        self.assertTrue(all(r['outcome']=='reset' for r in results))
        posts = [c for c in self.calls if c[1]=='POST']
        self.assertEqual(posts, [('a','POST',{'credit_id':'c','redeem_request_id':self.key})])
        self.assertEqual(self.journal.reset_at('a'), self.now)
        self.assertEqual(self.journal.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(AppError): self.consume(account='b')

    def test_unknown_outcome_requires_same_id_after_restart(self):
        self.fail = True
        with self.assertRaises(AppError): self.consume()
        listed = self.desk.list('alias')
        self.assertEqual(listed['pending'], [{'idempotencyKey':self.key,'creditId':'c'}])
        with self.assertRaises(AppError): self.consume(key=str(uuid.uuid4()))
        self.assertEqual(self.journal.reset_at('a'), 0)
        self.fail = False
        self.outcome = 'already_redeemed'
        self.payload['credits'][0]['status'] = 'redeemed'
        self.desk = SubscriptionResetDesk(sources=lambda:self.sources, request=self.request, journal=self.journal, clock=lambda:self.now)
        self.assertEqual(self.consume()['outcome'], 'already_redeemed')
        self.assertEqual([c[2]['redeem_request_id'] for c in self.calls if c[1]=='POST'], [self.key,self.key])
        self.assertEqual(self.desk.list('a')['pending'], [])

    def test_nothing_to_reset_no_credit_and_unknown_result(self):
        for outcome in ['nothing_to_reset','no_credit']:
            self.outcome = outcome
            self.assertEqual(self.consume(key=str(uuid.uuid4()))['outcome'],outcome)
            self.assertEqual(self.journal.reset_at('a'),0)
        self.outcome = 'future_unknown'
        with self.assertRaises(AppError): self.consume()
        self.assertEqual(self.journal.reset_at('a'),0)
        self.assertEqual(len(self.desk.list('a')['pending']),1)

    def test_real_transport_contract_is_mocked(self):
        desk = SubscriptionResetDesk(auth=lambda a:('private-token','private-account'))
        def request(req, timeout):
            self.assertEqual(req.full_url, desk.URL+'/consume')
            self.assertEqual(req.get_method(),'POST')
            self.assertEqual(json.loads(req.data),{'credit_id':'c','redeem_request_id':self.key})
            self.assertEqual(req.get_header('Authorization'),'Bearer private-token')
            return io.BytesIO(b'{"code":"reset"}')
        with patch('urllib.request.urlopen',side_effect=request):
            self.assertEqual(desk._request({},'POST',{'credit_id':'c','redeem_request_id':self.key})['code'],'reset')

    def test_confirmed_reset_invalidates_pool_and_standalone_reserve(self):
        usage = SubscriptionUsage()
        usage.keep('a',[{'seconds':18000,'usedPct':90,'resetAt':2000}],999)
        provider={'id':'a','accountId':'a','usageAccountId':'a','usageReserve':{'18000':20}}
        payload={'rate_limit':{'primary_window':{'used_percent':1,'limit_window_seconds':18000,'reset_at':2000}}}
        fetch = Mock(return_value=payload)
        now = [999]
        selector=SubscriptionPools(usage,fetch,lambda _:provider,lambda _:True,lambda:now[0],listed=lambda a,m:True,event=lambda e:None,resets=self.journal)
        selector.failed({**provider,'poolId':'p'},429)
        self.consume()
        now[0] = 1001
        p,error=selector.resolve({'id':'stable','pool':{'id':'p','name':'P','members':[{'accountId':'a'}],'mode':'auto'}})
        self.assertIsNone(error)
        self.assertEqual(p['accountId'],'a')
        fetch.assert_called_once()
        usage.keep('a',[{'seconds':18000,'usedPct':90,'resetAt':2000}],999)
        gate=ReserveGate(usage,fetch,clock=lambda:1001,resets=self.journal)
        self.assertIsNone(gate.verdict(provider))
        self.assertEqual(fetch.call_count,2)

    def test_reset_does_not_clear_newer_quota_or_auth_failure(self):
        provider={'id':'a','accountId':'a','usageAccountId':'a','poolId':'p'}
        source={'id':'stable','pool':{'id':'p','name':'P','members':[{'accountId':'a'}],'mode':'auto'}}
        self.consume()
        for status, failed_at, reason in [(429,1001,'quota'),(401,999,'auth_rejected')]:
            fetch = Mock()
            selector=SubscriptionPools(SubscriptionUsage(),fetch,lambda _:provider,lambda _:True,lambda:failed_at,listed=lambda a,m:True,event=lambda e:None,resets=self.journal)
            selector.failed(provider,status)
            selector.clock=lambda:1002
            _,error=selector.resolve(source)
            self.assertEqual(error.verdict['members'][0]['reason'],reason)
            fetch.assert_not_called()

class NewSubscriptions(unittest.TestCase):
    def setUp(self):
        self.data={'accounts':[{'id':'a','accountType':'openai-subscription','authMode':'oauth','baseUrl':'https://chatgpt.com'}], 'blocks':[{'id':'model','accountId':'p'}], 'pools':[{'id':'p','name':'Pool','mode':'auto','members':[{'accountId':'a','enabled':False}]}]}
        self.desk=CloudPoolDesk(load=lambda:copy.deepcopy(self.data),save=lambda d:setattr(self,'data',d))

    def test_third_and_more_accounts_wait_for_login_then_join_once(self):
        before=copy.deepcopy(self.data['blocks'])
        for n in range(2,9):
            self.desk.connect_account('p',{'id':f'account-{n}','type':'openai-subscription','name':f'Account {n}'})
        self.assertEqual(len(self.data['pools'][0]['members']),8)
        member=self.data['pools'][0]['members'][2]
        self.assertEqual(member,{'accountId':'account-3','enabled':False,'automatic':True,'pendingLogin':True})
        self.assertEqual(self.desk.complete_login('account-3'),['p'])
        self.assertEqual(self.desk.complete_login('account-3'),[])
        self.assertTrue(self.data['pools'][0]['members'][2]['enabled'])
        self.assertNotIn('pendingLogin',self.data['pools'][0]['members'][2])
        self.desk.complete_login('a')
        self.assertFalse(self.data['pools'][0]['members'][0]['enabled'])
        self.assertEqual(self.data['blocks'],before)

    def test_invalid_or_duplicate_account_never_partly_saves(self):
        before=copy.deepcopy(self.data)
        for pool,account in [('missing',{'id':'new','type':'openai-subscription'}),('p',{'id':'a','type':'openai-subscription'}),('p',{'id':'new','type':'openai'}),('p',{'id':'new','type':'openai-subscription','testAliasOf':'a'})]:
            with self.assertRaises(AppError): self.desk.connect_account(pool,account)
            self.assertEqual(self.data,before)

    def test_policy_edit_cannot_enable_pending_member(self):
        self.desk.connect_account('p',{'id':'new','type':'openai-subscription'})
        pool=copy.deepcopy(self.data['pools'][0])
        pool['members'][1]['enabled']=True
        self.desk.upsert(pool)
        self.assertFalse(self.data['pools'][0]['members'][1]['enabled'])

class RemoteOAuth(unittest.TestCase):
    def setUp(self):
        self.server=Mock(oauth_session={'verifier':'secret-pkce','redirectUri':'http://localhost:1455/auth/callback'})
        oauth._oauth_sessions.clear()
        oauth._oauth_sessions['state']={'accountId':'new','server':self.server,'startedAt':time.time(),'result':{'state':'pending'}}
        self.account={'id':'new'}
        self.data=patch.object(oauth,'load_cloud_data',return_value={'accounts':[self.account]})
        self.exchange=patch.object(oauth,'_exchange_oauth_code',return_value={'access_token':'private-token'})
        self.store=patch.object(oauth,'_store_oauth_tokens',return_value={'email':'new@example.test'})
        self.enable=patch.object(CloudPoolDesk,'complete_login',return_value=[])
        for p in (self.data,self.exchange,self.store,self.enable): p.start()
        self.addCleanup(patch.stopall)
        self.addCleanup(oauth._oauth_sessions.clear)

    def test_pasted_callback_exchanges_once_with_original_pkce(self):
        result=oauth.OAuthLoginDesk.paste_callback('state','http://localhost:1455/auth/callback?code=returned-code&state=state')
        self.assertEqual(result,{'state':'done','email':'new@example.test'})
        self.assertEqual(oauth.OAuthLoginDesk.paste_callback('state','http://localhost:1455/auth/callback?code=returned-code&state=state'),result)
        oauth._exchange_oauth_code.assert_called_once_with(self.account,'returned-code','secret-pkce','http://localhost:1455/auth/callback')
        CloudPoolDesk.complete_login.assert_called_once_with('new')

    def test_foreign_origin_wrong_state_missing_code_and_expiry_refused(self):
        for url in ['https://evil.test/auth/callback?code=x&state=state','http://localhost:1456/auth/callback?code=x&state=state','http://localhost:1455/auth/callback?code=x&state=other','http://localhost:1455/auth/callback?state=state','http://localhost:1455/auth/callback?code=x&code=y&state=state']:
            with self.assertRaises(AppError): oauth.OAuthLoginDesk.paste_callback('state',url)
        oauth._oauth_sessions['state']['startedAt']-=301
        with self.assertRaises(AppError): oauth.OAuthLoginDesk.paste_callback('state','http://localhost:1455/auth/callback?code=x&state=state')
        oauth._exchange_oauth_code.assert_not_called()

    def test_provider_failure_does_not_echo_code_or_enable_member(self):
        oauth._exchange_oauth_code.side_effect=RuntimeError('contains-private-code')
        result=oauth.OAuthLoginDesk.paste_callback('state','http://localhost:1455/auth/callback?code=x&state=state')
        self.assertEqual(result['state'],'error')
        self.assertNotIn('private',json.dumps(result))
        CloudPoolDesk.complete_login.assert_not_called()

    def test_missing_token_never_enables_member(self):
        oauth._exchange_oauth_code.return_value={}
        self.assertEqual(oauth.OAuthLoginDesk.paste_callback('state','http://localhost:1455/auth/callback?code=x&state=state')['state'],'error')
        CloudPoolDesk.complete_login.assert_not_called()
        oauth._store_oauth_tokens.assert_not_called()

    def test_new_member_refreshes_its_pool_catalogue_after_login(self):
        CloudPoolDesk.complete_login.return_value=['p']
        with patch('caravan.admin.model_catalog.kick_refresh') as refresh, patch('caravan.admin.cloud_api.refresh_account_models_cache') as fetch:
            self.assertEqual(oauth.OAuthLoginDesk.paste_callback('state','http://localhost:1455/auth/callback?code=x&state=state')['state'],'done')
            self.assertEqual(refresh.call_args.args[0],'p')
            refresh.call_args.args[1]()
            fetch.assert_called_once_with('p')

if __name__=='__main__': unittest.main(verbosity=2)
