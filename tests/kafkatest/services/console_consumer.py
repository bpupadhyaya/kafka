# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ducktape.services.background_thread import BackgroundThreadService
from ducktape.utils.util import wait_until

import os
import subprocess


def is_int(msg):
    """Default method used to check whether text pulled from console consumer is a message.

    return int or None
    """
    try:
        return int(msg)
    except:
        return None

"""
0.8.2.1 ConsoleConsumer options

The console consumer is a tool that reads data from Kafka and outputs it to standard output.
Option                                  Description
------                                  -----------
--blacklist <blacklist>                 Blacklist of topics to exclude from
                                          consumption.
--consumer.config <config file>         Consumer config properties file.
--csv-reporter-enabled                  If set, the CSV metrics reporter will
                                          be enabled
--delete-consumer-offsets               If specified, the consumer path in
                                          zookeeper is deleted when starting up
--formatter <class>                     The name of a class to use for
                                          formatting kafka messages for
                                          display. (default: kafka.tools.
                                          DefaultMessageFormatter)
--from-beginning                        If the consumer does not already have
                                          an established offset to consume
                                          from, start with the earliest
                                          message present in the log rather
                                          than the latest message.
--max-messages <Integer: num_messages>  The maximum number of messages to
                                          consume before exiting. If not set,
                                          consumption is continual.
--metrics-dir <metrics dictory>         If csv-reporter-enable is set, and
                                          this parameter isset, the csv
                                          metrics will be outputed here
--property <prop>
--skip-message-on-error                 If there is an error when processing a
                                          message, skip it instead of halt.
--topic <topic>                         The topic id to consume on.
--whitelist <whitelist>                 Whitelist of topics to include for
                                          consumption.
--zookeeper <urls>                      REQUIRED: The connection string for
                                          the zookeeper connection in the form
                                          host:port. Multiple URLS can be
                                          given to allow fail-over.
"""


class ConsoleConsumer(BackgroundThreadService):
    # Root directory for persistent output
    PERSISTENT_ROOT = "/mnt/console_consumer"
    STDOUT_CAPTURE = os.path.join(PERSISTENT_ROOT, "console_consumer.stdout")
    STDERR_CAPTURE = os.path.join(PERSISTENT_ROOT, "console_consumer.stderr")
    LOG_DIR = os.path.join(PERSISTENT_ROOT, "logs")
    LOG_FILE = os.path.join(LOG_DIR, "console_consumer.log")
    LOG4J_CONFIG = os.path.join(PERSISTENT_ROOT, "tools-log4j.properties")
    CONFIG_FILE = os.path.join(PERSISTENT_ROOT, "console_consumer.properties")

    logs = {
        "consumer_stdout": {
            "path": STDOUT_CAPTURE,
            "collect_default": False},
        "consumer_stderr": {
            "path": STDERR_CAPTURE,
            "collect_default": False},
        "consumer_log": {
            "path": LOG_FILE,
            "collect_default": True}
        }

    def __init__(self, context, num_nodes, kafka, topic, message_validator=None, from_beginning=True, consumer_timeout_ms=None):
        """
        Args:
            context:                    standard context
            num_nodes:                  number of nodes to use (this should be 1)
            kafka:                      kafka service
            topic:                      consume from this topic
            message_validator:          function which returns message or None
            from_beginning:             consume from beginning if True, else from the end
            consumer_timeout_ms:        corresponds to consumer.timeout.ms. consumer process ends if time between
                                        successively consumed messages exceeds this timeout. Setting this and
                                        waiting for the consumer to stop is a pretty good way to consume all messages
                                        in a topic.
        """
        super(ConsoleConsumer, self).__init__(context, num_nodes)
        self.kafka = kafka
        self.args = {
            'topic': topic,
        }

        self.consumer_timeout_ms = consumer_timeout_ms

        self.from_beginning = from_beginning
        self.message_validator = message_validator
        self.messages_consumed = {idx: [] for idx in range(1, num_nodes + 1)}

    @property
    def start_cmd(self):
        args = self.args.copy()
        args['zk_connect'] = self.kafka.zk.connect_setting()
        args['stdout'] = ConsoleConsumer.STDOUT_CAPTURE
        args['stderr'] = ConsoleConsumer.STDERR_CAPTURE
        args['config_file'] = ConsoleConsumer.CONFIG_FILE

        cmd = "export LOG_DIR=%s;" % ConsoleConsumer.LOG_DIR
        cmd += " export KAFKA_LOG4J_OPTS=\"-Dlog4j.configuration=file:%s\";" % ConsoleConsumer.LOG4J_CONFIG
        cmd += " /opt/kafka/bin/kafka-console-consumer.sh --topic %(topic)s --zookeeper %(zk_connect)s" \
            " --consumer.config %(config_file)s" % args

        if self.from_beginning:
            cmd += " --from-beginning"

        cmd += " 2>> %(stderr)s | tee -a %(stdout)s &" % args
        return cmd

    def pids(self, node):
        try:
            cmd = "ps ax | grep -i console_consumer | grep java | grep -v grep | awk '{print $1}'"
            pid_arr = [pid for pid in node.account.ssh_capture(cmd, allow_fail=True, callback=int)]
            return pid_arr
        except (subprocess.CalledProcessError, ValueError) as e:
            return []

    def alive(self, node):
        return len(self.pids(node)) > 0

    def _worker(self, idx, node):
        node.account.ssh("mkdir -p %s" % ConsoleConsumer.PERSISTENT_ROOT, allow_fail=False)

        # Create and upload config file
        if self.consumer_timeout_ms is not None:
            prop_file = self.render('console_consumer.properties', consumer_timeout_ms=self.consumer_timeout_ms)
        else:
            prop_file = self.render('console_consumer.properties')

        self.logger.info("console_consumer.properties:")
        self.logger.info(prop_file)
        node.account.create_file(ConsoleConsumer.CONFIG_FILE, prop_file)

        # Create and upload log properties
        log_config = self.render('tools_log4j.properties', log_file=ConsoleConsumer.LOG_FILE)
        node.account.create_file(ConsoleConsumer.LOG4J_CONFIG, log_config)

        # Run and capture output
        cmd = self.start_cmd
        self.logger.debug("Console consumer %d command: %s", idx, cmd)
        for line in node.account.ssh_capture(cmd, allow_fail=False):
            msg = line.strip()
            if self.message_validator is not None:
                msg = self.message_validator(msg)
            if msg is not None:
                self.logger.debug("consumed a message: " + str(msg))
                self.messages_consumed[idx].append(msg)

    def start_node(self, node):
        super(ConsoleConsumer, self).start_node(node)

    def stop_node(self, node):
        node.account.kill_process("java", allow_fail=True)
        wait_until(lambda: not self.alive(node), timeout_sec=10, backoff_sec=.2,
                   err_msg="Timed out waiting for consumer to stop.")

    def clean_node(self, node):
        if self.alive(node):
            self.logger.warn("%s %s was still alive at cleanup time. Killing forcefully..." %
                             (self.__class__.__name__, node.account))
        node.account.kill_process("java", clean_shutdown=False, allow_fail=True)
        node.account.ssh("rm -rf %s" % ConsoleConsumer.PERSISTENT_ROOT, allow_fail=False)

