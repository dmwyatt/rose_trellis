######################
Installation and Setup
######################

*******
Install
*******
Use pip.

*****
Setup
*****

Trello Authentication
=====================
You need two things to authenticate with Trello as detailed `at this place <https://trello.com/docs/gettingstarted/index.html>`_.

Application key
---------------
Make sure you're logged into Trello and then go to https://trello.com/1/appKey/generate.

Token
-----
Documented in detail `here <https://trello.com/docs/gettingstarted/index.html#getting-a-token-from-a-user>`_,
where it explains how to get time-limited tokens along with read/write restrictions.

For an all-powerful token that never expires, visit an url like:

::

   https://trello.com/1/authorize?key=substitutewithyourapplicationkey&name=My+Application&expiration=never&response_type=token&scope=read,write

.. _envvar:

Environment variables
---------------------
If you set the environment variables TRELLO_API_KEY and/or TRELLO_API_TOKEN,
:class:`rosetrellis.trello_client.TrelloClient` will use them and you won't
have to pass them in when you instantiate it.
