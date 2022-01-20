# Copyright (c) "Neo4j"
# Neo4j Sweden AB [http://neo4j.com]
#
# This file is part of Neo4j.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from .._async_compat.util import AsyncUtil
from ..addressing import Address
from ..api import READ_ACCESS
from ..conf import (
    Config,
    PoolConfig,
    SessionConfig,
    WorkspaceConfig,
)
from ..meta import experimental


class AsyncGraphDatabase:
    """Accessor for :class:`neo4j.Driver` construction.
    """

    @classmethod
    @AsyncUtil.experimental_async(
        "neo4j async is in experimental phase. It might be removed or changed "
        "at any time (including patch releases)."
    )
    def driver(cls, uri, *, auth=None, **config):
        """Create a driver.

        :param uri: the connection URI for the driver, see :ref:`async-uri-ref` for available URIs.
        :param auth: the authentication details, see :ref:`auth-ref` for available authentication details.
        :param config: driver configuration key-word arguments, see :ref:`async-driver-configuration-ref` for available key-word arguments.

        :rtype: AsyncNeo4jDriver or AsyncBoltDriver
        """

        from ..api import (
            DRIVER_BOLT,
            DRIVER_NEO4j,
            parse_neo4j_uri,
            parse_routing_context,
            SECURITY_TYPE_NOT_SECURE,
            SECURITY_TYPE_SECURE,
            SECURITY_TYPE_SELF_SIGNED_CERTIFICATE,
            URI_SCHEME_BOLT,
            URI_SCHEME_BOLT_SECURE,
            URI_SCHEME_BOLT_SELF_SIGNED_CERTIFICATE,
            URI_SCHEME_NEO4J,
            URI_SCHEME_NEO4J_SECURE,
            URI_SCHEME_NEO4J_SELF_SIGNED_CERTIFICATE,
        )

        driver_type, security_type, parsed = parse_neo4j_uri(uri)

        if security_type in [SECURITY_TYPE_SELF_SIGNED_CERTIFICATE, SECURITY_TYPE_SECURE] and ("encrypted" in config.keys() or "trusted_certificates" in config.keys()):
            from neo4j.exceptions import ConfigurationError
            raise ConfigurationError("The config settings 'encrypted' and 'trust' can only be used with the URI schemes {!r}. Use the other URI schemes {!r} for setting encryption settings.".format(
                [
                    URI_SCHEME_BOLT,
                    URI_SCHEME_NEO4J,
                ],
                [
                    URI_SCHEME_BOLT_SELF_SIGNED_CERTIFICATE,
                    URI_SCHEME_BOLT_SECURE,
                    URI_SCHEME_NEO4J_SELF_SIGNED_CERTIFICATE,
                    URI_SCHEME_NEO4J_SECURE,
                ]
            ))

        if security_type == SECURITY_TYPE_SECURE:
            config["encrypted"] = True
        elif security_type == SECURITY_TYPE_SELF_SIGNED_CERTIFICATE:
            config["encrypted"] = True
            config["trusted_certificates"] = []

        if driver_type == DRIVER_BOLT:
            if parse_routing_context(parsed.query):
                raise ValueError(
                    'Routing parameters are not supported with scheme "bolt". '
                    'Given URI "{}".'.format(uri)
                )
            return cls.bolt_driver(parsed.netloc, auth=auth, **config)
        elif driver_type == DRIVER_NEO4j:
            routing_context = parse_routing_context(parsed.query)
            return cls.neo4j_driver(parsed.netloc, auth=auth, routing_context=routing_context, **config)

    @classmethod
    def bolt_driver(cls, target, *, auth=None, **config):
        """ Create a driver for direct Bolt server access that uses
        socket I/O and thread-based concurrency.
        """
        from .._exceptions import (
            BoltHandshakeError,
            BoltSecurityError,
        )

        try:
            return AsyncBoltDriver.open(target, auth=auth, **config)
        except (BoltHandshakeError, BoltSecurityError) as error:
            from neo4j.exceptions import ServiceUnavailable
            raise ServiceUnavailable(str(error)) from error

    @classmethod
    def neo4j_driver(cls, *targets, auth=None, routing_context=None, **config):
        """ Create a driver for routing-capable Neo4j service access
        that uses socket I/O and thread-based concurrency.
        """
        from neo4j._exceptions import (
            BoltHandshakeError,
            BoltSecurityError,
        )

        try:
            return AsyncNeo4jDriver.open(*targets, auth=auth, routing_context=routing_context, **config)
        except (BoltHandshakeError, BoltSecurityError) as error:
            from neo4j.exceptions import ServiceUnavailable
            raise ServiceUnavailable(str(error)) from error


class _Direct:

    default_host = "localhost"
    default_port = 7687

    default_target = ":"

    def __init__(self, address):
        self._address = address

    @property
    def address(self):
        return self._address

    @classmethod
    def parse_target(cls, target):
        """ Parse a target string to produce an address.
        """
        if not target:
            target = cls.default_target
        address = Address.parse(target, default_host=cls.default_host,
                                default_port=cls.default_port)
        return address


class _Routing:

    default_host = "localhost"
    default_port = 7687

    default_targets = ": :17601 :17687"

    def __init__(self, initial_addresses):
        self._initial_addresses = initial_addresses

    @property
    def initial_addresses(self):
        return self._initial_addresses

    @classmethod
    def parse_targets(cls, *targets):
        """ Parse a sequence of target strings to produce an address
        list.
        """
        targets = " ".join(targets)
        if not targets:
            targets = cls.default_targets
        addresses = Address.parse_list(targets, default_host=cls.default_host, default_port=cls.default_port)
        return addresses


class AsyncDriver:
    """ Base class for all types of :class:`neo4j.AsyncDriver`, instances of
    which are used as the primary access point to Neo4j.
    """

    #: Connection pool
    _pool = None

    def __init__(self, pool):
        assert pool is not None
        self._pool = pool

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    def __del__(self):
        if not AsyncUtil.is_async_code:
            self.close()

    @property
    def encrypted(self):
        return bool(self._pool.pool_config.encrypted)

    def session(self, **config):
        """Create a session, see :ref:`async-session-construction-ref`

        :param config: session configuration key-word arguments,
            see :ref:`async-session-configuration-ref` for available key-word
            arguments.

        :returns: new :class:`neo4j.AsyncSession` object
        """
        raise NotImplementedError

    async def close(self):
        """ Shut down, closing any open connections in the pool.
        """
        await self._pool.close()

    @experimental("The configuration may change in the future.")
    async def verify_connectivity(self, **config):
        """ This verifies if the driver can connect to a remote server or a cluster
        by establishing a network connection with the remote and possibly exchanging
        a few data before closing the connection. It throws exception if fails to connect.

        Use the exception to further understand the cause of the connectivity problem.

        Note: Even if this method throws an exception, the driver still need to be closed via close() to free up all resources.
        """
        raise NotImplementedError

    @experimental("Feature support query, based on Bolt Protocol Version and Neo4j Server Version will change in the future.")
    async def supports_multi_db(self):
        """ Check if the server or cluster supports multi-databases.

        :return: Returns true if the server or cluster the driver connects to supports multi-databases, otherwise false.
        :rtype: bool
        """
        async with self.session() as session:
            await session._connect(READ_ACCESS)
            return session._connection.supports_multiple_databases


class AsyncBoltDriver(_Direct, AsyncDriver):
    """:class:`.AsyncBoltDriver` is instantiated for ``bolt`` URIs and
    addresses a single database machine. This may be a standalone server or
    could be a specific member of a cluster.

    Connections established by a :class:`.AsyncBoltDriver` are always made to
    the exact host and port detailed in the URI.

    This class is not supposed to be instantiated externally. Use
    :meth:`AsyncGraphDatabase.driver` instead.
    """

    @classmethod
    def open(cls, target, *, auth=None, **config):
        """
        :param target:
        :param auth:
        :param config: The values that can be specified are found in :class: `neo4j.PoolConfig` and :class: `neo4j.WorkspaceConfig`

        :return:
        :rtype: :class: `neo4j.BoltDriver`
        """
        from .io import AsyncBoltPool
        address = cls.parse_target(target)
        pool_config, default_workspace_config = Config.consume_chain(config, PoolConfig, WorkspaceConfig)
        pool = AsyncBoltPool.open(address, auth=auth, pool_config=pool_config, workspace_config=default_workspace_config)
        return cls(pool, default_workspace_config)

    def __init__(self, pool, default_workspace_config):
        _Direct.__init__(self, pool.address)
        AsyncDriver.__init__(self, pool)
        self._default_workspace_config = default_workspace_config

    def session(self, **config):
        """
        :param config: The values that can be specified are found in :class: `neo4j.SessionConfig`

        :return:
        :rtype: :class: `neo4j.AsyncSession`
        """
        from .work import AsyncSession
        session_config = SessionConfig(self._default_workspace_config, config)
        SessionConfig.consume(config)  # Consume the config
        return AsyncSession(self._pool, session_config)

    @experimental("The configuration may change in the future.")
    async def verify_connectivity(self, **config):
        server_agent = None
        config["fetch_size"] = -1
        async with self.session(**config) as session:
            result = await session.run("RETURN 1 AS x")
            value = await result.single().value()
            summary = await result.consume()
            server_agent = summary.server.agent
        return server_agent


class AsyncNeo4jDriver(_Routing, AsyncDriver):
    """:class:`.AsyncNeo4jDriver` is instantiated for ``neo4j`` URIs. The
    routing behaviour works in tandem with Neo4j's `Causal Clustering
    <https://neo4j.com/docs/operations-manual/current/clustering/>`_
    feature by directing read and write behaviour to appropriate
    cluster members.

    This class is not supposed to be instantiated externally. Use
    :meth:`AsyncGraphDatabase.driver` instead.
    """

    @classmethod
    def open(cls, *targets, auth=None, routing_context=None, **config):
        from .io import AsyncNeo4jPool
        addresses = cls.parse_targets(*targets)
        pool_config, default_workspace_config = Config.consume_chain(config, PoolConfig, WorkspaceConfig)
        pool = AsyncNeo4jPool.open(*addresses, auth=auth, routing_context=routing_context, pool_config=pool_config, workspace_config=default_workspace_config)
        return cls(pool, default_workspace_config)

    def __init__(self, pool, default_workspace_config):
        _Routing.__init__(self, pool.get_default_database_initial_router_addresses())
        AsyncDriver.__init__(self, pool)
        self._default_workspace_config = default_workspace_config

    def session(self, **config):
        from .work import AsyncSession
        session_config = SessionConfig(self._default_workspace_config, config)
        SessionConfig.consume(config)  # Consume the config
        return AsyncSession(self._pool, session_config)

    @experimental("The configuration may change in the future.")
    async def verify_connectivity(self, **config):
        """
        :raise ServiceUnavailable: raised if the server does not support routing or if routing support is broken.
        """
        # TODO: Improve and update Stub Test Server to be able to test.
        return await self._verify_routing_connectivity()

    async def _verify_routing_connectivity(self):
        from ..exceptions import (
            Neo4jError,
            ServiceUnavailable,
            SessionExpired,
        )

        table = self._pool.get_routing_table_for_default_database()
        routing_info = {}
        for ix in list(table.routers):
            try:
                routing_info[ix] = await self._pool.fetch_routing_info(
                    address=table.routers[0],
                    database=self._default_workspace_config.database,
                    imp_user=self._default_workspace_config.impersonated_user,
                    bookmarks=None,
                    timeout=self._default_workspace_config
                                .connection_acquisition_timeout
                )
            except (ServiceUnavailable, SessionExpired, Neo4jError):
                routing_info[ix] = None
        for key, val in routing_info.items():
            if val is not None:
                return routing_info
        raise ServiceUnavailable("Could not connect to any routing servers.")