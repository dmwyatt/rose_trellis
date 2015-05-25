import asyncio
from rosetrellis import trello_client as trello_client
from rosetrellis.models import TrelloObject


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
		raise NotImplementedError

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
