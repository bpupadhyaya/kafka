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
# see kafka.server.KafkaConfig for additional details and defaults

from setuptools import find_packages, setup

setup(name="kafkatest",
      version="0.8.3-SNAPSHOT",
      description="Apache Kafka System Tests",
      author="Apache Kafka",
      platforms=["any"], 
      license="apache2.0",
      packages=find_packages(),
      requires=["ducktape(==0.3.0)"]
      )
