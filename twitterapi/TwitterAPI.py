__author__ = "Jonas Geduldig"
__date__ = "June 7, 2013"
__license__ = "MIT"

import constants
import json
import requests
from requests_oauthlib import OAuth1
import time


STREAM_SOCKET_TIMEOUT = 90 # 90 seconds per Twitter's recommendation
REST_SOCKET_TIMEOUT = 5
REST_SUBDOMAIN = 'api'


class TwitterAPI(object):	
	def __init__(self, consumer_key, consumer_secret, access_token_key, access_token_secret):
		self.session = requests.Session()
		self.session.auth = OAuth1(consumer_key, consumer_secret, access_token_key, access_token_secret)
		
	def _make_url(self, subdomain, path):
		return '%s://%s.%s/%s/%s' % (constants.PROTOCOL, subdomain, constants.DOMAIN, constants.VERSION, path)
		
	def _rest_request(self, resource, params=None):
		method = constants.REST_ENDPOINTS[resource][0]
		url = self._make_url(REST_SUBDOMAIN, resource + '.json')
		self.session.stream = False
		self.response = self.session.request(method, url, params=params, timeout=REST_SOCKET_TIMEOUT)
		return self.response
		
	def _streaming_request(self, resource, params=None):
		method = 'GET' if params is None else 'POST'
		url = self._make_url(constants.STREAMING_ENDPOINTS[resource][0], resource + '.json')
		self.session.stream = True
		self.response = self.session.request(method, url, params=params, timeout=STREAM_SOCKET_TIMEOUT)
		return self.response
		
	def request(self, resource, params=None):
		if resource in constants.REST_ENDPOINTS:
			return self._rest_request(resource, params)
		elif resource in constants.STREAMING_ENDPOINTS:
			return self._streaming_request(resource, params)
		else:
			raise Exception('"%s" is not valid endpoint' % resource)
			
	def get_iterator(self):
		if self.session.stream:
			return StreamingIterator(self.response)
		else:
			return RestIterator(self.response)

	def get_rest_quota(self):
		remaining, limit, reset = None, None, None
		if self.response and not self.session.stream:
			if 'x-rate-limit-remaining' in self.response.headers:
				remaining = int(self.response.headers['x-rate-limit-remaining'])
				if remaining == 0:
					limit = int(self.response.headers['x-rate-limit-limit'])
					reset = int(self.response.headers['x-rate-limit-reset'])
					reset = datetime.fromtimestamp(reset)
		return {'remaining': remaining, 'limit': limit, 'reset': reset}

				
class RestIterator(object):
	def __init__(self, response):
		resp = response.json()
		if 'errors' in resp:
			self.results = resp['errors']
		elif 'statuses' in resp:
			self.results = resp['statuses']
		elif hasattr(resp, '__iter__'):
			if len(resp) > 0 and 'trends' in resp[0]:
				self.results = resp[0]['trends']
			else:
				self.results = resp
		else:		
			self.results = (resp,)
		
	def __iter__(self):
		for item in self.results:
			yield item
				
				
class StreamingIterator(object):
	def __init__(self, response):
		self.response = response
		
	def __iter__(self):
		for item in self.response.iter_lines():
			if item:
				yield json.loads(item)
	

class TwitterRestPager(object):
	def __init__(self, api, resource, params=None):
		self.api = api
		self.resource = resource
		self.params = params

	def get_iterator(self, wait=5, new_tweets=False):
		while True:
			# get one page of results
			self.api._rest_request(self.resource, self.params)
			iter = self.api.get_iterator()
			if new_tweets:
				iter.results = reversed(iter.results)
				
			# yield each item in the page
			id = None
			for item in iter:
				if 'id' in item:
					id = item['id']
				yield item
				
			# sleep before getting another page of results
			time.sleep(wait)
			
			# depending on the newer/older direction, use the first or last tweet id to limit
			# the next request
			if id is None:
				break
			elif new_tweets:
				self.params['since_id'] = str(id)
			else:
				self.params['max_id'] = str(id - 1)