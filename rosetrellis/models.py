"""
Contains models for the various objects we get from Trello.
"""
import abc
import asyncio
import logging
import time
import itertools

from dateutil import parser
from typing import Any, List, Union

import rosetrellis.base.obj_cache as obj_cache
import rosetrellis.trello_client as trello_client
from rosetrellis.util import Synchronizer


logger = logging.getLogger(__name__)


def get_class_for_data(data: dict):
	for subclass in TrelloObject.__subclasses__():
		if subclass.is_valid_data(data):
			return subclass


@asyncio.coroutine
def get_obj_instance_for_data(data: dict, tc: trello_client.TrelloClient, inflate_children=True):
	klass = get_class_for_data(data)
	if not klass:
		raise ValueError("Do not know how to handle provided data.")
	logger.debug("Using class '{}' to inflate data".format(klass.__name__))
	return (yield from klass.get(data, tc, inflate_children=inflate_children))


def get_obj_instance_for_data_s(data: dict, tc: trello_client.TrelloClient, inflate_children=True):
	return asyncio.get_event_loop().run_until_complete(
		get_obj_instance_for_data(data, tc, inflate_children=inflate_children)
	)


class TrelloObjectCollection(list, Synchronizer):
	"""
	A list-like object that represents collections of objects inheriting from
	:class:`TrelloObject`.

	Because this is a subclass of :class:`Synchronizer`, every explicitly
	declared coroutine method, has a corresponding synchronous method with the
	same name followed by the suffix ``_s``. For example, the method
	:meth:`~.TrelloObjectCollection.save` has a partner
	synchronous method :meth:`~.TrelloObjectCollection.save_s` that is
	generated at runtime by :class:`Synchronizer`.
	"""

	@asyncio.coroutine
	def save(self):
		"""Save all objects in this list."""
		save_coros = [obj.save() for obj in self]
		yield from asyncio.gather(*save_coros)

	@asyncio.coroutine
	def inflate(self):
		inflate_coros = [obj.inflate() for obj in self]
		yield from asyncio.gather(*inflate_coros)


class TrelloObject(Synchronizer, metaclass=abc.ABCMeta):
	"""
	The base class for all Trello objects.

	Because this is a subclass of :class:`Synchronizer`, every explicitly
	declared coroutine method, has a corresponding synchronous method with the
	same name followed by the suffix ``_s``.

	For example, the method	:meth:`~rosetrellis.models.TrelloObject.save` has
	a partner synchronous method :meth:`~rosetrellis.models.TrelloObject.save_s`
	that is generated at runtime by :class:`Synchronizer`.
	"""

	API_FIELDS = ()
	"""A simple list of all fields this object should receive from the api"""

	INFLATORS = {}
	""" A description of how to build all the related objects
		See other classes like :class:`~.Card` to see some examples
	"""

	def __init__(self, id_: str, tc: trello_client.TrelloClient, *args, **kwargs) -> None:
		"""
		:param id_: A full 24-character Trello object id or the shortLink you see
			in Trello urls.
		:param tc: An instance of :class:`.TrelloClient` for us to use for Trello
			API communication.
		:param inflate_children: If set to ``False``, we won't automatically
			inflate related objects, like the :class:`.Board` related to a
			:class:`.Card`.  You will have to just rely on the ``idBoard``
			attribute in that case.
		"""
		em = "Subclasses of TrelloObject must provide the {} attribute"
		if not self.API_FIELDS:
			raise ValueError(em.format('API_FIELDS'))

		self.tc = tc
		self.id = id_
		self._refreshed_at = 0
		self.opts = kwargs

		# Create inflator definitions
		# used by self.state_from_api to convert object references to actual objects
		self.BOARD_INFLATE = {'dest_field': 'board', 'inflator': Board.get}
		self.BOARDS_INFLATE = {'dest_field': 'boards', 'inflator': Board.get_many}
		self.CARD_INFLATE = {'dest_field': 'card', 'inflator': Card.get}
		self.CHECKLISTS_INFLATE = {'dest_field': 'checklists', 'inflator': Checklist.get_many}
		self.LABELS_INFLATE = {'dest_field': 'labels', 'inflator': Label.get_many}
		self.LIST_INFLATE = {'dest_field': 'list', 'inflator': Lists.get}
		self.ORGANIZATION_INFLATE = {'dest_field': 'organization', 'inflator': Organization.get}
		self.BOARD_PREFS = {'dest_field': 'prefs', 'inflator': handle_prefs}

	@classmethod
	@asyncio.coroutine
	def get(cls, data_or_id: Union[str, dict],
	        tc: trello_client.TrelloClient,
	        inflate_children=True,
	        **kwargs):
		"""
		A coroutine.

		Gets and creates TrelloObjects.

		If provided with a string ID, we attempt to get the object from our
		object cache. If that fails we build a new object out of data from
		provided TrelloClient.

		If provided with a mapping of key-value pairs, we build an object out
		of that data.

		:param data_or_id:  Either an object id, where the id is from Trello, or a
			dict of key-value pairs as returned from the Trello API.

		:param tc:  Instance of :class:`~.TrelloClient`.

		:param inflate_children: If set to ``False``, we won't automatically
			inflate related objects, like the :class:`.Board` related  to
			a :class:`.Card`.  You will have to just rely on the
			``idBoard`` attribute in that case.

		:raises TypeError: if you don't provide a string or a dict for `data_or_id`.
		:raises ValueError: if you don't provide a dict with an 'id' key.

		:rtype: :class:`~.TrelloObject`
		:returns: One of the classes implementing ``TrelloObject``.  For example,
			:class:`.Card` or :class:`.Organization`.
		"""

		if isinstance(data_or_id, str):
			id_ = data_or_id
			data = None
		elif isinstance(data_or_id, dict):
			id_ = data_or_id['id']
			data = data_or_id
		elif 'id' not in data_or_id:
			print(data_or_id)
			raise ValueError("Must provide a mapping with an 'id' key.")
		else:
			raise TypeError("Must provide either a str id or a dict of object data")

		obj = obj_cache.get(id_)

		if obj is None and not data:
			logger.debug("No cached object and no provided data, requesting data from TrelloClient.")
			resp = yield from cls.get_data(id_, tc, **kwargs)
			obj = cls(resp['id'], tc, inflate_children=inflate_children, **kwargs)
			obj_cache.set(obj)
			yield from obj.state_from_api(resp, inflate_children=inflate_children)

		elif obj is None and data:
			logger.debug("No cached object.  Building object from provided data.")
			obj = cls(data['id'], tc, inflate_children=inflate_children, **kwargs)
			obj_cache.set(obj)
			yield from obj.state_from_api(data, inflate_children=inflate_children)

		elif obj and data:
			logger.debug("Found cached object.  Updating with provided data.")
			yield from obj.state_from_api(data, inflate_children=inflate_children)

		return obj

	@classmethod
	@asyncio.coroutine
	def get_many(cls, datas_or_ids: List[Union[str, dict]], tc: trello_client.TrelloClient,
	             inflate_children=True, **kwargs) -> TrelloObjectCollection:
		"""
		A coroutine.

		Asynchronously call :meth:`~.get` for each item in ``datas_or_ids``

		:param datas_or_ids: A list of ids (and/or actual already-retrieved data)
			to create objects out of.

		:param tc:  Used to communicate with Trello API.

		:param inflate_children: If set to ``False``, we won't automatically
			inflate related objects, like the :class:`.Board` related  to
			a :class:`.Card`.  You will have to just rely on the
			``idBoard`` attribute in that case.

		:returns: A list of objects.

		See Also:
			:meth:`~.get`
			:meth:`~.get_all`
		"""
		getters = [cls.get(doi, tc, inflate_children=inflate_children, **kwargs) for doi in datas_or_ids]

		results = yield from asyncio.gather(*getters)
		return TrelloObjectCollection(results)

	@asyncio.coroutine
	def delete(self):
		"""
		A coroutine.

		Deletes instance from Trello API and removes all data from self."""

		# TODO: We have other attributes we need to delete.  For example, we change 'idBoard' to a board instance on self.board.
		response = self.delete_from_api(self.id)
		obj_cache.remove(self.id)
		for k, v in self._raw_data:
			delattr(self, k)

	@asyncio.coroutine
	def save(self) -> None:
		"""
		A coroutine.

		Saves changes to Trello api"""

		changes = self.get_api_from_state()
		if changes:
			new_data = yield from self.changes_to_api(changes)
			yield from self.state_from_api(new_data)

	@asyncio.coroutine
	def refresh(self, inflate_children=True):
		"""
		A coroutine.

		Refreshes data from Trello.
		"""
		data = yield from self.get_data(self.id, self.tc)
		yield from self.state_from_api(data, inflate_children=inflate_children)

	@asyncio.coroutine
	def state_from_api(self, api_data: dict, inflate_children: bool=True):
		"""
		Takes a dict, ``api_data``, and creates the state of this object using
		the information contained within.

		:param api_data: The data from the API.
		:param inflate_children: If set to ``False``, we won't automatically
			inflate related objects, like the :class:`.Board` related  to
			a :class:`.Card`.  You will have to just rely on the
			``idBoard`` attribute in that case.
		"""
		self._raw_data = api_data
		inflators = []
		for k, v in api_data.items():
			if inflate_children and k in self.INFLATORS:
				inflator_attr = self.INFLATORS[k]
				inflator_definition = getattr(self, inflator_attr, None)
				if not inflator_definition:
					raise ValueError('"{}" is an invalid inflator'.format(inflator_attr))

				dest_field = inflator_definition['dest_field']
				inflator = inflator_definition['inflator']
				inflators.append(self._inflator(dest_field, v, inflator))

			if 'date' in k and v:
				# parse date fields into datetime objects
				parsed = None
				try:
					v = parser.parse(v)
				except ValueError:
					pass

			setattr(self, k, v)

		if inflators:
			yield from asyncio.wait(inflators)

		self._refreshed_at = time.time()

	@asyncio.coroutine
	def _inflator(self, dest_field, orig_value, inflator):
		new_value = yield from inflator(orig_value, self.tc)
		setattr(self, dest_field, new_value)

	@classmethod
	@abc.abstractmethod
	def get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs) -> dict:
		"""
		Abstract classmethod that retrieves data from Trello for the provided id.

		Implementers return a dict of data used to inflate the object.

		:param id_: The id of the object to retrieve.
		:param tc: An instance of :class:`rosetrellis.trello_client.TrelloClient`.
		:returns: A dict of data for the object.
		"""

	@classmethod
	@abc.abstractmethod
	def get_all(cls, tc: trello_client.TrelloClient, *args, **kwargs) -> TrelloObjectCollection:
		"""
		Abstract classmthod that retrieves *all* instances of this object.

		Implementers return a :class:`TrelloObjectCollection`.

		:param tc: An instance of :class:`rosetrellis.trello_client.TrelloClient`.
		"""

	@abc.abstractmethod
	def delete_from_api(self) -> None:
		"""
		Abstract method that deletes this instance from the Trello API.
		"""

	@abc.abstractmethod
	def changes_to_api(self, changes: dict) -> dict:
		"""
		Abstract method that sends data to Trello API.

		:param changes: The changes to send.  The key:value pairs should match up with
			the Trello API fields as detailed in the Trello API docs.
		:returns: The new data to set on self.
		"""

	@abc.abstractmethod
	def get_api_from_state(self) -> dict:
		"""
		Abstract method that returns how current state differs from original data.

		:returns: The data that has changed since we built the object.
		"""

	@classmethod
	def is_valid_data(self, data: dict) -> bool:
		"""
		Determines whether the provided dict is valid data for this object.

		:returns: A bool indicating whether this is valid dat.
		"""

		return all([key in self.API_FIELDS for key in data])

	def is_inflated(self) -> bool:
		return all([hasattr(self, f) for f in self.get_inflated_fields()])

	def get_inflated_fields(self) -> List[str]:
		fields = []
		for k, v in self.INFLATORS.items():
			inflator_definition = getattr(self, v, None)
			if not inflator_definition:
				continue
			fields.append(inflator_definition['dest_field'])
		return fields


class Organization(TrelloObject):
	"""
	Trello organization representation.
	"""
	API_FIELDS = ('billableMemberCount', 'desc', 'descData', 'displayName', 'id',
	              'idBoards', 'invitations', 'invited', 'logoHash', 'memberships',
	              'name', 'powerUps', 'prefs', 'premiumFeatures', 'products', 'url',
	              'website')

	INFLATORS = {
		'idBoards': 'BOARDS_INFLATE'
	}

	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs) -> dict:
		return (yield from tc.get_organization(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def delete_from_api(self):
		yield from self.tc.delete_organization(self.id)

	@asyncio.coroutine
	def changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_organization(self.id, changes))

	def get_api_from_state(self):
		"""
		Return dict of changes between current state and data we were
		instantiated with.

		Special handling for:

		1. Setting self.desc to None.
		2. Validates that self.website was set to an address beginning with
			'http' as required by Trello.
		"""
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
	API_FIELDS = ('closed', 'dateLastActivity', 'dateLastView', 'desc', 'descData',
	              'id', 'idOrganization', 'invitations', 'invited', 'labelNames',
	              'memberships', 'name', 'pinned', 'powerUps', 'prefs', 'shortLink',
	              'shortUrl', 'starred', 'subscribed', 'url')

	INFLATORS = {
		'idOrganization': 'ORGANIZATION_INFLATE',
		'prefs': 'BOARD_PREFS'
	}

	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs):
		return (yield from tc.get_board(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		only_open = kwargs.get('only_open', True)
		boards_data = yield from tc.get_boards(only_open=only_open)
		return (yield from cls.get_many(boards_data, tc, inflate_children=inflate_children))

	@asyncio.coroutine
	def delete_from_api(self):
		"""
		Boards can't be deleted!

		Instead, try archiving by setting self.closed to True and saving.

		:raises NotImplementedError:
		"""
		raise NotImplementedError("Trello does not permit deleting of boards.  Try `Board.close()`")

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		return (yield from self.tc.update_board(self.id, changes))

	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.desc != self._raw_data['desc']:
			changes['desc'] = self.desc
		if self.closed != self._raw_data['closed']:
			changes['closed'] = self.closed
		if self.organization.id != self._raw_data['idOrganization']:
			changes['idOrganization'] = self.organization.id

		changes.update(self.prefs.get_api_from_state())

		return changes

	@asyncio.coroutine
	def get_labels(self):
		return (yield from Label.get_labels(self.id, self.tc))

	@asyncio.coroutine
	def get_lists(self, inflate_children=True) -> TrelloObjectCollection:
		lists_data = yield from self.tc.get_board_lists(self.id)
		return (yield from Lists.get_many(lists_data, self.tc, inflate_children=True))

	@asyncio.coroutine
	def get_cards(self, inflate_children=True) -> TrelloObjectCollection:
		cards_data = yield from self.tc.get_board_cards(self.id)
		return (yield from Card.get_many(cards_data, self.tc, inflate_children=inflate_children))

	@asyncio.coroutine
	def get_checklists(self, inflate_children=True) -> TrelloObjectCollection:
		checklists_data = yield from self.tc.get_board_checklists(self.id)
		return (yield from Checklist.get_many(checklists_data, self.tc, inflate_children=inflate_children))

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
	API_FIELDS = ('closed', 'id', 'idBoard', 'name', 'pos', 'subscribed')

	INFLATORS = {
		'idBoard': 'BOARD_INFLATE'
	}

	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs):
		return (yield from tc.get_list(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs) -> TrelloObjectCollection:
		boards = yield from Board.get_all(tc, inflate_children=inflate_children)
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
	"""
	Trello card representation.
	"""
	API_FIELDS = ('badges', 'checkItemStates', 'closed', 'dateLastActivity', 'desc',
	              'descData', 'due', 'email', 'id', 'idAttachmentCover', 'idBoard',
	              'idChecklists', 'idLabels', 'idList', 'idMembers', 'idMembersVoted',
	              'idShort', 'labels', 'manualCoverAttachment', 'name', 'pos',
	              'shortLink', 'shortUrl', 'subscribed', 'url')
	INFLATORS = {
		'idBoard': 'BOARD_INFLATE',
		'idChecklists': 'CHECKLISTS_INFLATE',
		'idLabels': 'LABELS_INFLATE',
		'idList': 'LIST_INFLATE',
		# 'idMembers': {'dest_field': 'members', 'inflator': Member.get_many}
	}

	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient) -> dict:
		return (yield from tc.get_card(card_id=id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		boards = yield from Board.get_all(tc, inflate_children=inflate_children)
		card_getters = [board.get_cards(inflate_children=inflate_children) for board in boards]
		return TrelloObjectCollection(
			itertools.chain.from_iterable(
				(yield from asyncio.gather(*card_getters))
			)
		)

	@asyncio.coroutine
	def delete_from_api(self):
		yield from self.tc.delete_card(self.id)

	@asyncio.coroutine
	def changes_to_api(self, changes: dict):
		updated_api_data = yield from self.tc.update_card(self.id, changes)
		return updated_api_data

	def get_api_from_state(self):
		changes = {}
		if self.name != self._raw_data['name']:
			changes['name'] = self.name
		if self.desc != self._raw_data['desc']:
			changes['desc'] = self.desc
		if self.closed != self._raw_data['closed']:
			changes['closed'] = self.closed

		if 'labels' in self._raw_data and self.label_colors:
			raw_data_colors = sorted([label['color'] for label in self._raw_data['labels']])
			state_colors = sorted(self.label_colors)

			if raw_data_colors != state_colors:
				changes['labels'] = ','.join(state_colors)

		return changes

	@asyncio.coroutine
	def state_from_api(self, api_data, inflate_children=True):
		"""sub"""

		if 'labels' in api_data and inflate_children:
			# Redundant info caused by using 'all' filter when getting
			# card data
			try:
				del api_data['idLabels']
			except KeyError:
				pass

		yield from super(Card, self).state_from_api(api_data, inflate_children=inflate_children)

	@property
	def label_colors(self) -> List:
		"""
		List of the label colors for this card.
		"""
		return [l.color for l in self.labels]

	def __repr__(self):
		if self._refreshed_at:
			return "<Card: name='{}', id='{}'>".format(self.name, self.id)
		else:
			return "<Card: id='{}'>".format(self.id)


class Checklist(TrelloObject):
	API_FIELDS = ('cards', 'checkItems', 'id', 'idBoard', 'idCard', 'name', 'pos')

	INFLATORS = {
		'idBoard': 'BOARD_INFLATE',
		'idCard': 'CARD_INFLATE'
	}

	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_checklist(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		boards = yield from Board.get_all(tc)
		getters = [board.get_checklists() for board in boards]

		checklists = list(itertools.chain.from_iterable((yield from asyncio.gather(*getters))))

		return checklists

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

	@property
	def incomplete_items(self):
		if not hasattr(self, 'check_items'):
			return None
		return [ci for ci in self.check_items if not ci.complete]

	@property
	def complete_items(self):
		if not hasattr(self, 'check_items'):
			return None
		return [ci for ci in self.check_items if ci.complete]

	@asyncio.coroutine
	def state_from_api(self, api_data, inflate_children=True):
		if 'checkItems' in api_data and inflate_children:
			self.check_items = yield from CheckItem.get_many(
				api_data['checkItems'],
				self.tc,
				checklist_id=api_data['id'],
				card_id=api_data['idCard']
			)

			del api_data['checkItems']

		yield from super(Checklist, self).state_from_api(api_data, inflate_children=inflate_children)

	def __repr__(self):
		if self._refreshed_at:
			return "<Checklist: name='{}', id='{}' ({}))>".format(self.name, self.id, self.card)
		else:
			return "<Checklist: id='{}'>".format(self.id)


class CheckItem(TrelloObject):
	API_FIELDS = ('id', 'name', 'nameData', 'pos', 'state')

	def __init__(self, id_: str, tc: trello_client.TrelloClient, checklist_id: str=None, card_id: str=None,
	             **kwargs) -> None:
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
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
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
	API_FIELDS = ('color', 'id', 'idBoard', 'name', 'uses')

	INFLATORS = {
		'idBoard': 'BOARD_INFLATE'
	}

	@classmethod
	@asyncio.coroutine
	def get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_label(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
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
