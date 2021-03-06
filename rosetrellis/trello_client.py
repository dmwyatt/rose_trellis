from asyncio import Semaphore, BaseEventLoop
import logging
import os
import asyncio
import pprint
import time
import collections

import aiohttp
from typing import Any, Union, List, Sequence, Tuple

import rosetrellis.util


__all__ = ('TrelloClient',)

logger = logging.getLogger(__name__)


class InvalidIdError(Exception):
	pass


class CommFail(Exception):
	def __init__(self, message, url, params, status, response):
		super(CommFail, self).__init__(message)
		self.url = url
		self.params = params
		self.status = status
		self.response = response

	def __str__(self):
		return "Error communicating with Trello:\n" \
		       "url: {}\nparams: {}\nstatus:{}\nresponse:{}".format(self.url,
		                                                            pprint.pformat(self.params),
		                                                            self.status,
		                                                            self.response)


def _prepare_list_param(list_param: Union[Sequence[str], str]) -> Union[str, None]:
	if not list_param == "default":
		if isinstance(list_param, str):
			# pretty up a comma-separated list of strings
			list_param = [s.strip() for s in list_param.split(',')]
		return ','.join(list_param)


def _parse_batch(batch_resp: list) -> Tuple[Union[List[dict], List[tuple]]]:
	good = []
	bad = []

	for obj in batch_resp:
		# Not sure if this will always be valid.  Let's keep an eye on it.
		assert len(obj) == 1
		for k, v in obj.items():
			if k == '200':
				good.append(v)
			else:
				bad.append((k, v))

	return good, bad


def _dict_to_params(data: dict, field_names: List[str]) -> dict:
	params = {}
	for field in field_names:
		value = data.get(field)
		if value:
			params[field] = value
	return params


class CachedUrl:
	def __init__(self, url: str, params: Union[None, dict]=None) -> None:
		self.url = url
		self.params = params if params else {}

	def __hash__(self) -> None:
		return hash((self.url, tuple(self.params.items())))

	def __eq__(self, other: Any) -> bool:
		if type(other) is type(self):
			return self.__dict__ == other.__dict__
		else:
			return NotImplemented

	def __repr__(self) -> str:
		return "CachedUrl('{}', {})".format(self.url, self.params)


class CachedUrlDict(dict):
	def __init__(self, *args, **kwargs) -> None:
		try:
			self.expire_seconds = kwargs['expire_seconds']
		except KeyError:
			raise ValueError("Must provide expire_seconds kwarg to CacheDict")

		super(CachedUrlDict, self).__init__(*args, **kwargs)

	def vacuum(self) -> None:
		for k, v in self.items():
			if self._is_expired(v):
				del self[k]

	def _is_expired(self, value: tuple) -> bool:
		return time.time() - value[0] > self.expire_seconds

	def __getitem__(self, key: CachedUrl) -> Union[None, list, dict]:
		value = super(CachedUrlDict, self).__getitem__(key)

		if self._is_expired(value):
			logger.debug('cache expiration')
			del self[key]
		else:
			return value[1]

	def __setitem__(self, key: CachedUrl, value: Union[list, dict]):
		if not isinstance(key, CachedUrl):
			raise ValueError('You may only use CachedUrl instances as keys in CachedUrlDict')
		super(CachedUrlDict, self).__setitem__(key, (time.time(), value))


class TrelloClientCardMixin:
	@asyncio.coroutine
	def create_card(self, data: dict) -> dict:
		url = 'cards'
		return (yield from self.post(url, params=data))

	def get_card_url(self, card_id: str) -> str:
		return 'cards/{}'.format(card_id)

	@asyncio.coroutine
	def get_card(self, card_id, case_insensitive: bool=True, fields: Union[Sequence[str], str]="default") -> dict:
		url = self.get_card_url(card_id)
		if not fields:
			return (yield from self.get(url))
		else:
			params = {}
			fields = _prepare_list_param(fields)
			if fields:
				params['fields'] = fields
			return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def get_cards(self, cards: List[str]) -> Tuple[Union[List[dict], List[tuple]]]:
		urls = ['/cards/{}'.format(cid) for cid in cards]
		cards = yield from self.batch_get(urls)
		return _parse_batch(cards)

	@asyncio.coroutine
	def get_cards_for_board(self, board_id: str) -> List[dict]:
		url = 'board/{}/cards'.format(board_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def update_card(self, card_id: str, data: dict):
		url = 'cards/{}'.format(card_id)
		return (yield from self.put(url, params=data))

	@asyncio.coroutine
	def get_card_attachments(self, card_id):
		url = 'checklists/{}/attachments'
		return

	@asyncio.coroutine
	def get_card_attachment(self, card_id: str, attachment_id: str):
		url = 'cards/{}/attachments/{}'.format(card_id, attachment_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def delete_card(self, card_id):
		url = 'cards/{}'.format(card_id)
		return (yield from self.delete(url))


class TrelloClientChecklistMixin:
	@asyncio.coroutine
	def get_checklist(self, checklist_id: str,
	                  include_card: bool=True,
	                  card_fields: str="all",
	                  include_check_items: bool=True,
	                  check_item_fields: str="",
	                  fields: str="all") -> dict:
		url = 'checklists/{}'.format(checklist_id)
		params = {}
		params['cards'] = "all" if include_card else "none"
		params['card_fields'] = card_fields
		params['checkItems'] = "all" if include_check_items else "none"
		if check_item_fields:
			params['checkItem_fields'] = check_item_fields
		params['fields'] = fields

		return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def delete_checklist(self, checklist_id: str):
		url = 'checklists/{}'.format(checklist_id)
		return (yield from self.delete(url))

	@asyncio.coroutine
	def update_checklist(self, checklist_id: str, changes: dict) -> dict:
		url = 'checklists/{}'.format(checklist_id)
		return (yield from self.put(url, params=changes))

	@asyncio.coroutine
	def create_checklist(self, data: dict) -> dict:
		url = 'checklists'
		return (yield from self.post(url, params=data))


class TrelloClientCheckItemMixin:
	@asyncio.coroutine
	def get_checkitem(self, checklist_id: str, checkitem_id: str) -> dict:
		url = 'checklists/{}/checkItems/{}'.format(checklist_id, checkitem_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def delete_checkitem(self, card_id: str, checklist_id: str, checkitem_id: str) -> dict:
		url = "cards/{card_id}/checklist/{checklist_id}/checkItem/{checkitem_id}"
		url = url.format(card_id=card_id, checklist_id=checklist_id, checkitem_id=checkitem_id)
		return (yield from self.delete(url))

	@asyncio.coroutine
	def update_checkitem(self, card_id: str, checklist_id: str, checkitem_id: str, data: dict) -> dict:
		url = "cards/{card_id}/checklist/{checklist_id}/checkItem/{checkitem_id}"
		url = url.format(card_id=card_id, checklist_id=checklist_id, checkitem_id=checkitem_id)
		if 'state' in data:
			data['state'] = str(data['state']).lower()

		return (yield from self.put(url, params=data))

	@asyncio.coroutine
	def create_checkitem(self, checklist_id: str, data: dict) -> dict:
		url = "checklists/{}/checkItems".format(checklist_id)
		return (yield from self.post(url, params=data))


class TrelloClientBoardMixin:
	def get_board_url(self, board_id: str) -> str:
		return 'boards/{}'.format(board_id)

	@asyncio.coroutine
	def create_board(self, data: dict) ->dict:
		return (yield from self.post('boards', params=data))

	@asyncio.coroutine
	def get_board(self, board_id: str, fields: Union[Sequence[str], str]="default") -> dict:
		url = self.get_board_url(board_id)
		if not fields:
			return (yield from self.get(url))
		else:
			params = {}
			fields = _prepare_list_param(fields)
			if fields:
				params['fields'] = fields
			return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def get_boards(self, only_open: bool=True) -> List[dict]:
		url = 'member/me/boards'
		params = {}
		if only_open:
			params['filter'] = 'open'
		return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def update_board(self, board_id, data: dict) -> dict:
		url = 'boards/{}'.format(board_id)
		return (yield from self.put(url, params=data))

	@asyncio.coroutine
	def get_board_lists(self, board_id) -> Sequence[str]:
		url = 'boards/{}/lists'.format(board_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def get_board_cards(self, board_id) -> Sequence[str]:
		url = 'boards/{}/cards'.format(board_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def get_board_checklists(self, board_id) -> Sequence[dict]:
		url = 'boards/{}/checklists'.format(board_id)
		return (yield from self.get(url))


class TrelloClientLabelMixin:
	@asyncio.coroutine
	def get_label(self, label_id: str) -> dict:
		url = 'labels/{}'.format(label_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def create_label(self, data: dict) ->  dict:
		return (yield from self.post('labels', data))

	@asyncio.coroutine
	def get_labels(self, board_id: str) -> list:
		url = 'board/{}/labels'.format(board_id)
		return (yield from self.get(url))

	@asyncio.coroutine
	def update_label(self, label_id: str, data: dict) -> dict:
		url = 'labels/{}'.format(label_id)
		return (yield from self.put(url, params=data))

	@asyncio.coroutine
	def delete_label(self, label_id: str) -> dict:
		url = 'labels/{}'.format(label_id)
		return (yield from self.delete(url))


class TrelloClientOrgMixin:
	@asyncio.coroutine
	def get_organization(self, org_id: str, fields: Union[Sequence[str], str]="default") -> dict:
		url = 'organizations/{}'.format(org_id)
		params = {}
		fields = _prepare_list_param(fields)
		if fields:
			params['fields'] = fields
		return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def delete_organization(self, org_id: str) -> dict:
		url = 'organizations/{}'.format(org_id)
		return (yield from self.delete(url))

	@asyncio.coroutine
	def update_organization(self, org_id: str, params: dict) -> dict:
		url = 'organization/{}'.format(org_id)
		return (yield from self.put(url, params=params))

	@asyncio.coroutine
	def create_organization(self, data: dict) -> dict:
		url = 'organization'

		if 'powerUps' in data:
			data['powerUps'] = _prepare_list_param(data['powerUps'])

		fields = ['name', 'desc', 'idOrganization', 'idBoardSource', 'keepFromSource',
		          'powerUps', 'prefs_permissionLevel', 'prefs_voting', 'prefs_comments',
		          'prefs_invitations', 'prefs_selfJoin', 'prefs_cardCovers',
		          'prefs_background', 'prefs_cardAging']

		return (yield from self.create(url, data, fields))


class TrelloClientListsMixin:
	@asyncio.coroutine
	def get_list(self, list_id: str, fields: Union[Sequence[str], str]="default") -> dict:
		url = 'lists/{}'.format(list_id)
		params = {}
		fields = _prepare_list_param(fields)
		if fields:
			params['fields'] = fields
		return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def create_list(self, data: dict) ->dict:
		return (yield from self.post('lists', params=data))

	@asyncio.coroutine
	def delete_list(self, list_id: str) -> dict:
		url = "lists/{}".format(list_id)
		return (yield from self.delete(url))

	@asyncio.coroutine
	def update_list(self, list_id, changes: dict) -> dict:
		url = 'lists/{}'.format(list_id)
		return (yield from self.put(url, params=changes))

	@asyncio.coroutine
	def archive_cards_on_list(self, list_id):
		url = "lists/{}/archiveAllCards".format(list_id)
		return (yield from self.post(url))


class TrelloClientMemberMixin:
	@asyncio.coroutine
	def get_member(self, id_: str="me", fields: Union[Sequence[str], str]="default") -> dict:
		params = {}
		fields = _prepare_list_param(fields)
		if fields:
			params['fields'] = fields
		url = 'member/{}'.format(id_)
		return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def update_member(self, id_: str, params: dict) -> dict:
		url = 'member/{}'.format(id_)
		return (yield from self.put(url, params=params))


class TrelloClient(TrelloClientCardMixin,
                   TrelloClientChecklistMixin,
                   TrelloClientCheckItemMixin,
                   TrelloClientBoardMixin,
                   TrelloClientLabelMixin,
                   TrelloClientOrgMixin,
                   TrelloClientListsMixin,
                   TrelloClientMemberMixin):
	def __init__(self,
	             api_key: str=None,
	             api_token: str=None,
	             verify_credentials: bool=False,
	             cache_for: int=10,
	             loop: BaseEventLoop=None) -> None:
		self._api_key = api_key if api_key else os.environ.get('TRELLO_API_KEY')
		self._api_token = api_token if api_token else os.environ.get('TRELLO_API_TOKEN')

		err_msg = ""
		example = "\n>>> TrelloClient(api_key='your api key here', api_token='your api token here')\n"
		if not self._api_key:
			err_msg += "Unable to get api key from environment variable TRELLO_API_KEY.  Either set envvar or provide it to this constructor like so: {}".format(
				example)

		if not self._api_token:
			msg = "Unable to get api token from environment variable TRELLO_API_TOKEN.  Either set envvar or provide it to this constructor like so: {}".format(
				example)
			if not err_msg:
				err_msg = msg
			else:
				err_msg += "\n"
				err_msg += msg

		if err_msg:
			raise ValueError(err_msg)

		self._conx_sema = Semaphore(5)
		self._cache = CachedUrlDict(expire_seconds=cache_for)

		self._request_history = collections.deque([], 100)

	@asyncio.coroutine
	def get(self, url, params=None):
		logger.debug("GETing.  url: '%s' params: %s", url, params)
		if not params:
			params = {}

		result = yield from self.request(url, 'get', params)
		# logger.debug(result)
		return result

	@asyncio.coroutine
	def post(self, url, params=None):
		logger.debug("POSTing.  url: '%s' params: %s", url, params)
		if not params:
			params = {}

		return (yield from self.request(url, 'post', params))

	@asyncio.coroutine
	def put(self, url, params=None):
		logger.debug("PUTing.  url: '%s' params: %s", url, params)
		if not params:
			params = {}

		return (yield from self.request(url, 'put', params))

	@asyncio.coroutine
	def delete(self, url, params=None):
		logger.debug("DELETEing.  url: '%s' params: %s", url, params)
		if not params:
			params = {}

		return (yield from self.request(url, 'delete', params))

	@asyncio.coroutine
	def request(self, url, method, params):
		if method.lower() == 'get':
			# We cache all get requests...
			cached_url = CachedUrl(url, params)
			try:
				cached = self._cache[cached_url]
			except KeyError:
				# haven't cached this yet
				logger.debug("cache miss")
				cached = None

			if cached:
				# CACHE HIT!
				logger.debug("cache hit")
				return cached

		params['key'] = self._api_key
		params['token'] = self._api_token

		if len(self._request_history) == self._request_history.maxlen:
			now = time.time()

			past = now - 10 * 1000

			oldest_request_time = self._request_history[0]
			oldest_request_time_delta = now - oldest_request_time

			if oldest_request_time_delta <= past:
				throttle_time = past - oldest_request_time_delta
				logger.debug("Throttling for {} seconds".format(throttle_time))
				yield from asyncio.sleep(throttle_time)

		logger.debug("current connections: {}".format(self._conx_sema._value))
		with (yield from self._conx_sema):
			self._request_history.append(time.time())
			r = yield from aiohttp.request(method, rosetrellis.util.join_url(url), params=params)

		if 200 <= r.status > 299:
			logger.error("Received bad status: %s.  Response content: %s", r.status, (yield from r.text()))
			if "invalid id" in (yield from r.text()).lower():
				raise InvalidIdError('{} (url: {})'.format((yield from r.text()), url))

			raise CommFail("Error communicating with Trello", url, params, r.status, (yield from r.text()))

		json = yield from r.json()
		if method.lower() == 'get':
			self._cache[cached_url] = json

		return json

	@asyncio.coroutine
	def batch_get(self, routes: List[Union[Sequence[str], str]]):
		url = 'batch'
		params = {'urls': _prepare_list_param(routes)}
		return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def create(self, url: str, data: dict, post_fields: List[str]) -> dict:
		params = _dict_to_params(data, post_fields)
		return (yield from self.post(url, params=params))
