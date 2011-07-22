import gettext
import os
import json
import re
import sys
import time
import unittest
from tests import util

GROUP="dbaas.guest"
GROUP_START="dbaas.guest.initialize"
GROUP_TEST="dbaas.guest.test"
GROUP_STOP="dbaas.guest.shutdown"


from datetime import datetime
from nose.plugins.skip import SkipTest
from novaclient.exceptions import NotFound
from nova import context
from nova import db
from nova import exception
from nova.api.platform.dbaas.dbcontainers import _dbaas_mapping
from nova.compute import power_state
from reddwarf.db import api as dbapi

from reddwarfclient import Dbaas
from tests.util import test_config
from proboscis.decorators import expect_exception
from proboscis.decorators import time_out
from proboscis import test
from tests.util import check_database
from tests.util import create_dns_entry
from tests.util import process
from tests.util.users import Requirements
from tests.util import string_in_list
from tests.util import TestClient

try:
    import rsdns
except Exception:
    rsdns = None


class ContainerTestInfo(object):
    """Stores new container information used by dependent tests."""

    def __init__(self):
        self.dbaas = None  # The rich client instance used by these tests.
        self.dbaas_flavor_href = None  # The flavor of the container.
        self.dbaas_image = None  # The image used to create the container.
        self.dbaas_image_href = None  # The link of the image.
        self.id = None  # The ID of the instance in the database.
        self.ip = None  # The IP of the instance.
        self.myresult = None  # The container info returned by the API
        self.name = None  # Test name, generated each test run.
        self.pid = None # The process ID of the instance.
        self.user = None  # The user instance who owns the container.
        self.volume = None # The volume the container will have.

    def check_database(self, dbname):
        return check_database(self.id, dbname)

    def expected_dns_entry(self):
        """Returns expected DNS entry for this container.

        :rtype: Instance of :class:`DnsEntry`.

        """
        return create_dns_entry(container_info.user.auth_user,
                                container_info.id)


# The two variables are used below by tests which depend on a container
# existing.
container_info = ContainerTestInfo()
dbaas = None  # Rich client used throughout this test.


@test(groups=[GROUP, GROUP_START, 'dbaas.setup'], depends_on_groups=["services.initialize"])
class Setup(unittest.TestCase):
    """Makes sure the client can hit the ReST service.

    This test also uses the API to find the image and flavor to use.

    """

    def setUp(self):
        """Sets up the client."""
        global dbaas
        container_info.user = test_config.users.find_user(Requirements(is_admin=True))
        dbaas = TestClient(util.create_dbaas_client(container_info.user))

    def test_find_image(self):
        result = dbaas.find_image_and_self_href(test_config.dbaas_image)
        container_info.dbaas_image, container_info.dbaas_image_href = result

    def test_find_flavor(self):
        result = dbaas.find_flavor_and_self_href(flavor_id=1)
        container_info.dbaas_flavor, container_info.dbaas_flavor_href = result

    def test_create_container_name(self):
        container_info.name = "TEST_" + str(datetime.now())

@test(depends_on_groups=['dbaas.setup'], groups=[GROUP, GROUP_START, 'dbaas.mgmt.hosts'])
class ContainerHostCheck(unittest.TestCase):
    """Class to run tests after Setup"""
    
    def test_empty_index_host_list(self):
        host_index_result = dbaas.hosts.index()
        self.assertNotEqual(host_index_result, None,
                            "list hosts call should not be empty")
        print("result : %s" % str(host_index_result))
        self.assertTrue(len(host_index_result) > 0,
                        "list hosts length should not be empty")
        print("test_index_host_list result: %s" % str(host_index_result[0]))
        print("instance count for host : %d" % int(host_index_result[0].instanceCount))
        self.assertEquals(int(host_index_result[0].instanceCount), 0,
                          "instance count of 'host' should have 0 running instances")
        print("test_index_host_list result instance_count: %s" %
              str(host_index_result[0].instanceCount))
        self.assertEquals(len(host_index_result), 1,
                          "The result list is expected to be of length 1")
        for host in list(enumerate(host_index_result, start=1)):
            print("%d host: %s" % (host[0], host[1]))
            container_info.host = host[1]

    def test_empty_index_host_list_single(self):
        host_index_result = dbaas.hosts.get(container_info.host)
        self.assertNotEqual(host_index_result, None,
                            "list hosts should not be empty")
        print("test_index_host_list_single result: %s" %
              str(host_index_result))
        self.assertTrue(container_info.name
                        not in [dbc.name for dbc
                                in host_index_result.dbcontainers])
        for container in list(enumerate(host_index_result.dbcontainers, start=1)):
            print("%d dbcontainer: %s" % (container[0], container[1]))
            
    @expect_exception(NotFound)
    def test_host_not_found(self):
        container_info.myresult = dbaas.hosts.get('host@$%3dne')

@test(depends_on_classes=[Setup], groups=[GROUP, GROUP_START])
class CreateContainer(unittest.TestCase):
    """Test to create a Database Container

    If the call returns without raising an exception this test passes.

    """

    def test_create(self):
        global dbaas
        # give the services some time to start up
        time.sleep(2)

        databases = []
        databases.append({"name": "firstdb", "charset": "latin2",
                          "collate": "latin2_general_ci"})
        container_info.volume = {"size":1}

        container_info.result = dbaas.dbcontainers.create(
                                            container_info.name,
                                            container_info.dbaas_flavor_href,
                                            container_info.volume,
                                            databases)
        container_info.id = container_info.result.id
        
        # checks to be sure these are not found in the result
        result_dict = container_info.result.__dict__
        for attr in ["hostId","imageRef","metadata","adminPass"]:
            self.assertTrue(result_dict.get(attr) == None,
                            "Create response should not contain %s = %s" %
                            (attr, result_dict.get(attr)))
        # checks to be sure these are found in the result
        for attr in ["flavorRef","id","name","status","addresses","links","volume"]:
            self.assertTrue(result_dict.get(attr) != None,
                            "Create response should contain %s = %s attribute." %
                            (attr, result_dict.get(attr)))

    def test_get_container(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id).__dict__
        self.assertEquals(_dbaas_mapping[power_state.BUILDING], container_info.myresult['status'])

    def test_security_groups_created(self):
        if not db.security_group_exists(context.get_admin_context(), "dbaas", "tcp_3306"):
            self.assertFalse(True, "Security groups did not get created")


@test(depends_on_classes=[CreateContainer], groups=[GROUP, GROUP_START])
class VerifyGuestStarted(unittest.TestCase):
    """
        Test to verify the guest container is started and we can get the init
        process pid.
    """

    @time_out(60 * 8)
    def test_container_created(self):
        while True:
            status, err = process("sudo vzctl status %s | awk '{print $5}'"
                                  % str(container_info.id))

            if not string_in_list(status, ["running"]):
                time.sleep(5)
            else:
                self.assertEquals("running", status.strip())
                break


    @time_out(60 * 10)
    def test_get_init_pid(self):
        while True:
            out, err = process("pstree -ap | grep init | cut -d',' -f2 | vzpid - | grep %s | awk '{print $1}'"
                                % str(container_info.id))
            container_info.pid = out.strip()
            if not container_info.pid:
                time.sleep(10)
            else:
                break

    def test_guest_status_db_building(self):
        result = dbapi.guest_status_get(container_info.id)
        self.assertEqual(result.state, power_state.BUILDING)

    def test_guest_started_get_container(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id).__dict__
        self.assertEquals(_dbaas_mapping[power_state.BUILDING], container_info.myresult['status'])


@test(depends_on_classes=[VerifyGuestStarted], groups=[GROUP, GROUP_START])
class WaitForGuestInstallationToFinish(unittest.TestCase):
    """
        Wait until the Guest is finished installing.  It takes quite a while...
    """

    @time_out(60 * 8)
    def test_container_created(self):
        #/vz/private/1/var/log/nova/nova-guest.log
        while True:
            status, err = process(
                """cat /vz/private/%s/var/log/nova/nova-guest.log | grep "Dbaas" """
                % str(container_info.id))
            if not string_in_list(status, ["Dbaas preparation complete."]):
                time.sleep(5)
            else:
                break


@test(depends_on_classes=[WaitForGuestInstallationToFinish], groups=[GROUP, GROUP_START])
class TestGuestProcess(unittest.TestCase):
    """
        Test that the guest process is started with all the right parameters
    """

    @time_out(60 * 10)
    def test_guest_process(self):
        init_proc = re.compile("[\w\W\|\-\s\d,]*nova-guest --flagfile=/etc/nova/nova.conf nova[\W\w\s]*")
        guest_proc = re.compile("[\w\W\|\-\s]*/usr/bin/nova-guest --flagfile=/etc/nova/nova.conf[\W\w\s]*")
        apt = re.compile("[\w\W\|\-\s]*apt-get[\w\W\|\-\s]*")
        while True:
            guest_process, err = process("pstree -ap %s | grep nova-guest"
                                            % container_info.pid)
            if not string_in_list(guest_process, ["nova-guest"]):
                time.sleep(10)
            else:
                if apt.match(guest_process):
                    time.sleep(10)
                else:
                    init = init_proc.match(guest_process)
                    guest = guest_proc.match(guest_process)
                    if init and guest:
                        self.assertTrue(True, init.group())
                    else:
                        self.assertFalse(False, guest_process)
                    break

    @time_out(130)
    def test_guest_status_db_running(self):
        state = power_state.BUILDING
        while state != power_state.RUNNING:
            time.sleep(10)
            result = dbapi.guest_status_get(container_info.id)
            state = result.state
        time.sleep(1)
        self.assertEqual(state, power_state.RUNNING)


    def test_guest_status_get_container(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id).__dict__
        self.assertEquals(_dbaas_mapping[power_state.RUNNING], container_info.myresult['status'])


@test(depends_on_classes=[CreateContainer], groups=[GROUP, GROUP_START, "nova.volumes.container"])
class TestVolume(unittest.TestCase):
    """Make sure the volume is attached to container correctly."""

    def test_db_should_have_instance_to_volume_association(self):
        """The compute manager should associate a volume to the instance."""
        volumes = db.volume_get_all_by_instance(context.get_admin_context(), 
                                                container_info.id)
        self.assertEquals(1, len(volumes))

@test(depends_on_classes=[CreateContainer], groups=[GROUP, GROUP_START, "dbaas.listing"])
class TestContainListing(unittest.TestCase):
    """ Test the listing of the container information """
    
    def test_detail_list(self):
        container_info.myresult = dbaas.dbcontainers.details()
        self.assertTrue(self._detail_dbcontainers_exist())

    def test_index_list(self):
        container_info.myresult = dbaas.dbcontainers.index()
        self.assertTrue(self._index_dbcontainers_exist())

    def test_get_container(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id)
        self._assert_dbcontainers_exist()

    def test_get_container_status(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id).__dict__
        self.assertEquals(_dbaas_mapping[power_state.RUNNING], container_info.myresult['status'])

    def test_get_legacy_status(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id).__dict__
        if len(container_info.myresult)>0:
            self.assertTrue(True)
        else:
            self.assertTrue(False)

    def test_get_legacy_status_notfound(self):
        try:
            if dbaas.dbcontainers.get(-2):
                self.assertTrue(True)
            else:
                self.assertTrue(False)
        except NotFound:
            pass

    def test_volume_found(self):
        container_info.myresult = dbaas.dbcontainers.get(container_info.id).__dict__
        self.assertEquals(container_info.volume['size'],
                          container_info.myresult['volume']['size'])

    def _detail_dbcontainers_exist(self):
        for container in container_info.myresult:
            if not container.status:
                return False
            if not container.id and container.id != container_info.id:
                return False
            if not container.name:
                return False
            if not container.addresses:
                return False
            if not container.links:
                return False
            if not container.volume:
                return False
        return True

    def _index_dbcontainers_exist(self):
        for container in container_info.myresult:
            if not container.id and container.id != container_info.id:
                return False
            if not container.name:
                return False
            if not container.links:
                return False
        return True

    def _assert_dbcontainers_exist(self):
        container = container_info.myresult
        self.assertEqual(container_info.id, container.id)        
        self.assertTrue(container.name is not None)
        self.assertTrue(container.links is not None)
        if rsdns:
            dns_entry = container_info.expected_dns_entry()
            self.assertEqual(dns_entry.name, container.hostname)


@test(depends_on_classes=[CreateContainer], groups=[GROUP, "dbaas.mgmt.listing"])
class MgmtHostCheck(unittest.TestCase):
    def test_index_host_list(self):
        myresult = dbaas.hosts.index()
        self.assertNotEqual(myresult, None,
                            "list hosts should not be empty")
        self.assertTrue(len(myresult) > 0,
                        "list hosts should not be empty")
        print("test_index_host_list result: %s" % str(myresult))
        print("test_index_host_list result instance_count: %d" %
              myresult[0].instanceCount)
        self.assertEquals(myresult[0].instanceCount, 1,
                          "instance count of 'host' should have 1 running instances")
        self.assertEquals(len(myresult), 1,
                          "The result list is expected to be of length 1")
        for index, host in enumerate(myresult, start=1):
            print("%d host: %s" % (index, host))
            container_info.host = host

    def test_index_host_list_single(self):
        myresult = dbaas.hosts.get(container_info.host)
        self.assertNotEqual(myresult, None,
                            "list hosts should not be empty")
        print("test_index_host_list_single result: %s" %
              str(myresult))
        self.assertTrue(len(myresult.dbcontainers) > 0,
                        "dbcontainer list on the host should not be empty")
        print("test_index_host_list_single result dbcontainers: %s" %
              str(myresult.dbcontainers))
        for index, container in enumerate(myresult.dbcontainers, start=1):
            print("%d dbcontainer: %s" % (index, container))

@test(depends_on_groups=[GROUP_TEST], groups=[GROUP, GROUP_STOP],
      never_skip=True)
class DeleteContainer(unittest.TestCase):
    """ Delete the created container """

    @time_out(3 * 60)
    def test_delete(self):
        global dbaas
        if not hasattr(container_info, "result"):
            raise SkipTest("Container was never created, skipping test...")
        dbaas.dbcontainers.delete(container_info.result)

        try:
            time.sleep(1)
            while container_info.result:
                container_info.result = dbaas.dbcontainers.get(container_info.id)
                self.assertEquals(_dbaas_mapping[power_state.SHUTDOWN], container_info.result.status)
        except NotFound:
            pass

@test(depends_on_classes=[DeleteContainer], groups=[GROUP, GROUP_STOP])
class ContainerHostCheck2(ContainerHostCheck):
    """Class to run tests after delete"""

    @expect_exception(Exception)
    def test_host_not_found(self):
        container_info.myresult = dbaas.hosts.get('host-dne')

    @expect_exception(Exception)
    def test_host_not_found(self):
        container_info.myresult = dbaas.hosts.get('host@$%3dne')
