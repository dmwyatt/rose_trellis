"""
Contains models for the various objects we get from Trello.
"""
import abc
import asyncio
import logging
import operator
import time
import itertools
import datetime
import re

from dateutil import parser
from typing import Any, List, Union, Sequence, Callable, Tuple, Dict

import rosetrellis.base.obj_cache as obj_cache
import rosetrellis.trello_client as trello_client
from rosetrellis.util import Synchronizer, make_sequence_attrgetter


logger = logging.getLogger(__name__)

id_getter = operator.attrgetter('id')
ids_getter = make_sequence_attrgetter('id')


class IsCoroutineError(Exception):
	pass


class StateTransformer:
	"""
	Describes how to change the value to and from object state to API.

	Used by TrelloObjects to transform API values to TrelloObject values and
	vice-versa.
	"""

	def __init__(self,
	             api_name: str,
	             state_name: str,
	             api_transformer: Union[Callable[Any], str]=None,
	             state_transformer: Union[Callable[Any], str]=None) -> None:
		"""
		There are three possible types of transformer:

		1. You can provide a callable.
		2. You can provide ``None`` for no transformation.
		3. You can provide a string name of a callable on self which is retrieved
			from self similarly to:

		>>> ast = StateTransformer('idBoard', 'board', api_transformer=Card.get, state_transformer=operator.attrgetter('id'))
		>>> call_me = getattr(self, ast.transformer)
		>>> assert callable(call_me)

		This third type of transformer is provided to enable you to use callables that
		are undefined at the time the python interpreter parses the class definition,
		such as methods on self.

		:param api_name: Name used to get value from the API dict.
		:param state_name: Name of the attribute on :class:`.TrelloObject` instances.
		:param api_transformer: Used to transform from API value to state value.
		:param state_transformer: Used to transform from state value to API value.
		"""

		self.api_name = api_name
		self.state_name = state_name
		self.api_transformer = api_transformer
		self.state_transformer = state_transformer

	def __repr__(self):
		return "<StateTransformer: api_name={} state_name={} api_transformer={} state_transformer={}>".format(
			self.api_name, self.state_name, self.api_transformer, self.state_transformer
		)


def get_class_for_data(data: dict):
	for subclass in TrelloObject.__subclasses__():
		if subclass.is_valid_data(data):
			return subclass


def get_class_for_api_key(api_key: str):
	classes = TrelloObject.__subclasses__()
	for subclass in TrelloObject.__subclasses__():
		if api_key in subclass._get_api_keys():
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


def transform_date_from_api(date_str: str) -> datetime.datetime:
	# parse date fields into datetime objects
	try:
		return parser.parse(date_str)
	except ValueError:
		return


def transform_date_from_state(dt: datetime.datetime) -> str:
	dt_str = dt.isoformat()
	dt_str = re.sub("\+00:00$", "Z", dt_str)
	return dt_str


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

	Because this is a subclass of :class:`~util.Synchronizer`, every explicitly
	declared coroutine method, has a corresponding synchronous method with the
	same name followed by the suffix ``_s``.

	For example, the method	:meth:`~rosetrellis.models.TrelloObject.save` has
	a partner synchronous method :meth:`~rosetrellis.models.TrelloObject.save_s`
	that is generated at runtime by :class:`~util.Synchronizer`.

	At a minimum, implementing classes must override or provide the following
	members:

	* :attr:`.API_SINGLE_KEY`
	* :attr:`.STATE_SINGLE_ATTR`
	* :attr:`.API_MANY_KEY`
	* :attr:`.STATE_MANY_ATTR`
	* :attr:`.API_NESTED_MANY_KEY`
	* :attr:`.API_NESTED_SINGLE_KEY`
	* :meth:`.get_all`

	The following are all private abstract methods that should be overriden:

	* :meth:`._get_data`
	* :meth:`._delete_from_api`
	* :meth:`._changes_to_api`
	* :meth:`._create_on_api`
	* :meth:`._get_api_update_from_state`
	* :meth:`._get_api_create_from_state`

	Additionally, the implementing class will likely want to override
	:meth:`._get_additional_transformers`.
	"""

	API_FIELDS = ()  #: A list of all fields we should expect from the API.
	API_SINGLE_KEY = ''  #: The name used on the Trello API to represent a single instance
	STATE_SINGLE_ATTR = ''  #: Name of attribute to use on object instances for a relation to a single object
	API_MANY_KEY = ''  #: The name used on the Trello API to represent multiple instances
	STATE_MANY_ATTR = ''  #: Name of attribute to use on object instances for a relation to multiple objects
	API_NESTED_MANY_KEY = ''  #: Name of key for when Trello nests the JSON for multiple objects in another instance
	API_NESTED_SINGLE_KEY = ''  #: Name of key for when Trello nests the JSON for a single object in another object

	def __init__(self, tc: trello_client.TrelloClient, *args, **kwargs) -> None:
		"""
		:param tc: An instance of :class:`.TrelloClient` for us to use for Trello
			API communication.
		:param kwargs: If creating a new object for Trello, key:value mappings
			for the fields needed to POST a new object.
		"""

		self.API_STATE_TRANSFORMERS = TrelloObject._make_transformers(self.API_FIELDS)
		required_attrs = ['API_FIELDS', 'API_SINGLE_KEY', 'STATE_SINGLE_ATTR',
		                  'API_MANY_KEY', 'STATE_MANY_ATTR', 'API_NESTED_MANY_KEY',
		                  'API_NESTED_SINGLE_KEY']
		em = "Subclasses of TrelloObject must provide the {} attribute(s)"

		# Test that implementors of this class have provided the required attributes.
		fails = []
		for ra in required_attrs:
			fail_value = 'blahblahblah'
			value = getattr(self, ra, fail_value)
			if not value or value == fail_value:
				fails.append(ra)
		if fails:
			raise ValueError(em.format(fails))

		self.tc = tc
		self._refreshed_at = 0
		self.id = kwargs.get('id', None)

	@classmethod
	def is_valid_data(cls, data: dict) -> dict:
		extra_api_keys = []
		missing_api_keys = []
		for k in data:
			if k not in cls.API_FIELDS:
				extra_api_keys.append(k)
		for f in cls.API_FIELDS:
			if f not in data:
				missing_api_keys.append(f)

		return (not (extra_api_keys or missing_api_keys), extra_api_keys, missing_api_keys)

	#####################################
	## API Retrieval methods
	#####################################
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
			resp = yield from cls._get_data(id_, tc, **kwargs)
			is_valid, extra, missing = cls.is_valid_data(resp)
			if not is_valid:
				raise ValueError("Received incorrect API response or {} is misconfigured: \n"
				                 "extra_keys: {} \n"
				                 "missing_keys: {}".format(cls.__name__,
				                                           extra,
				                                           missing))

			obj = cls(tc, id=id_, **kwargs)
			obj_cache.set(obj)
			yield from obj._state_from_api(resp, inflate_children=inflate_children)

		elif obj is None and data:
			logger.debug("No cached object.  Building object from provided data.")
			obj = cls(tc, id=data['id'], **kwargs)
			obj_cache.set(obj)
			yield from obj._state_from_api(data, inflate_children=inflate_children)

		elif obj and data:
			logger.debug("Found cached object.  Updating with provided data.")
			yield from obj._state_from_api(data, inflate_children=inflate_children)

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

	#####################################
	## Instance <-> API management
	#####################################
	@asyncio.coroutine
	def delete(self):
		"""
		A coroutine.

		Deletes instance from Trello API and removes all data from self."""

		# TODO: We have other attributes we need to delete.  For example, we change 'idBoard' to a board instance on self.board.
		response = yield from self._delete_from_api()
		obj_cache.remove(self.id)
		for k, v in self._raw_data.items():
			delattr(self, k)
		delattr(self, '_raw_data')

	def create(self):
		create_data = self._get_api_create_from_state()
		new_data = yield from self._create_on_api(create_data)
		yield from self._state_from_api(new_data)

	@asyncio.coroutine
	def save(self) -> None:
		"""
		A coroutine.

		Saves changes to Trello api"""
		if not self.id:
			# This is a new object, so create it
			yield from self.create()
			assert getattr(self, 'id', None) is not None

		# even if we had to create, not all state
		# can be sent to Trello on object creation
		changes = self._get_api_update_from_state()
		if changes:
			new_data = yield from self._changes_to_api(changes)
			yield from self._state_from_api(new_data)

	@asyncio.coroutine
	def refresh(self, inflate_children=True):
		"""
		A coroutine.

		Refreshes data from Trello.
		"""
		data = yield from self._get_data(self.id, self.tc)
		yield from self._state_from_api(data, inflate_children=inflate_children)

	@asyncio.coroutine
	def _state_from_api(self, api_data: dict, inflate_children: bool=True):
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
		transformations = []
		for k, v in api_data.items():
			if not inflate_children:
				setattr(self, k, v)
				continue

			if k not in self.API_FIELDS:
				raise ValueError("Received field from API that we don't know about.  '{}' is unknown".format(k))
			transformer = self._get_transformer_for_api_key(k)

			# If we don't have a value for this key, then we don't run any transformer
			transformer_func = None if v is None else transformer.api_transformer

			try:
				# We can just run (or get and run) the transformer function...
				result = self._run_transformer_func(v, transformer_func)
				setattr(self, transformer.state_name, result)
			except IsCoroutineError:
				# ... unless it is a coroutine.  We'll run all coroutines later.
				transformations.append(self._inflator(transformer.state_name, v, transformer_func))

		if transformations:
			yield from asyncio.wait(transformations)

		self._refreshed_at = time.time()

	@asyncio.coroutine
	def _inflator(self, dest_field, orig_value, inflator):
		new_value = yield from inflator(orig_value, self.tc)
		setattr(self, dest_field, new_value)

	#####################################
	## Abstract methods
	#####################################
	@classmethod
	@abc.abstractmethod
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs) -> dict:
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
	def _delete_from_api(self) -> None:
		"""
		Abstract method that deletes this instance from the Trello API.
		"""

	@abc.abstractmethod
	def _changes_to_api(self, changes: dict) -> dict:
		"""
		Abstract method that sends data to Trello API.

		:param changes: The changes to send.  The key:value pairs should match up with
			the Trello API fields as detailed in the Trello API docs.
		:returns: The new data to set on self.
		"""

	@abc.abstractmethod
	def _create_on_api(self, data: dict) -> dict:
		"""
		Abstract method that creates object on Trello API.

		:param data:  The data to create the object.
		:return: The new data for our state.
		"""

	@abc.abstractmethod
	def _get_api_update_from_state(self) -> dict:
		"""
		Abstract method that returns how current state differs from original data.

		:returns: The data that has changed since we built the object.
		"""

	@abc.abstractmethod
	def _get_api_create_from_state(self) -> dict:
		"""
		Determines the data to use to create an instance on API from current state.

		:returns: The data that is needed to POST to API.
		"""

	#####################################
	## Transformer methods
	#####################################
	def _run_transformer_func(self, value: Any, tf: Union[Callable[Any], str, None]) -> Any:
		if isinstance(tf, str):
			_tf = getattr(self, tf, None)
			if not _tf or not callable(_tf):
				raise ValueError(
					"Do not know how to get transformer described by: '{}'".format(tf))
			else:
				tf = _tf

		if asyncio.iscoroutinefunction(tf):
			raise IsCoroutineError
		elif tf is None:
			return value
		else:
			return tf(value)

	def _get_transformer_for_api_key(self, api_key: str) -> StateTransformer:
		"""
		Searches our transformers for the one matching the provided api key.

		:param api_key: String name of the api key we're looking to transform.
		:returns: A :class:`.StateTransformer` or None if we can't find one.
		"""
		transformer = None
		for st in self.API_STATE_TRANSFORMERS:
			if st.api_name == api_key:
				transformer = st
				break
		for st in self._get_additional_transformers():
			if st.api_name == api_key:
				transformer = st
				break

		return transformer

	def _get_transformer_for_state_attr(self, attr: str) -> StateTransformer:
		"""
		Searches our transformers for the one matching the provided attribute.

		:param attr: String name of the attribute we're looking to transform.
		:returns: A :class:`.StateTransformer` or None if we can't find one.
		"""

		transformer = None
		for st in self.API_STATE_TRANSFORMERS:
			if st.state_name == attr:
				transformer = st
				break
		for st in self._get_additional_transformers():
			if st.state_name == attr:
				transformer = st
				break
		return transformer

	@classmethod
	def _make_transformers(cls, api_keys: Sequence[str]) -> list:
		"""
		Convenience class method for turning a list of api keys into :attr:`~.StateTransformer`'s
		which use the same api and instance names.

		:param api_keys:
		:return:
		"""
		transformers = []
		for fn in api_keys:
			klass = get_class_for_api_key(fn)
			st = None
			if klass:
				st = klass._get_relation_transformer_for_api_key(fn)
				if st:
					transformers.append(st)

			if not st:
				api_transformer = transform_date_from_api if 'date' in fn else None

				state_transformer = transform_date_from_state if 'date' in fn else None
				transformers.append(
					StateTransformer(api_name=fn,
					                 state_name=fn,
					                 api_transformer=api_transformer,
					                 state_transformer=state_transformer)
				)
		return transformers

	@classmethod
	def _get_state_name_from_api_key(cls, api_key: str) -> str:
		if api_key == cls.API_SINGLE_KEY:
			return cls.STATE_SINGLE_ATTR
		if api_key == cls.API_MANY_KEY:
			return cls.STATE_MANY_ATTR

	@classmethod
	def _get_relation_transformer_for_api_key(cls, api_key: str) -> StateTransformer:
		if api_key in [cls.API_SINGLE_KEY, cls.API_NESTED_SINGLE_KEY]:
			return cls._get_transformer_for_single(api_key == cls.API_NESTED_SINGLE_KEY)
		elif api_key in [cls.API_MANY_KEY, cls.API_NESTED_MANY_KEY]:
			return cls._get_transformer_for_many(api_key == cls.API_NESTED_MANY_KEY)

	@classmethod
	def _get_api_many_keys(cls):
		return [cls.API_MANY_KEY, cls.API_NESTED_MANY_KEY]

	@classmethod
	def _get_api_single_keys(cls):
		return [cls.API_SINGLE_KEY, cls.API_NESTED_SINGLE_KEY]

	@classmethod
	def _get_api_keys(cls):
		return cls._get_api_many_keys() + cls._get_api_single_keys()

	@classmethod
	def _get_transformer_for_single(cls, nested: bool) -> StateTransformer:
		"""
		Provides a StateTransformer that transforms the api representation (normally an id)
		of this type of class into a TrelloObject-subclassing instance.

		:returns: A :class:`.StateTransformer` that transforms an api value into
			this subclass of :class:`.TrelloObject`.
		:raise ValueError: If this subclass isn't configured with :attr:`.API_SINGLE_KEY`
			and :attr:`.STATE_SINGLE_ATTR`.
		"""
		api_key = cls.API_SINGLE_KEY if not nested else cls.API_NESTED_SINGLE_KEY
		return StateTransformer(api_key, cls.STATE_SINGLE_ATTR, api_transformer=cls.get)

	@classmethod
	def _get_transformer_for_many(cls, nested: bool) -> StateTransformer:
		"""
		Provides a StateTransformer that transforms the api representation of a list
		(nromally a list of ids) of this type of class into a TrelloObject-subclassing instance.

		:returns: A :class:`.StateTransformer` that transforms an api value into
			this subclass of :class:`.TrelloObject`.
		:raise ValueError: If this subclass isn't configured with :attr:`.API_MANY_KEY`
			and :attr:`.STATE_MANY_ATTR`.
		"""

		api_key = cls.API_MANY_KEY if not nested else cls.API_NESTED_MANY_KEY
		return StateTransformer(api_key, cls.STATE_MANY_ATTR,
		                        api_transformer=cls.get_many, state_transformer=ids_getter)

	def _get_additional_transformers(self):
		"""
		Provides additional transformers for :attr:`.API_STATE_TRANSFORMERS`.

		Override this method if implementing class needs to provide transformers
		that can't be provided in the class attribute :attr:`.API_STATE_TRANSFORMERS`.

		You might need to do this if the transformer you need to provide isn't defined
		at the time the python interpreter parses the class definition.

		For example, :class:`.Organization` needs the :attr:`.Board.TRANSFORM_ONE`
		transformer, but ``Board`` is not yet defined when the class definition for
		``Organization`` is parsed, so we could override this method like so::

			def get_additional_transformers(self):
				return (Board.TRANSFORM_ONE,)

		:return: A tuple of :class:`.StateTransformer`'s
		"""
		return tuple()

	#####################################
	## Helpers
	#####################################
	def _stripped_dict_from_fields(self, fields: List[str]) -> dict:
		"""
		Returns a dict of the values contained in the attributes specified in
		``fields``.

		If the value does not exist or is None, then we don't create an entry
		for it.

		:param fields:
		:return: A dict mapping fields to values taken from self.
		"""
		create_dict = {}
		for f in fields:
			value = getattr(self, f, None)
			if value:
				create_dict[f] = value

		return create_dict

	def _changes_from_raw_data(self, attr_key_pairs: List[Tuple[str, str]]) -> dict:
		changes = {}
		for attr, key in attr_key_pairs:
			if not hasattr(self, attr) or not key in self._raw_data:
				continue
			state_transformer = self._get_transformer_for_state_attr(attr)
			transformer_func = state_transformer.state_transformer

			state_value = self._run_transformer_func(getattr(self, attr), transformer_func)

			if state_value != self._raw_data[key]:
				changes[key] = state_value

		return changes


class Member(TrelloObject):
	"""
	Trello member representation.
	"""
	API_FIELDS = ('avatarHash', 'avatarSource', 'bio', 'bioData', 'confirmed', 'email',
	              'fullName', 'gravatarHash', 'id', 'idBoards', 'idBoardsPinned',
	              'idOrganizations', 'idPremOrgsAdmin', 'initials', 'loginTypes',
	              'memberType', 'oneTimeMessagesDismissed', 'prefs', 'premiumFeatures',
	              'products', 'status', 'trophies', 'uploadedAvatarHash', 'url', 'username')

	API_SINGLE_KEY = 'idMember'
	STATE_SINGLE_ATTR = 'member'
	API_MANY_KEY = 'idMembers'
	STATE_MANY_ATTR = 'members'
	API_NESTED_MANY_KEY = 'members'
	API_NESTED_SINGLE_KEY = 'member'

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs):
		return (yield from tc.get_member(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		# TODO: Maybe iterate through organizations and get members from memberships
		return (yield from cls.get_many(["me"], tc, inflate_children=inflate_children))

	@classmethod
	@asyncio.coroutine
	def _delete_from_api(self):
		"""
		Members can't be deleted!
		"""
		raise NotImplementedError("Trello does not permit deleting of members.")

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_member(self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict) -> dict:
		raise NotImplementedError("You must create new members at http://trello.com")

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('fullName', 'fullName'),
			('initials', 'initials'),
			('username', 'username'),
			('bio', 'bio'),
			('avatarSource', 'avatarSource'),
		])

		# TODO: Handle prefs/colorBlind and prefs/minutesBetweenSummaries

		return changes

	def _get_api_create_from_state(self) -> dict:
		raise NotImplementedError("You must create new members at http://trello.com")

	def __repr__(self):
		return "<Member: username='{}' fullName='{}'>".format(getattr(self, 'username'),
		                                                      getattr(self, 'fullName'))


class Organization(TrelloObject):
	"""
	Trello organization representation.
	"""
	API_FIELDS = ('billableMemberCount', 'desc', 'descData', 'displayName', 'id',
	              'idBoards', 'invitations', 'invited', 'logoHash', 'memberships',
	              'name', 'powerUps', 'prefs', 'premiumFeatures', 'products', 'url',
	              'website')

	API_SINGLE_KEY = 'idOrganization'
	STATE_SINGLE_ATTR = 'organization'
	API_MANY_KEY = 'idOrganizations'
	STATE_MANY_ATTR = 'organizations'
	API_NESTED_MANY_KEY = 'organizations'
	API_NESTED_SINGLE_KEY = 'organization'

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs) -> dict:
		return (yield from tc.get_organization(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		member = yield from Member.get("me", tc)
		return member.organizations

	@asyncio.coroutine
	def _delete_from_api(self):
		return (yield from self.tc.delete_organization(self.id))

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_organization(self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict) -> dict:
		return (yield from self.tc.create_organization(data))

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('displayName', 'displayName'),
			('desc', 'desc'),
			('website', 'website')
		])

		return changes

	def _get_api_create_from_state(self) -> dict:
		if not getattr(self, 'name', None) or not getattr(self, 'displayName', None):
			raise ValueError("Cannot create an 'Organization' without a name or "
			                 "displayName property on self.")

		return self._stripped_dict_from_fields(['name', 'displayName', 'desc', 'website'])

	def __repr__(self):
		displayName = getattr(self, 'displayName', None)
		if self._refreshed_at:
			return "<Organization: displayName='{}', id='{}')>".format(displayName, self.id)
		else:
			return "<Organization: id='{}'>".format(self.id)


class Board(TrelloObject):
	API_FIELDS = ('closed', 'dateLastActivity', 'dateLastView', 'desc', 'descData',
	              'id', 'idOrganization', 'invitations', 'invited', 'labelNames', 'memberships',
	              'name', 'pinned', 'powerUps', 'prefs', 'shortLink', 'shortUrl',
	              'starred', 'subscribed', 'url')

	API_SINGLE_KEY = 'idBoard'
	STATE_SINGLE_ATTR = 'board'
	API_MANY_KEY = 'idBoards'
	STATE_MANY_ATTR = 'boards'
	API_NESTED_MANY_KEY = 'boards'
	API_NESTED_SINGLE_KEY = 'board'

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs):
		return (yield from tc.get_board(id_, fields="all"))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		only_open = kwargs.get('only_open', True)
		boards_data = yield from tc.get_boards(only_open=only_open)
		return (yield from cls.get_many(boards_data, tc, inflate_children=inflate_children))

	@asyncio.coroutine
	def _delete_from_api(self):
		"""
		Boards can't be deleted!

		Instead, try archiving by setting self.closed to True and saving.

		:raises NotImplementedError: Because it's not possible to delete boards.
		"""
		raise NotImplementedError("Trello does not permit deleting of boards.  Try `Board.close()`")

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_board(self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict) -> dict:
		return (yield from self.tc.create_board(data))

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('desc', 'desc'),
			('closed', 'closed'),
			('organization', 'idOrganization'),
		])

		changes.update(self.prefs.get_api_update_from_state())

		return changes

	def _get_api_create_from_state(self) -> dict:
		if not getattr(self, 'name', None):
			raise ValueError("Must have Board.name to create a Board")

		# TODO: Handle prefs
		return self._stripped_dict_from_fields(['name', 'desc', 'idOrganization', 'powerUps'])

	@asyncio.coroutine
	def get_labels(self):
		return (yield from Label.get_labels(self.id, self.tc))

	@asyncio.coroutine
	def get_lists(self, inflate_children=True) -> TrelloObjectCollection:
		lists_data = yield from self.tc.get_board_lists(self.id)
		return (yield from Lists.get_many(lists_data, self.tc, inflate_children=inflate_children))

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

	API_SINGLE_KEY = 'idList'
	STATE_SINGLE_ATTR = 'list'
	API_MANY_KEY = 'idLists'
	STATE_MANY_ATTR = 'lists'
	API_NESTED_MANY_KEY = 'lists'
	API_NESTED_SINGLE_KEY = 'list'

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs) -> TrelloObjectCollection:
		boards = yield from Board.get_all(tc, inflate_children=inflate_children)
		lists_getters = [b.get_lists() for b in boards]
		lists = list(itertools.chain.from_iterable((yield from asyncio.gather(*lists_getters))))
		return TrelloObjectCollection(lists)

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient, **kwargs):
		return (yield from tc.get_list(id_, fields="all"))

	@asyncio.coroutine
	def _delete_from_api(self):
		raise NotImplementedError("Trello does not permit list deletion.  Try closing the list instead.")

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_list(self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict) -> dict:
		return (yield from self.tc.create_list(data))

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('board', 'idBoard'),
			('pos', 'pos'),
			('subscribed', 'subscribed')
		])

		return changes

	def _get_api_create_from_state(self):
		board_id = getattr(getattr(self, 'board', None), 'id', None)
		if not getattr(self, 'name', None) or not board_id:
			raise ValueError("Cannot create a 'List' without a 'name' and 'board' property.")

		data = self._stripped_dict_from_fields(['name', 'displayName', 'pos'])

		data['idBoard'] = board_id

		return data

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

	API_SINGLE_KEY = 'idCard'
	STATE_SINGLE_ATTR = 'card'
	API_MANY_KEY = 'idCards'
	STATE_MANY_ATTR = 'cards'
	API_NESTED_MANY_KEY = 'cards'
	API_NESTED_SINGLE_KEY = 'card'

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient) -> dict:
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
	def _delete_from_api(self):
		yield from self.tc.delete_card(self.id)

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		updated_api_data = yield from self.tc.update_card(self.id, changes)
		return updated_api_data

	@asyncio.coroutine
	def _create_on_api(self, data: dict):
		return (yield from self.tc.create_card(data))

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('desc', 'desc'),
			('closed', 'closed'),
			('pos', 'pos'),
			('list', 'idList'),
			('board', 'idBoard'),
			('due', 'due'),
			('subscribed', 'subscribed')
		])

		postable_labels = self._postable_labels
		if postable_labels:
			changes['labels'] = postable_labels

		return changes

	def _get_api_create_from_state(self):
		due = getattr(self, 'due', None)
		list_id = getattr(getattr(self, 'list', None), 'id', None)

		if not getattr(self, 'name', None) or not list_id:
			raise ValueError("Cannot create a 'Card' without a 'name' and 'list' property")

		data = self._stripped_dict_from_fields(['name', 'desc', 'pos'])
		postable_labels = self._postable_labels
		if postable_labels:
			data['labels'] = postable_labels

		return data

	@asyncio.coroutine
	def _state_from_api(self, api_data, inflate_children=True):
		"""sub"""

		if 'labels' in api_data and inflate_children:
			# Redundant info caused by using 'all' filter when getting
			# card data
			try:
				del api_data['idLabels']
			except KeyError:
				pass

		yield from super(Card, self)._state_from_api(api_data, inflate_children=inflate_children)

	@property
	def label_colors(self) -> List[str]:
		"""
		List of the label colors for this card.
		"""
		return [l.color for l in self.labels]

	@property
	def _postable_labels(self) -> List[str]:
		if 'labels' in self._raw_data and self.label_colors:
			raw_data_colors = sorted([label['color'] for label in self._raw_data['labels']])
			state_colors = sorted(self.label_colors)

			if raw_data_colors != state_colors:
				return ','.join(state_colors)

	def __repr__(self):
		if self._refreshed_at:
			return "<Card: name='{}', id='{}'>".format(self.name, self.id)
		else:
			return "<Card: id='{}'>".format(self.id)


class Checklist(TrelloObject):
	API_FIELDS = ('cards', 'checkItems', 'id', 'idBoard', 'idCard', 'name', 'pos')

	API_SINGLE_KEY = 'idChecklist'
	STATE_SINGLE_ATTR = 'checklist'
	API_MANY_KEY = 'idChecklists'
	STATE_MANY_ATTR = 'checklists'
	API_NESTED_MANY_KEY = 'checklists'
	API_NESTED_SINGLE_KEY = 'checklist'

	def _get_additional_transformers(self):
		checkitem_transformers = CheckItem._api_transformers(self.id)
		return [StateTransformer(CheckItem.API_NESTED_MANY_KEY,
		                         CheckItem.STATE_MANY_ATTR,
		                         api_transformer=checkitem_transformers['transform_many'],
		                         state_transformer=None)]

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_checklist(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		boards = yield from Board.get_all(tc)
		getters = [board.get_checklists() for board in boards]

		checklists = list(itertools.chain.from_iterable((yield from asyncio.gather(*getters))))

		return checklists

	@asyncio.coroutine
	def _delete_from_api(self):
		return (yield from self.tc.delete_checklist(self.id))

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_checklist(self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict):
		return (yield from self.tc.create_checklist(data))

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('pos', 'pos'),
			('card', 'idCard')
		])

		return changes

	def _get_api_create_from_state(self):
		board_id = getattr(self, 'board', None)
		card_id = getattr(self, 'card', None)
		if not board_id or not card_id:
			raise ValueError("Cannot create a 'Checklist' without a 'board' and 'card' property")

		data = self._stripped_dict_from_fields(['name', 'pos'])

		data['idBoard'] = board_id
		data['idCard'] = card_id

		return data

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

	def __repr__(self):
		if self._refreshed_at:
			return "<Checklist: name='{}', id='{}' ({}))>".format(self.name, self.id, self.card)
		else:
			return "<Checklist: id='{}'>".format(self.id)


class CheckItem(TrelloObject):
	API_FIELDS = ('id', 'name', 'nameData', 'pos', 'state')

	API_SINGLE_KEY = 'idCheckItem'
	STATE_SINGLE_ATTR = 'checkitem'
	API_MANY_KEY = 'idCheckItem'
	STATE_MANY_ATTR = 'checkitems'
	API_NESTED_MANY_KEY = 'checkItems'
	API_NESTED_SINGLE_KEY = 'checkItem'

	def __init__(self, tc: trello_client.TrelloClient, checklist_id: str=None, **kwargs) -> None:
		if not checklist_id:
			raise ValueError("Must provide checklist id to CheckItem")
		self.checklist_id = checklist_id
		super(CheckItem, self).__init__(tc)

	@classmethod
	def _api_transformers(cls, checklist_id: str) -> Dict[str, Callable[dict]]:
		@asyncio.coroutine
		def transform_single(data: Union[str, dict], tc: trello_client.TrelloClient) -> Callable[dict]:
			return cls.get(data, tc, checklist_id=checklist_id)

		@asyncio.coroutine
		def transform_many(datas: List[str, dict], tc: trello_client.TrelloClient) -> Callable[dict]:
			return cls.get_many(datas, tc, checklist_id=checklist_id)

		return {'transform_single': transform_single, 'transform_many': transform_many}

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, checkitem_id: str, tc: trello_client.TrelloClient, checklist_id: str=None):
		if not checklist_id:
			raise ValueError("Must provide checklist id to CheckItem")
		return (yield from tc.get_checkitem(checklist_id, checkitem_id))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def _delete_from_api(self):
		return (yield from self.tc.delete_checkitem(self.id, self.checklist.id))

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_checkitem(self.card_id, self.checklist_id, self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict):
		return (yield from self.tc.create_checkitem(self.checklist_id, data))

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('pos', 'pos'),
			('state', 'state')
		])

		return changes

	def _get_api_create_from_state(self):
		if not getattr(self, 'name', None):
			raise ValueError("Cannot create a 'Checklist' without a 'name' property.")

		data = self._stripped_dict_from_fields(['name', 'pos', 'checked'])

		return data

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

	API_SINGLE_KEY = 'idLabel'
	STATE_SINGLE_ATTR = 'label'
	API_MANY_KEY = 'idLabels'
	STATE_MANY_ATTR = 'labels'
	API_NESTED_MANY_KEY = 'labels'
	API_NESTED_SINGLE_KEY = 'label'

	@classmethod
	@asyncio.coroutine
	def _get_data(cls, id_: str, tc: trello_client.TrelloClient):
		return (yield from tc.get_label(id_))

	@classmethod
	@asyncio.coroutine
	def get_all(cls, tc: trello_client.TrelloClient, *args, inflate_children=True, **kwargs):
		raise NotImplementedError

	@asyncio.coroutine
	def _delete_from_api(self):
		return (yield from self.tc.delete_label())

	@asyncio.coroutine
	def _changes_to_api(self, changes: dict) -> dict:
		return (yield from self.tc.update_label(self.id, changes))

	@asyncio.coroutine
	def _create_on_api(self, data: dict):
		return (yield from self.tc.create_label(self.id, data))

	@classmethod
	@asyncio.coroutine
	def get_labels(self, board_id: str, tc: trello_client.TrelloClient) -> 'Label':
		labels_data = yield from tc.get_labels(board_id)
		labels = TrelloObjectCollection()
		for label_data in labels_data:
			label = Label(label_data['id'], tc)
			yield from label._state_from_api(label_data)
			obj_cache.set(label)
			labels.append(label)
		return labels

	def _get_api_update_from_state(self):
		changes = self._changes_from_raw_data([
			('name', 'name'),
			('color', 'color')
		])

		return changes

	def _get_api_create_from_state(self):
		data = self._stripped_dict_from_fields(['name', 'color'])

		if not getattr(getattr(self, 'board', None), 'id', None):
			raise ValueError("Cannot create a 'Label' without a 'Board' in a 'board' property")

		data['idBoard'] = self.board.id

		return data

	def __repr__(self):
		if self._refreshed_at:
			return "<Label: color='{}' name='{}' id='{}'>".format(self.color, self.name, self.id)
		else:
			return "<Label: id='{}'>".format(self.id)
