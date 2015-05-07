import abc
import asyncio
import logging
import time
import itertools

from dateutil import parser
from typing import Any, Tuple, List, Union

import rose_trellis.base.obj_cache as obj_cache
import rose_trellis.trello_client as trello_client


logger = logging.getLogger(__name__)


class TrelloObjectCollection(list):
	def save(self):
		save_coros = [obj.save() for obj in self]
		yield from asyncio.gather(*save_coros)

	def inflate(self):
		inflate_coros = [obj.inflate() for obj in self]
		yield from asyncio.gather(*inflate_coros)


class TrelloObject(metaclass=abc.ABCMeta):
	def __init__(self, id_: str, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs) -> None:
		self.tc = tc
		self.id = id_
		self._refreshed_at = 0
		self.opts = kwargs
		self.inflate_children = inflate_children

	@classmethod
	@asyncio.coroutine
	def get(cls, data_or_id: Union[str, dict], tc: trello_client.TrelloClient, inflate_children=True,
	        **kwargs) -> 'TrelloObject':
		if isinstance(data_or_id, str):
			id_ = data_or_id
			data = None
		elif isinstance(data_or_id, dict):
			id_ = data_or_id['id']
			data = data_or_id
		else:
			raise TypeError("Must provide either a str id or a dict of object data")

		obj = obj_cache.get(id_)
		if not obj and not data:
			resp = yield from cls.get_data(id_, tc, **kwargs)
			obj = cls(resp['id'], tc, inflate_children=inflate_children, **kwargs)
			obj_cache.set(obj)
			yield from obj.state_from_api(resp)
		elif not obj and data:
			obj = cls(data['id'], tc, inflate_children=inflate_children, **kwargs)
			obj_cache.set(obj)
			yield from obj.state_from_api(data)
		elif obj and data:
			yield from obj.state_from_api(data)

		return obj

	@classmethod
	@asyncio.coroutine
	def get_many(cls, datas_or_ids: List[Union[str, dict]], tc: trello_client.TrelloClient,
	             inflate_children=True, **kwargs) -> TrelloObjectCollection:
		getters = [cls.get(doi, tc, inflate_children=inflate_children, **kwargs) for doi in datas_or_ids]

		results = yield from asyncio.gather(*getters)
		return TrelloObjectCollection(results)

	@asyncio.coroutine
	def delete(self):
		response = self.delete_from_api(self.id)
		obj_cache.remove(self.id)
		for k, v in self._raw_data:
			delattr(self, k)

	@asyncio.coroutine
	def save(self) -> None:
		"""Saves changes to Trello api"""
		changes = self.get_api_from_state()
		if changes:
			new_data = yield from self.changes_to_api(changes)
			self.state_from_api(new_data)

	@asyncio.coroutine
	def inflate(self):
		data = yield from self.get_data(self.id, self.tc)
		yield from self.state_from_api(data)

	@asyncio.coroutine
	def state_from_api(self, api_data):
		self._raw_data = api_data
		for k, v in api_data.items():
			if self.inflate_children:
				field_name, inflated = yield from _api_field_to_obj_field(k, v, self.tc)
				setattr(self, field_name, inflated)
			else:
				setattr(self, k, v)

		self._refreshed_at = time.time()

	@abc.abstractclassmethod
	def get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs) -> dict:
		"""Retrieves data from Trello for the provided id.
		Implementers return a dict of data used to inflate the object."""

	@abc.abstractclassmethod
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs) -> TrelloObjectCollection:
		"""Retrieves all instances of this object."""

	@abc.abstractmethod
	def delete_from_api(self) -> None:
		"""Deletes object from Trello API"""

	@abc.abstractmethod
	def changes_to_api(self, changes: dict) -> dict:
		"""Sends data to Trello API"""

	@abc.abstractmethod
	def get_api_from_state(self) -> dict:
		"""Returns how current state differs from original data."""


class Organization(TrelloObject):
	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient) -> dict:
		return (yield from tc.get_organization(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def delete_from_api(self):
		yield from self.tc.delete_organization(self.id)

	@asyncio.coroutine
	def changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_organization(self.id, changes))

	def get_api_from_state(self):
		changes = {}
		if self.name != self.raw_data['name']:
			changes['name'] = self.name
		if self.displayName != self._raw_data['displayName']:
			changes['displayName'] = self.displayName
		if self.desc != self._raw_data['desc']:
			if self.desc is None:
				changes['desc'] = ''
			else:
				changes['desc'] = self.desc

		new_ws = '' or self.website
		if new_ws != self._raw_data['website']:
			if new_ws:
				if not new_ws.startswith('http://') or not new_ws.startswith('https://'):
					raise ValueError('Organization.website must start with "http://" or "https://')
			else:
				changes['website'] = new_ws

		return changes

	def __repr__(self):
		if self._refreshed_at:
			return "<Organization: displayName='{}', id='{}')>".format(self.displayName, self.id)
		else:
			return "<Organization: id='{}'>".format(self.id)


class Board(TrelloObject):
	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_board(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs):
		only_open = kwargs.get('only_open', True)
		boards_data = yield from tc.get_boards(only_open=only_open)
		return (yield from cls.get_many(boards_data, tc))

	@asyncio.coroutine
	def delete_from_api(self):
		raise NotImplementedError("Trello does not permit deleting of boards.  Try `Board.close()`")

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.update_board(self.id, changes))

	@asyncio.coroutine
	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.desc != self._raw_data['desc']:
			changes['desc'] = self.desc
		if self.closed != self._raw_data['closed']:
			changes['closed'] = self.closed
		if self.organization.id != self._raw_data['idOrganization']:
			changes['idOrgaizatio'] = self.organization.id

		changes.update(self.prefs.get_api_from_state())

		return changes

	@asyncio.coroutine
	def get_labels(self):
		return (yield from Label.get_labels(self.id, self.tc))

	@asyncio.coroutine
	def get_lists(self) -> TrelloObjectCollection:
		lists_data = yield from self.tc.get_board_lists(self.id)
		return (yield from Lists.get_many(lists_data, self.tc))

	def __repr__(self):
		if self._refreshed_at:
			return "<Board: name='{}', id='{}')>".format(self.name, self.id)
		else:
			return "<Board: id='{}'>".format(self.id)


class BoardPrefs:
	attr_mapping = [
		('permissionLevel', 'permissionLevel', 'private'),
		('voting', 'voting', 'disabled'),
		('comments', 'comments', 'members'),
		('invitations', 'invitations', 'members'),
		('selfJoin', 'selfJoin', True),
		('cardCovers', 'cardCovers', True),
		('cardAging', 'cardAging', 'regular'),
		('background', 'background', 'blue'),
		('calendarFeedEnabled', 'calendarFeedEnabled', True)
	]

	required_fields = ['permissionLevel', 'voting', 'comments', 'invitations', 'selfJoin', 'cardCovers', 'background',
	                   'calendarFeedEnabled']

	def __init__(self, api_prefs_dict: dict) -> None:
		BoardPrefs.validate_board_prefs_data(api_prefs_dict)
		self.state_from_api(api_prefs_dict)

	@classmethod
	def validate_board_prefs_data(cls, data: dict) -> bool:
		for attr_name in cls.required_fields:
			if not attr_name in data:
				raise ValueError("BoardPrefs data requires a field called '{}'".format(attr_name))

	def state_from_api(self, api_prefs_dict: dict) -> None:
		self._raw_data = api_prefs_dict
		for mapping in self.attr_mapping:
			self.set_attr(api_prefs_dict, *mapping)

	def set_attr(self, prefs_dict: dict, api_pref_name: str, attr_name: str, default: Any) -> None:
		setattr(self, attr_name, prefs_dict.get(api_pref_name, default))

	def get_api_from_state(self) -> dict:
		changes = {}
		for api_field, obj_attr, __ in self.attr_mapping:
			if self._raw_data.get(api_field) != getattr(self, obj_attr):
				changes['prefs/{}'.format(api_field)] = getattr(self, obj_attr)
		return changes

	def __repr__(self):
		rep = "<BoardPrefs: "
		for api_field, obj_attr, __ in self.attr_mapping:
			rep += "{}={} ".format(obj_attr, getattr(self, obj_attr))
		rep = rep.strip()
		rep += ">"
		return rep


class Lists(TrelloObject):
	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs):
		return (yield from tc.get_list(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs) -> TrelloObjectCollection:
		boards = yield from Board.get_all(tc)
		lists_getters = [b.get_lists() for b in boards]
		lists = list(itertools.chain.from_iterable((yield from asyncio.gather(*lists_getters))))
		return TrelloObjectCollection(lists)

	@asyncio.coroutine
	def delete_from_api(self):
		raise NotImplementedError("Trello does not permit list deletion.  Try closing the list instead.")

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.update_list(self.id, changes))

	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.board.id != self._raw_data['idBoard']:
			changes['idBoard'] = self.board.id
		if self.pos != self._raw_data['pos']:
			changes['pos'] = self.pos
		if self.subscribed != self._raw_data['subscribed']:
			changes['subscribed'] = self.subscribed

		return changes

	def __repr__(self):
		if self._refreshed_at:
			return "<List: name='{}', id='{}'>".format(self.name, self.id)
		else:
			return "<List: id='{}'>".format(self.id)


class Card(TrelloObject):
	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient) -> dict:
		return (yield from tc.get_card(card_id=id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def delete_from_api(self):
		yield from self.tc.delete_card(self.id)

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.updatE_card(changes))

	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.desc != self._raw_data['desc']:
			changes['desc'] = self.desc
		if self.closed != self._raw_data['closed']:
			changes['closed'] = self.closed

		raw_data_colors = sorted([l['color'] for l in self._raw_data['colors']])
		state_colors = sorted(self.label_colors)

		if raw_data_colors != state_colors:
			changes['labels'] = ','.join(state_colors)

		return changes

	@asyncio.coroutine
	def state_from_api(self, api_data):
		if 'labels' in api_data and self.inflate_children:
			# Redundant info caused by using 'all' filter when getting
			# card data
			try:
				del api_data['idLabels']
			except KeyError:
				pass

		yield from super(Card, self).state_from_api(api_data)

	@property
	def label_colors(self):
		return [l.color for l in self.labels]

	def __repr__(self):
		if self._refreshed_at:
			return "<Card: name='{}', id='{}'>".format(self.name, self.id)
		else:
			return "<Card: id='{}'>".format(self.id)


class Checklist(TrelloObject):
	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_checklist(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def delete_from_api(self):
		return (yield from self.tc.delete_checklist(self.id))

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.update_checklist(self.id, changes))

	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.pos != self._raw_data['pos']:
			changes['pos'] = self.pos


		if hasattr(self, 'card'):
			# if object was created with inflate_children=False, then we won't have a card instance
			curr_id = self.card.id
		else:
			curr_id = self.idCard
		if curr_id != self._raw_data['idCard']:
			changes['idCard'] = curr_id

		return changes

	@asyncio.coroutine
	def state_from_api(self, api_data):
		if 'checkItems' in api_data and self.inflate_children:
			self.check_items = yield from \
				CheckItem.get_many(
					api_data['checkItems'], self.tc, checklist_id=api_data['id'], card_id=api_data['idCard'])
			del api_data['checkItems']
		yield from super(Checklist, self).state_from_api(api_data)

	def __repr__(self):
		if self._refreshed_at:
			return "<Checklist: name='{}', id='{}' ({}))>".format(self.name, self.id, self.card)
		else:
			return "<Checklist: id='{}'>".format(self.id)


class CheckItem(TrelloObject):
	def __init__(self, id_: str, tc: trello_client.TrelloClient, checklist_id: str=None, card_id: str=None, **kwargs) -> None:
		if not checklist_id:
			raise ValueError("Must provide checklist id to CheckItem")
		if not card_id:
			raise ValueError("Must provide card id to CheckItem")
		self.checklist_id = checklist_id
		self.card_id = card_id
		super(CheckItem, self).__init__(id_, tc)

	@classmethod
	@asyncio.coroutine
	def get_data(cls, checkitem_id: str, tc: trello_client.TrelloClient, checklist_id: str=None):
		if not checklist_id:
			raise ValueError("Must provide checklist id to CheckItem")
		return (yield from tc.get_checkitem(checklist_id, checkitem_id))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def delete_from_api(self):
		return (yield from self.tc.delete_checkitem(self.id, self.checklist.id))

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.update_checkitem(self.card_id, self.checklist_id, self.id, changes))

	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.pos != self._raw_data['pos']:
			changes['pos'] = self.pos
		if self.state != self._raw_data['state']:
			changes['state'] = self.state

		return changes

	@property
	def complete(self):
		if hasattr(self, 'state'):
			if self.state == 'complete' or self.state == 'true':
				return True
			elif self.state == 'incomplete' or self.state == 'false':
				return False
			else:
				return self.state
		else:
			return None

	@complete.setter
	def complete(self, value):
		if value == 'incomplete' or value == 'false' or value is False:
			self.state = False
		else:
			self.state = True

	def __repr__(self):
		if self._refreshed_at:
			return "<CheckItem: name='{}' id='{}'>".format(self.name, self.id)
		else:
			return "<CheckItem: id='{}'".format(self.id)


class Label(TrelloObject):
	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_label(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def delete_from_api(self):
		return (yield from self.tc.delete_label())

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.update_label(self.id, changes))

	@classmethod
	@asyncio.coroutine
	def get_labels(self, board_id: str, tc: trello_client.TrelloClient) -> 'Label':
		labels_data = yield from tc.get_labels(board_id)
		labels = TrelloObjectCollection()
		for label_data in labels_data:
			label = Label(label_data['id'], tc)
			yield from label.state_from_api(label_data)
			obj_cache.set(label)
			labels.append(label)
		return labels

	@asyncio.coroutine
	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.color != self._raw_data['color']:
			changes['color'] = self.color

		return changes

	def __repr__(self):
		if self._refreshed_at:
			return "<Label: color='{}' name='{}' id='{}'>".format(self.color, self.name, self.id)
		else:
			return "<Label: id='{}'>".format(self.id)


# field handlers
@asyncio.coroutine
def handle_prefs(prefs: dict, tc: trello_client.TrelloClient) -> BoardPrefs:
	try:
		ret = BoardPrefs(prefs)
	except ValueError:
		# TODO: handle organization prefs
		return prefs

# TODO: 'memberships', 'invitations', 'idMembers', 'idList'
api_fields_mapping = (
	('idOrganization', 'organization', Organization.get),
	('idBoard', 'board', Board.get),
	('idBoards', 'boards', Board.get_many),
	('idLabels', 'labels', Label.get_many),
	('prefs', 'prefs', handle_prefs),
	('labels', 'labels', Label.get_many),
	('idChecklist', 'checklist', Checklist.get),
	('idChecklists', 'checklists', Checklist.get_many),
	('idCard', 'card', Card.get),
	('idList', 'list', Lists.get)
)


@asyncio.coroutine
def _api_field_to_obj_field(key: str, value: Any, tc: trello_client.TrelloClient) -> Tuple[str, Any]:
	"""

	:param key: the key from the Trello API
	:param value: the value from the Trello API
	:param tc: our TrelloClient
	:raise ValueError:
	"""

	# handle empty values
	if value is None:
		return key, value

	found = False
	for api_field_name, obj_field_name, api_to_obj_map in api_fields_mapping:
		if api_field_name == key:
			found = True
			break

	if not found:
		# handle some generic cases
		if 'date' in key and value:
			# parse date fields into datetime objects
			parsed = None
			try:
				parsed = parser.parse(value)
			except ValueError:
				pass
			if parsed:
				return key, parsed

		# This is our fall-through case.  We have no way to process this key/value mapping
		# so just use them as-is
		return key, value

	if callable(api_to_obj_map):
		return obj_field_name, (yield from api_to_obj_map(value, tc))

	# We have a mapping for this key, but we don't know how to handle the specified mapper
	raise ValueError(
		"Do not know how to map '{}' to '{}' with '{}'".format(api_field_name, obj_field_name, api_to_obj_map))
