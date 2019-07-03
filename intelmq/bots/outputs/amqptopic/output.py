# -*- coding: utf-8 -*-

from intelmq.lib.bot import Bot

try:
    import pika
except ImportError:
    pika = None


class AMQPTopicBot(Bot):
    connection = None

    def init(self):
        if pika is None:
            raise ValueError("Could not import library 'pika'. Please install it.")

        self.connection = None
        self.channel = None

        pika_version = tuple(int(x) for x in pika.__version__.split('.'))
        self.kwargs = {}
        if pika_version < (0, 11):
            self.kwargs['heartbeat_interval'] = self.parameters.connection_heartbeat
        else:
            self.kwargs['heartbeat'] = self.parameters.connection_heartbeat
        if pika_version < (1, ):
            # https://groups.google.com/forum/#!topic/pika-python/gz7lZtPRq4Q
            self.publish_raises_nack = False
        else:
            self.publish_raises_nack = True

        self.keep_raw_field = self.parameters.keep_raw_field
        self.delivery_mode = self.parameters.delivery_mode
        self.content_type = self.parameters.content_type
        self.exchange = self.parameters.exchange_name
        self.require_confirmation = self.parameters.require_confirmation
        self.durable = self.parameters.exchange_durable
        self.exchange_type = self.parameters.exchange_type
        self.connection_host = self.parameters.connection_host
        self.connection_port = self.parameters.connection_port
        self.connection_vhost = self.parameters.connection_vhost
        self.credentials = pika.PlainCredentials(self.parameters.username, self.parameters.password)
        self.connection_parameters = pika.ConnectionParameters(
            host=self.connection_host,
            port=self.connection_port,
            virtual_host=self.connection_vhost,
            connection_attempts=self.parameters.connection_attempts,
            credentials=self.credentials,
            **self.kwargs)
        self.routing_key = self.parameters.routing_key
        self.properties = pika.BasicProperties(
            content_type=self.content_type, delivery_mode=self.delivery_mode)

        self.connect_server()

        self.hierarchical = getattr(self.parameters, "message_hierarchical", False)
        self.with_type = getattr(self.parameters, "message_with_type", False)
        self.jsondict_as_string = getattr(self.parameters, "message_jsondict_as_string", False)

    def connect_server(self):
        self.logger.info('AMQP Connecting to %s:%s/%s.',
                         self.connection_host, self.connection_port, self.connection_vhost)
        try:
            self.connection = pika.BlockingConnection(self.connection_parameters)
        except pika.exceptions.ProbableAuthenticationError:
            self.logger.error('AMQP authentication failed!')
            raise
        except pika.exceptions.ProbableAccessDeniedError:
            self.logger.error('AMQP authentication for virtual host failed!')
            raise
        except pika.exceptions.AMQPConnectionError:
            self.logger.error('AMQP connection failed!')
            raise
        else:
            self.logger.info('AMQP connection successful.')
            self.channel = self.connection.channel()
            if self.exchange:  # do not declare default exchange (#1295)
                try:
                    self.channel.exchange_declare(exchange=self.exchange, type=self.exchange_type,
                                                  durable=self.durable)
                except pika.exceptions.ChannelClosed:
                    self.logger.error('Access to exchange refused.')
                    raise
            self.channel.confirm_delivery()

    def process(self):
        ''' Stop the Bot if cannot connect to AMQP Server after the defined connection attempts '''

        # self.connection and self.channel can be None
        if getattr(self.connection, 'is_closed', None) or getattr(self.channel, 'is_closed', None):
            self.connect_server()

        event = self.receive_message()

        if not self.keep_raw_field:
            del event['raw']
        body = event.to_json(hierarchical=self.hierarchical,
                             with_type=self.with_type,
                             jsondict_as_string=self.jsondict_as_string).encode(errors='backslashreplace')

        try:
            if not self.channel.basic_publish(exchange=self.exchange,
                                              routing_key=self.routing_key,
                                              # replace unicode characters when encoding (#1296)
                                              body=body,
                                              properties=self.properties,
                                              mandatory=True):
                if self.require_confirmation and not self.publish_raises_nack:
                    raise ValueError('Message sent but not confirmed.')
                elif not self.publish_raises_nack:
                    self.logger.info('Message sent but not confirmed.')
        except (pika.exceptions.ChannelError, pika.exceptions.AMQPChannelError,
                pika.exceptions.NackError):
            self.logger.exception('Error publishing the message.')
        except pika.exceptions.UnroutableError:
            self.logger.exception('The destination queue does not exist, declare it first. See also the README.')
            self.stop()
        else:
            self.acknowledge_message()

    def shutdown(self):
        if self.connection:
            self.connection.close()


BOT = AMQPTopicBot
