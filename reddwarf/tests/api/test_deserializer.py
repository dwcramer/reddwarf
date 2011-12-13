#    Copyright 2011 OpenStack LLC
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import unittest

from nose.tools import raises

from reddwarf import exception
from reddwarf.api import deserializer


class DeserializationTest(unittest.TestCase):
    """Test all the xml deserialization"""

    def setUp(self):
        self.deser = deserializer.ConfigXMLDeserializer()

    def test_config_create_single(self):
        xml = '<configs> \
               <config key="reddwarf_imageref" value="5" description="reddwarf image"/> \
               </configs>'
        output = self.deser.create(xml)
        expected = {'body':
                     {'configs':
                       [{'key': 'reddwarf_imageref', 'value': '5', 'description': 'reddwarf image'}]
                    }}
        self.assertEqual(json.dumps(expected), json.dumps(output))

    def test_config_create_multiple(self):
        xml = '<configs> \
               <config key="reddwarf_imageref" value="5" description="reddwarf image"/> \
               <config key="test2" value="test2val" description="test2desc"/> \
               </configs>'
        output = self.deser.create(xml)
        expected = {'body':
                     {'configs':
                       [{'key': 'reddwarf_imageref', 'value': '5', 'description': 'reddwarf image'},
                        {'key': 'test2', 'value': 'test2val', 'description': 'test2desc'}]
                    }}
        self.assertEqual(json.dumps(expected), json.dumps(output))

    @raises(exception.BadRequest)
    def test_config_create_empty_body(self):
        self.deser.create("")

    @raises(exception.BadRequest)
    def test_config_create_invalid_xml(self):
        self.deser.create("<configs><config></configs>")

    def test_config_create_no_configs(self):
        xml = '<config key="reddwarf_imageref" value="5" description="reddwarf image"/>'
        output = self.deser.create(xml)
        self.assertEqual(None, output)

    def test_config_update(self):
        xml = '<config key="reddwarf_imageref" value="5" description="reddwarf image"/>'
        output = self.deser.update(xml)
        expected = {'body':
                     {'config':
                       {'key': 'reddwarf_imageref', 'value': '5', 'description': 'reddwarf image'}
                    }}
        self.assertEqual(json.dumps(expected), json.dumps(output))

    @raises(exception.BadRequest)
    def test_config_update_empty_body(self):
        self.deser.create("")

    @raises(exception.BadRequest)
    def test_config_update_invalid_xml(self):
        self.deser.create("<configs><config></configs>")

    @raises(exception.BadRequest)
    def test_create_database_fails_quote_in_name(self):
        self.deser.create("""
            <Databases xmlns="http://docs.openstack.org/database/api/v1.0">
                <Database name="db"name" character_set="utf8" collate="utf8_general_ci"/>
            </Databases>
            """)

    @raises(exception.BadRequest)
    def test_create_instance_fails_quote_in_name(self):
        self.deser.create("""
            <instance xmlns="http://docs.openstack.org/database/api/v1.0"
                name="bad"name" flavorRef="https://ord.databases.api.rackspacecloud.com/v1.0/1234/flavors/1">
                <databases />
                <volume size="2" />
            </instance>
            """)

    @raises(exception.BadRequest)
    def test_create_user_fails_quote_in_name(self):
        self.deser.create("""
            <users xmlns="http://docs.openstack.org/database/api/v1.0">
                <user name="user"name" password="badUsername" database="databaseA"/>
            </users>
            """)

    @raises(exception.BadRequest)
    def test_create_user_fails_quote_in_password(self):
        self.deser.create("""
            <users xmlns="http://docs.openstack.org/database/api/v1.0">
                <user name="badPassword" password="pass"word" database="databaseA"/>
            </users>
            """)
