from asyncio import Semaphore, BaseEventLoop
import logging
import os
import asyncio
import random
from sqlite3.dbapi2 import paramstyle
import time

import aiohttp
from typing import Any, Union, List, Sequence, Tuple

import rose_trellis.util


__all__ = ('TrelloClient',)

logger = logging.getLogger(__name__)


class InvalidIdError(Exception):
	pass


class CommFail(Exception):
	pass

def prepare_list_param(list_param: Union[Sequence[str], str]) -> Union[str, None]:
	if not list_param == "default":
		if isinstance(list_param, str):
			# pretty up a comma-separated list of strings
			list_param = [s.strip() for s in list_param.split(',')]
		return ','.join(list_param)

def parse_batch(batch_resp: list) -> Tuple[Union[List[dict], List[tuple]]]:
	good = []
	bad = []

	for card in batch_resp:
		# Not sure if this will always be valid.  Let's keep an eye on it.
		assert len(card) == 1
		for k, v in card.items():
			if k == '200':
				good.append(v)
			else:
				bad.append((k, v))

	return good, bad


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

	def _getitem__(self, key: CachedUrl) -> Union[None, list, dict]:
		value = super(CachedUrlDict, self)._getitem__(key)

		if self._is_expired(value):
			del self[key]
		else:
			return value[1]

	def __setitem__(self, key: CachedUrl, value: Union[list, dict]):
		if not isinstance(key, CachedUrl):
			raise ValueError('You may only use CachedUrl instances as keys in CachedUrlDict')
		super(CachedUrlDict, self).__setitem__(key, (time.time(), value))


class TrelloClientCardMixin:
	@asyncio.coroutine
	def create_card(self, card_name: str, list_id: str, desc: str="", pos: str='bottom', due: str='null',
	                labels: str='') -> dict:
		params = {
			"idList": list_id,
			"name": card_name,
			"pos": pos,
			"due": due
		}
		if desc:
			params['desc'] = desc
		if labels:
			params['labels'] = labels

		url = 'cards'
		return (yield from self.post(url, params))

	@asyncio.coroutine
	def get_card(self, card_id, case_insensitive: bool=True, fields: Union[Sequence[str], str]="default") -> dict:
		url = 'cards/{}'.format(card_id)
		if not fields:
			return (yield from self.get(url))
		else:
			params = {}
			fields = prepare_list_param(fields)
			if fields:
				params['fields'] = fields
			return (yield from self.get(url, params=params))

	@asyncio.coroutine
	def get_cards(self, cards: List[str]) -> Tuple[Union[List[dict], List[tuple]]]:
		urls = ['/cards/{}'.format(cid) for cid in cards]
		cards = yield from self.batch_get(urls)
		return parse_batch(cards)

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


class TrelloClientBoardMixin:
	@asyncio.coroutine
	def get_board(self, board_id: str, fields: Union[Sequence[str], str]="default") -> dict:
		url = 'boards/{}'.format(board_id)
		if not fields:
			return (yield from self.get(url))
		else:
			params = {}
			fields = prepare_list_param(fields)
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


class TrelloClientLabelMixin:
	@asyncio.coroutine
	def get_label(self, label_id: str) -> dict:
		url = 'labels/{}'.format(label_id)
		return (yield from self.get(url))

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
		url = 'organization/{}'.format(org_id)
		params = {}
		fields = prepare_list_param(fields)
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

class TrelloClientListsMixin:
	@asyncio.coroutine
	def get_list(self, list_id: str, fields: Union[Sequence[str], str]="default") -> dict:
		url = 'lists/{}'.format(list_id)
		params = {}
		fields = prepare_list_param(fields)
		if fields:
			params['fields'] = fields
		return (yield from self.get(url, params=params))

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


class TrelloClient(TrelloClientCardMixin,
                   TrelloClientChecklistMixin,
                   TrelloClientCheckItemMixin,
                   TrelloClientBoardMixin,
                   TrelloClientLabelMixin,
                   TrelloClientOrgMixin,
                   TrelloClientListsMixin):
	def __init__(self,
	             api_key: str=None,
	             api_token: str=None,
	             verify_credentials: bool=False,
	             cache_for: int=10,
	             loop: BaseEventLoop=None) -> None:
		self._api_key = api_key if api_key else os.environ.get('TRELLO_API_KEY')
		self._api_token = api_token if api_token else os.environ.get('TRELLO_API_TOKEN')

		if not self._api_key:
			raise ValueError(
				"Unable to get api key from environment variable TRELLO_API_KEY.  Either set envvar or provide it to this constructor.")

		if not self._api_token:
			raise ValueError(
				"Unable to get api token from environment variable TRELLO_API_TOKEN.  Either set envvar or provide it to this constructor.")

		self._conx_sema = Semaphore(5)
		self._cache = CachedUrlDict(expire_seconds=cache_for)

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
				cached = None

			if cached:
				# CACHE HIT!
				return cached

		params['key'] = self._api_key
		params['token'] = self._api_token

		with (yield from self._conx_sema):
			r = yield from aiohttp.request(method, rose_trellis.util.join_url(url), params=params)

		retry_count = 0
		while r.status == 429 and retry_count < 10:
			with (yield from self._conx_sema):
				r = yield from aiohttp.request(method, rose_trellis.util.join_url(url), params=params)
			if r.status == 429 and retry_count < 10:
				logger.warning('Rate limited by Trello!')
				asyncio.sleep(random.random() * 5)

		if 200 <= r.status > 299:
			logger.error("Received bad status: %s.  Response content: %s", r.status, (yield from r.text()))
			if "invalid id" in (yield from r.text()).lower():
				raise InvalidIdError('{} (url: {})'.format((yield from r.text()), url))

			raise CommFail(
				'Error communicating with Trello.  Status: {}, result: {}'.format(r.status, (yield from r.text())))
		json = yield from r.json()
		if method.lower() == 'get':
			self._cache[cached_url] = json

		return json
	
	@asyncio.coroutine
	def batch_get(self, routes: List[Union[Sequence[str], str]]):
		url = 'batch'
		params = {'urls': prepare_list_param(routes)}
		return (yield from self.get(url, params=params))
