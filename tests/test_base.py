import asyncio
from collections import namedtuple
import unittest
from unittest.mock import Mock, patch, call

from rosetrellis.models import TrelloObject, IsCoroutineError, ids_getter
from rosetrellis.trello_client import TrelloClient
from tests import async_test, get_mock_coro

class TestRoseTrellisBase(unittest.TestCase):
	def setUp(self):
		self.tc = Mock(TrelloClient)


class TestTrelloObjectBase(TestRoseTrellisBase):
	def setUp(self):
		super(TestTrelloObjectBase, self).setUp()
		# Make it so we can instantiate the abstract base class TrelloObject
		class ConcretedTrelloObject(TrelloObject):
			API_FIELDS = ['data', 'id']
			API_SINGLE_KEY = 'apiObjId'
			STATE_SINGLE_ATTR = 'obj'
			API_MANY_KEY = 'apiObjIds'
			STATE_MANY_ATTR = 'objs'
			API_NESTED_MANY_KEY = 'nestedApiObjs'
			API_NESTED_SINGLE_KEY = 'nestedApiObj'

		ConcretedTrelloObject.__abstractmethods__ = set()

		self.CTO = ConcretedTrelloObject

@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestTrelloObjectMisc(TestTrelloObjectBase):
	def test_tc_available(self):
		to = self.CTO(self.tc)
		self.assertIs(to.tc, self.tc)

	def test_requires_attrs(self):
		fields = ['API_FIELDS', 'API_SINGLE_KEY', 'STATE_SINGLE_ATTR', 'API_MANY_KEY',
		          'STATE_MANY_ATTR', 'API_NESTED_MANY_KEY', 'API_NESTED_SINGLE_KEY']

		for f in fields:
			val = getattr(self.CTO, f)
			delattr(self.CTO, f)
			with self.assertRaises(ValueError):
				to = self.CTO(self.tc)
			setattr(self.CTO, f, val)

	def test_is_valid_data(self):
		valid, extra, missing = self.CTO.is_valid_data({'data': None, 'id': 'hi'})
		self.assertTrue(valid)
		self.assertEqual(len(extra), 0)
		self.assertEqual(len(missing), 0)

	def test_is_valid_data_missing_api_key(self):
		to = self.CTO(self.tc)
		missing_api_key_data = {'nope': None, 'id': 'whatup'}
		valid, extra, missing = self.CTO.is_valid_data(missing_api_key_data)
		self.assertFalse(valid)
		self.assertEqual(len(extra), 1)
		self.assertEqual(extra[0], 'nope')
		self.assertEqual(len(missing), 1)
		self.assertEqual(missing[0], to.API_FIELDS[0])

@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestTrelloObjectGet(TestTrelloObjectBase):
	@patch('rosetrellis.models.obj_cache')
	@async_test
	def test_get_no_cache_creates_obj(self, obj_cache):
		obj_cache.get.return_value = None
		an_id = 'not a real id'
		self.CTO._get_data = get_mock_coro({'data': None, 'id': 'not a real id'})
		self.CTO._state_from_api = get_mock_coro(None)
		obj = yield from self.CTO.get(an_id, self.tc)

		# tries to get obj from cache
		obj_cache.get.assert_called_with(an_id)

		# builds obj
		self.assertIsInstance(obj, self.CTO)

		# tried to get data from API
		self.CTO._get_data.assert_called_with(an_id, self.tc)

		# cached obj
		obj_cache.set.assert_called_with(obj)

	@patch('rosetrellis.models.obj_cache')
	@async_test
	def test_get_cached_from_id(self, obj_cache):
		some_object = 'some object'
		obj_cache.get.return_value = some_object
		self.CTO._get_data = get_mock_coro({'API_FIELDS': None})
		an_id = 'not a real id'
		obj = yield from self.CTO.get(an_id, self.tc)

		# didn't get data from internet
		self.assertEqual(self.CTO._get_data.call_count, 0)

		# gotten object is object from cache
		self.assertEqual(obj, some_object)

		# yeah, we got it from cache
		obj_cache.get.assert_called_with(an_id)

	@patch('rosetrellis.models.obj_cache')
	@async_test
	def test_get_no_cache_data_creates_obj(self, obj_cache):
		obj_cache.get.return_value = None
		self.CTO._get_data = get_mock_coro({'API_FIELDS': None})
		self.CTO._state_from_api = get_mock_coro(None)
		an_id = 'not a real id'
		data = {'something': 14, 'id': an_id, 'API_FIELDS': None}
		obj = yield from self.CTO.get(data, self.tc)

		# didn't get data from internet
		self.assertEqual(self.CTO._get_data.call_count, 0)

		# create a real obj
		self.assertIsInstance(obj, self.CTO)

		# set data on self
		self.CTO._state_from_api.assert_called_with(data, inflate_children=True)

		# cached new obj
		obj_cache.set.assert_called_with(obj)

	@patch('rosetrellis.models.obj_cache')
	@async_test
	def test_get_cached_and_new_data(self, obj_cache):
		obj_cache.get.return_value = None
		self.CTO._state_from_api = get_mock_coro(None)
		an_id = 'not a real id'
		self.CTO._get_data = get_mock_coro({'data': None, 'id': an_id})

		# create an obj
		obj = yield from self.CTO.get(an_id, self.tc)

		# got data from internet (mocked, obviously)
		self.assertEqual(self.CTO._get_data.call_count, 1)

		# return created object when ask for cached
		obj_cache.get.return_value = obj

		data = {'something': 14, 'id': an_id, 'API_FIELDS': None}
		obj_with_new_data = yield from self.CTO.get(data, self.tc)

		# we actually got our obj
		self.assertEqual(obj, obj_with_new_data)

		# didn't get data from internet (value is same as call a few lines up)
		self.assertEqual(self.CTO._get_data.call_count, 1)

		# create a real obj
		self.assertIsInstance(obj_with_new_data, self.CTO)

		# set data on self
		self.CTO._state_from_api.assert_called_with(data, inflate_children=True)

		# cached new obj
		obj_cache.set.assert_called_with(obj_with_new_data)

	@async_test
	def test_get_many(self):
		self.CTO.get = get_mock_coro('a result')
		ids = ['an id', 'another', 'another']
		many = yield from self.CTO.get_many(ids, self.tc)

		self.assertEqual(self.CTO.get.call_count, len(ids))
		self.assertTrue(all([result == 'a result' for result in many]))

@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestTrelloObjectApiStateComm(TestTrelloObjectBase):
	@patch('rosetrellis.models.obj_cache')
	@async_test
	def test_delete(self, obj_cache):
		obj_cache.get.return_value = None
		an_id = 'not a real id'
		self.CTO._get_data = get_mock_coro({'data': None, 'id': 'not a real id'})
		self.CTO._state_from_api = get_mock_coro(None)
		self.CTO._delete_from_api = get_mock_coro(None)
		obj = yield from self.CTO.get(an_id, self.tc)

		# builds obj
		self.assertIsInstance(obj, self.CTO)

		# set up object state as `_state_from_api` would normally do.
		obj._raw_data = {'one': 1, 'two': 2}
		for k, v in obj._raw_data.items():
			setattr(obj, k, v)

		# delete obj from api
		yield from obj.delete()

		# called _delete_from_api
		obj._delete_from_api.assert_called_with()

		# removed keys from self
		self.assertFalse(hasattr(obj, 'one'))
		self.assertFalse(hasattr(obj, 'two'))

	@patch('rosetrellis.models.obj_cache')
	@async_test
	def test_save_obj_already_on_api(self, obj_cache):
		obj_cache.get.return_value = None
		an_id = 'not a real id'

		# don't hit internet, just return this stuff
		self.CTO._get_data = get_mock_coro({'data': None, 'id': an_id})

		# make up some changes
		some_changes = 'yeah, changes'
		self.CTO._get_api_update_from_state = Mock()
		self.CTO._get_api_update_from_state.return_value = some_changes

		# don't send changes to internet, pretend to
		new_data = 'new data here'
		self.CTO._changes_to_api = get_mock_coro(new_data)

		# don't bother setting state from api
		self.CTO._state_from_api = get_mock_coro(None)

		# mock the 'create' method so we can make sure it doesn't get called
		self.CTO._create = get_mock_coro(None)

		# get an obj
		obj = yield from self.CTO.get(an_id, self.tc, inflate_children=False)

		# built obj
		self.assertIsInstance(obj, self.CTO)

		# should have an id since we're pretending this is an obj
		# that already exists on the Trello API
		self.assertIsNotNone(getattr(obj, 'id', None))

		yield from obj.save()

		# test that we don't try to create since we already exist
		self.assertEqual(self.CTO._create.call_count, 0)

		# test that we got changes
		self.CTO._get_api_update_from_state.assert_called_with()

		# test that we send changes to api
		self.CTO._changes_to_api.assert_called_with(some_changes)

		# test that we set the data we get back from api on self
		self.CTO._state_from_api.assert_called_with(new_data)

	@async_test
	def test_save_obj_not_on_api_yet(self):
		# make up some changes
		some_changes = 'yeah, changes'
		self.CTO._get_api_update_from_state = Mock()
		self.CTO._get_api_update_from_state.return_value = some_changes

		# don't send changes to internet, pretend to
		new_changes_data = 'new changes data here'
		self.CTO._changes_to_api = get_mock_coro(new_changes_data)

		# don't bother setting state from api
		self.CTO._state_from_api = get_mock_coro(None)

		# mock the 'create' method so we can make sure it gets called
		an_id = 'an id'

		@asyncio.coroutine
		def create_mock(self):
			self.id = an_id

		self.CTO.create = create_mock

		# make a new obj
		obj = self.CTO(self.tc)

		# save it
		yield from obj.save()

		# ensure mocks mocked the mocking mocks
		self.CTO._get_api_update_from_state.assert_called_with()
		self.CTO._changes_to_api.assert_called_with(some_changes)

		# test that we called `create`.  Our mock create method sets self.id...
		self.assertEqual(obj.id, an_id)

		# set state from our changes call
		self.CTO._state_from_api.assert_called_with(new_changes_data)

	@async_test
	def test_refresh(self):
		some_new_data = 'some new data'
		self.CTO._get_data = get_mock_coro(some_new_data)
		self.CTO._state_from_api = get_mock_coro(None)
		obj = self.CTO(self.tc)
		obj.id = 'an_id'

		yield from obj.refresh()

		self.CTO._get_data.assert_called_with(obj.id, self.tc)
		self.CTO._state_from_api.assert_called_with(some_new_data, inflate_children=True)

@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestTrelloObjectStateSetting(TestTrelloObjectBase):
	@async_test
	def test_state_from_api_not_inflate_children(self):
		obj = self.CTO(self.tc)

		yield from obj._state_from_api({'data': 1, 'more_data': 2}, inflate_children=False)

		self.assertTrue(hasattr(obj, 'data') and obj.data == 1)
		self.assertTrue(hasattr(obj, 'more_data') and obj.more_data == 2)

	@async_test
	def test_state_from_api_inflate_children_no_async_transformers(self):
		self.CTO._get_transformer_for_api_key = Mock()
		a_state_name = 'a_state_name'
		self.CTO._get_transformer_for_api_key.return_value = Mock(state_name=a_state_name)

		self.CTO._run_transformer_func = Mock()

		transformed_value = '09asduf'
		self.CTO._run_transformer_func.return_value = transformed_value

		obj = self.CTO(self.tc)
		some_data = 'some data'
		an_id = 'an id'
		yield from obj._state_from_api({'data': some_data, 'id': an_id}, inflate_children=True)

		# we ran transformer func for each api key
		calls = [call(some_data, self.CTO._get_transformer_for_api_key.return_value.api_transformer),
		         call(an_id, self.CTO._get_transformer_for_api_key.return_value.api_transformer)]
		self.CTO._run_transformer_func.assert_has_calls(calls, any_order=True)

		self.assertEqual(getattr(obj, a_state_name, None), transformed_value)

	@async_test
	def test_state_from_api_async_transformers(self):
		self.CTO._get_transformer_for_api_key = Mock()
		coroutine_transformer_return_value = 'bleh'
		api_transformer = get_mock_coro(coroutine_transformer_return_value)
		api_transformer._is_coroutine = True

		self.CTO._inflator = get_mock_coro(None)

		a_state_name = 'a_state_name'
		state_transformer = Mock(api_transformer=api_transformer, state_name=a_state_name)
		self.CTO._get_transformer_for_api_key.return_value = state_transformer

		obj = self.CTO(self.tc)
		some_data = 'some data'
		an_id = 'an id'
		yield from obj._state_from_api({'data': some_data, 'id': an_id}, inflate_children=True)

		# self.assertEqual(getattr(obj, a_state_name, None), coroutine_transformer_return_value)

		calls = [
			call(a_state_name, an_id, api_transformer),
			call(a_state_name, some_data, api_transformer)
		]

		self.CTO._inflator.assert_has_calls(calls, any_order=True)

@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestTrelloObjectTransformerMethods(TestTrelloObjectBase):
	def test_run_transformer_func_with_valid_str(self):
		def test_func(self, value):
			return value.capitalize()

		self.CTO._test_func = test_func
		obj = self.CTO(self.tc)

		val = 'a value'
		result = obj._run_transformer_func(val, '_test_func')
		self.assertEqual(result, val.capitalize())

	def test_run_transformer_func_with_invalid_str(self):
		obj = self.CTO(self.tc)

		val = 'a value'
		with self.assertRaises(ValueError):
			result = obj._run_transformer_func(val, '_test_func')

	def test_run_transformer_func_with_coro(self):
		@asyncio.coroutine
		def test_func(self, value):
			return value.capitalize()

		self.CTO._test_func = test_func
		obj = self.CTO(self.tc)

		val = 'a value'
		with self.assertRaises(IsCoroutineError):
			result = obj._run_transformer_func(val, '_test_func')

	def test_run_transformer_func_with_no_func(self):
		obj = self.CTO(self.tc)

		val = 'a value'
		self.assertEqual(obj._run_transformer_func(val, None), val)

	def test_get_transformer_for_api_key_no_transformer(self):
		obj = self.CTO(self.tc)
		self.assertIsNone(obj._get_transformer_for_api_key('not a key'))

	def test_get_transformer_for_api_key_standard_transformer(self):
		obj = self.CTO(self.tc)
		st = obj._get_transformer_for_api_key('data')
		self.assertEqual(st.api_name, 'data')

	def test_get_transformer_for_api_key_overriden_transformer(self):
		T = namedtuple('T', ['api_name', 'overrider'])

		def get_additional_transformers(self):
			return (T('data', overrider=True),)

		self.CTO._get_additional_transformers = get_additional_transformers

		obj = self.CTO(self.tc)
		st = obj._get_transformer_for_api_key('data')
		self.assertIsInstance(st, T)
		self.assertTrue(st.overrider)

	def test_get_transformer_for_state_attr_no_transformer(self):
		obj = self.CTO(self.tc)
		self.assertIsNone(obj._get_transformer_for_state_attr('nope'))

	def test_get_transformer_for_state_attr_standard_transformer(self):
		obj = self.CTO(self.tc)
		st = obj._get_transformer_for_state_attr('data')
		self.assertEqual(st.api_name, 'data')

	def test_get_transformer_for_state_attr_overriden_transformer(self):
		T = namedtuple('T', ['state_name', 'overrider'])

		def get_additional_transformers(self):
			return (T('data', overrider=True),)

		self.CTO._get_additional_transformers = get_additional_transformers

		obj = self.CTO(self.tc)
		st = obj._get_transformer_for_state_attr('data')
		self.assertIsInstance(st, T)
		self.assertTrue(st.overrider)

	def test_make_transformers(self):
		class CTOSubclass(self.CTO):
			API_FIELDS = ['id', 'data', 'another_field']

		field_names = CTOSubclass.API_FIELDS + ['yet_another_field']
		transformers = CTOSubclass._make_transformers(field_names)

		self.assertEqual(len(transformers), len(field_names))
		transformer_names = [t.api_name for t in transformers]
		self.assertTrue(all([fn in transformer_names for fn in field_names]))

	def test_get_state_name_from_api_key(self):
		# when given the API_SINGLE_KEY,
		# tells us the corresponding STATE_SINGLE_ATTR
		self.assertEqual(self.CTO.STATE_SINGLE_ATTR, self.CTO._get_state_name_from_api_key(self.CTO.API_SINGLE_KEY))

		# when given the API_MANY_KEY,
		# tells us the corresponding STATE_MANY_ATTR
		self.assertEqual(self.CTO.STATE_MANY_ATTR, self.CTO._get_state_name_from_api_key(self.CTO.API_MANY_KEY))

		# when given something other than API_SINGLE_KEY or API_MANY_KEY,
		# gives us None
		self.assertIsNone(self.CTO._get_state_name_from_api_key('what'))

	def test_get_relation_transformer_for_api_key(self):
		self.CTO._get_transformer_for_single = Mock()
		single_ret_value = 'return value'
		self.CTO._get_transformer_for_single.return_value = single_ret_value

		self.CTO._get_transformer_for_many = Mock()
		many_ret_value = 'many ret value'
		self.CTO._get_transformer_for_many.return_value = many_ret_value

		# when given API_SINGLE_KEY or API_NESTED_SINGLE_KEY,
		# gives us the transformer from _get_transformer_for_single
		self.assertEqual(
			single_ret_value,
			self.CTO._get_relation_transformer_for_api_key(self.CTO.API_SINGLE_KEY)
		)
		self.assertEqual(
			single_ret_value,
			self.CTO._get_relation_transformer_for_api_key(self.CTO.API_NESTED_SINGLE_KEY)
		)

		# when given API_MANY_KEY or API_NESTED_MANY_KEY,
		# gives us the transformer from _get_transformer_for_many
		self.assertEqual(
			many_ret_value,
			self.CTO._get_relation_transformer_for_api_key(self.CTO.API_MANY_KEY)
		)
		self.assertEqual(
			many_ret_value,
			self.CTO._get_relation_transformer_for_api_key(self.CTO.API_NESTED_MANY_KEY)
		)

	def test_get_api_many_keys(self):
		self.assertEqual(
			[self.CTO.API_MANY_KEY, self.CTO.API_NESTED_MANY_KEY],
			self.CTO._get_api_many_keys()
		)

	def test_get_api_single_keys(self):
		self.assertEqual(
			[self.CTO.API_SINGLE_KEY, self.CTO.API_NESTED_SINGLE_KEY],
			self.CTO._get_api_single_keys()
		)

	def test_get_api_keys(self):
		self.assertEqual(
			[self.CTO.API_MANY_KEY, self.CTO.API_NESTED_MANY_KEY, self.CTO.API_SINGLE_KEY,
			 self.CTO.API_NESTED_SINGLE_KEY],
			self.CTO._get_api_keys()
		)

	def test_get_transformer_for_single(self):
		st = self.CTO._get_transformer_for_single(False)

		self.assertEqual(st.api_name, self.CTO.API_SINGLE_KEY)
		self.assertEqual(st.state_name, self.CTO.STATE_SINGLE_ATTR)
		self.assertEqual(st.api_transformer, self.CTO.get)
		self.assertIsNone(st.state_transformer)

		st = self.CTO._get_transformer_for_single(True)

		self.assertEqual(st.api_name, self.CTO.API_NESTED_SINGLE_KEY)

	def test_get_transformer_for_many(self):
		st = self.CTO._get_transformer_for_many(False)

		self.assertEqual(st.api_name, self.CTO.API_MANY_KEY)
		self.assertEqual(st.state_name, self.CTO.STATE_MANY_ATTR)
		self.assertEqual(st.api_transformer, self.CTO.get_many)
		self.assertEqual(st.state_transformer, ids_getter)

		st = self.CTO._get_transformer_for_many(True)

		self.assertEqual(st.api_name, self.CTO.API_NESTED_MANY_KEY)

	def test_get_additional_transformers_defaults_to_empty(self):
		obj = self.CTO(self.tc)
		self.assertEqual(len(obj._get_additional_transformers()), 0)

	def test_stripped_dict_from_fields(self):
		obj = self.CTO(self.tc)

		fields = obj._stripped_dict_from_fields(['tc', 'nope'])
		self.assertEqual(fields['tc'], self.tc)
		self.assertEqual(len(fields), 1)

	@async_test
	def test_changes_from_raw_data(self):
		create_data = {'data': 'some data', 'id': 'the_id'}
		obj = yield from self.CTO.get(create_data, self.tc)
		self.assertEqual(obj.data, create_data['data'])
		self.assertEqual(obj.id, create_data['id'])

		obj.data = 'some other data'

		changes = obj._changes_from_raw_data((('data', 'data'), ('id', 'id')))
		self.assertEqual(changes, {'data': 'some other data'})

		# add an alternative name to _raw_data so that method will not reject the name
		obj._raw_data['some_other_name'] = None

		changes = obj._changes_from_raw_data((('data', 'some_other_name'), ('id', 'id')))
		self.assertEqual(changes, {'some_other_name': 'some other data'})
