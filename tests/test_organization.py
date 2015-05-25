from unittest.mock import patch
from rosetrellis.models import Organization

from tests import async_test, get_mock_coro
from tests.test_base import TestRoseTrellisBase

@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestOrganization(TestRoseTrellisBase):
	@async_test
	def test_get_data(self):
		get_org_ret_val = 'get org ret val'
		self.tc.get_organization = get_mock_coro(get_org_ret_val)

		an_id = 'an id'
		data = yield from Organization._get_data(an_id, self.tc)

		self.tc.get_organization.assert_called_with(an_id, fields="all")
		self.assertCountEqual(data, get_org_ret_val)

	@async_test
	def test_get_all(self):
		all_orgs = yield from Organization.get_all(self.tc)

	@async_test
	def test_delete_from_api(self):
		self.tc.delete_organization = get_mock_coro('what')

		an_id = 'an id'
		org = yield from Organization.get({'name': 'an organization', 'id': an_id}, self.tc)

		yield from org._delete_from_api()

		self.tc.delete_organization.assert_called_with(an_id)

	@async_test
	def test_changes_to_api(self):
		update_org_ret_val = 'updated ret val'
		self.tc.update_organization = get_mock_coro(update_org_ret_val)

		an_id = 'an id'
		org = yield from Organization.get({'name': 'an organization', 'id': an_id}, self.tc)

		changes = "bleh"
		updated_data = yield from org._changes_to_api(changes)
		self.assertEqual(updated_data, update_org_ret_val)

		self.tc.update_organization.assert_called_with(an_id, changes)

	@async_test
	def test_get_api_update_from_state(self):
		an_id = 'an id'
		org = yield from Organization.get({'name': 'an organization', 'id': an_id}, self.tc)

		self.assertEqual({}, org._get_api_update_from_state())

		changes = {'name': 'new name'}
		org.name = changes['name']

		self.assertEqual(org._get_api_update_from_state(), changes)

		changes['displayName'] = 'new display name'
		org.displayName = changes['displayName']
		self.assertEqual(org._get_api_update_from_state(), changes)

		changes['desc'] = 'new desc'
		org.desc = changes['desc']
		self.assertEqual(org._get_api_update_from_state(), changes)

		changes['website'] = 'new website'
		org.website = changes['website']
		self.assertEqual(org._get_api_update_from_state(), changes)

	@async_test
	def test_get_api_create_from_state_missing_required_fields(self):
		an_id = 'an id'
		org = yield from Organization.get({'id': an_id}, self.tc)

		with self.assertRaises(ValueError):
			org._get_api_create_from_state()

	@async_test
	def test_get_api_create_from_state(self):
		an_id = 'an id'
		org_data = {'name': 'an organization',
		            'displayName': 'the name to display',
		            'desc': 'a description',
		            'website': 'the awesome org website',
		            'id': an_id}

		org = yield from Organization.get(org_data, self.tc)

		create_data = org._get_api_create_from_state()
		expected_data = org_data.copy()
		del expected_data['id']

		self.assertEqual(expected_data, create_data)
