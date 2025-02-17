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

from ducktape.services.service import Service

import json
import re
import signal
import time


class KafkaService(Service):

    logs = {
        "kafka_log": {
            "path": "/mnt/kafka.log",
            "collect_default": True},
        "kafka_data": {
            "path": "/mnt/kafka-logs",
            "collect_default": False}
    }

    def __init__(self, context, num_nodes, zk, topics=None):
        """
        :type context
        :type zk: ZookeeperService
        :type topics: dict
        """
        super(KafkaService, self).__init__(context, num_nodes)
        self.zk = zk
        self.topics = topics

    def start(self):
        super(KafkaService, self).start()

        # Create topics if necessary
        if self.topics is not None:
            for topic, topic_cfg in self.topics.items():
                if topic_cfg is None:
                    topic_cfg = {}

                topic_cfg["topic"] = topic
                self.create_topic(topic_cfg)

    def start_node(self, node):
        props_file = self.render('kafka.properties', node=node, broker_id=self.idx(node))
        self.logger.info("kafka.properties:")
        self.logger.info(props_file)
        node.account.create_file("/mnt/kafka.properties", props_file)

        cmd = "/opt/kafka/bin/kafka-server-start.sh /mnt/kafka.properties 1>> /mnt/kafka.log 2>> /mnt/kafka.log & echo $! > /mnt/kafka.pid"
        self.logger.debug("Attempting to start KafkaService on %s with command: %s" % (str(node.account), cmd))
        node.account.ssh(cmd)
        time.sleep(5)
        if len(self.pids(node)) == 0:
            raise Exception("No process ids recorded on node %s" % str(node))

    def pids(self, node):
        """Return process ids associated with running processes on the given node."""
        try:
            return [pid for pid in node.account.ssh_capture("cat /mnt/kafka.pid", callback=int)]
        except:
            return []

    def signal_node(self, node, sig=signal.SIGTERM):
        pids = self.pids(node)
        for pid in pids:
            node.account.signal(pid, sig)

    def signal_leader(self, topic, partition=0, sig=signal.SIGTERM):
        leader = self.leader(topic, partition)
        self.signal_node(leader, sig)

    def stop_node(self, node, clean_shutdown=True):
        pids = self.pids(node)
        sig = signal.SIGTERM if clean_shutdown else signal.SIGKILL

        for pid in pids:
            node.account.signal(pid, sig, allow_fail=False)

        node.account.ssh("rm -f /mnt/kafka.pid", allow_fail=False)

    def clean_node(self, node):
        node.account.kill_process("kafka", clean_shutdown=False, allow_fail=True)
        node.account.ssh("rm -rf /mnt/kafka-logs /mnt/kafka.properties /mnt/kafka.log /mnt/kafka.pid", allow_fail=False)

    def create_topic(self, topic_cfg):
        node = self.nodes[0] # any node is fine here
        self.logger.info("Creating topic %s with settings %s", topic_cfg["topic"], topic_cfg)

        cmd = "/opt/kafka/bin/kafka-topics.sh --zookeeper %(zk_connect)s --create "\
            "--topic %(topic)s --partitions %(partitions)d --replication-factor %(replication)d" % {
                'zk_connect': self.zk.connect_setting(),
                'topic': topic_cfg.get("topic"),
                'partitions': topic_cfg.get('partitions', 1),
                'replication': topic_cfg.get('replication-factor', 1)
            }

        if "configs" in topic_cfg.keys() and topic_cfg["configs"] is not None:
            for config_name, config_value in topic_cfg["configs"].items():
                cmd += " --config %s=%s" % (config_name, str(config_value))

        self.logger.info("Running topic creation command...\n%s" % cmd)
        node.account.ssh(cmd)

        time.sleep(1)
        self.logger.info("Checking to see if topic was properly created...\n%s" % cmd)
        for line in self.describe_topic(topic_cfg["topic"]).split("\n"):
            self.logger.info(line)

    def describe_topic(self, topic):
        node = self.nodes[0]
        cmd = "/opt/kafka/bin/kafka-topics.sh --zookeeper %s --topic %s --describe" % \
              (self.zk.connect_setting(), topic)
        output = ""
        for line in node.account.ssh_capture(cmd):
            output += line
        return output

    def verify_reassign_partitions(self, reassignment):
        """Run the reassign partitions admin tool in "verify" mode
        """
        node = self.nodes[0]
        json_file = "/tmp/" + str(time.time()) + "_reassign.json"

        # reassignment to json
        json_str = json.dumps(reassignment)
        json_str = json.dumps(json_str)

        # create command
        cmd = "echo %s > %s && " % (json_str, json_file)
        cmd += "/opt/kafka/bin/kafka-reassign-partitions.sh "\
                "--zookeeper %(zk_connect)s "\
                "--reassignment-json-file %(reassignment_file)s "\
                "--verify" % {'zk_connect': self.zk.connect_setting(),
                                'reassignment_file': json_file}
        cmd += " && sleep 1 && rm -f %s" % json_file

        # send command
        self.logger.info("Verifying parition reassignment...")
        self.logger.debug(cmd)
        output = ""
        for line in node.account.ssh_capture(cmd):
            output += line

        self.logger.debug(output)

        if re.match(".*is in progress.*", output) is not None:
            return False

        return True

    def execute_reassign_partitions(self, reassignment):
        """Run the reassign partitions admin tool in "verify" mode
        """
        node = self.nodes[0]
        json_file = "/tmp/" + str(time.time()) + "_reassign.json"

        # reassignment to json
        json_str = json.dumps(reassignment)
        json_str = json.dumps(json_str)

        # create command
        cmd = "echo %s > %s && " % (json_str, json_file)
        cmd += "/opt/kafka/bin/kafka-reassign-partitions.sh "\
                "--zookeeper %(zk_connect)s "\
                "--reassignment-json-file %(reassignment_file)s "\
                "--execute" % {'zk_connect': self.zk.connect_setting(),
                                'reassignment_file': json_file}
        cmd += " && sleep 1 && rm -f %s" % json_file

        # send command
        self.logger.info("Executing parition reassignment...")
        self.logger.debug(cmd)
        output = ""
        for line in node.account.ssh_capture(cmd):
            output += line

        self.logger.debug("Verify partition reassignment:")
        self.logger.debug(output)

    def restart_node(self, node, wait_sec=0, clean_shutdown=True):
        """Restart the given node, waiting wait_sec in between stopping and starting up again."""
        self.stop_node(node, clean_shutdown)
        time.sleep(wait_sec)
        self.start_node(node)

    def leader(self, topic, partition=0):
        """ Get the leader replica for the given topic and partition.
        """
        cmd = "/opt/kafka/bin/kafka-run-class.sh kafka.tools.ZooKeeperMainWrapper -server %s " \
              % self.zk.connect_setting()
        cmd += "get /brokers/topics/%s/partitions/%d/state" % (topic, partition)
        self.logger.debug(cmd)

        node = self.nodes[0]
        self.logger.debug("Querying zookeeper to find leader replica for topic %s: \n%s" % (cmd, topic))
        partition_state = None
        for line in node.account.ssh_capture(cmd):
            match = re.match("^({.+})$", line)
            if match is not None:
                partition_state = match.groups()[0]
                break

        if partition_state is None:
            raise Exception("Error finding partition state for topic %s and partition %d." % (topic, partition))

        partition_state = json.loads(partition_state)
        self.logger.info(partition_state)

        leader_idx = int(partition_state["leader"])
        self.logger.info("Leader for topic %s and partition %d is now: %d" % (topic, partition, leader_idx))
        return self.get_node(leader_idx)

    def bootstrap_servers(self):
        return ','.join([node.account.hostname + ":9092" for node in self.nodes])