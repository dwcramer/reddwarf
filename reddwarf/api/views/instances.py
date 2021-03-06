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

import os


from nova import log as logging
from nova.api.openstack import common as nova_common
from nova.compute import power_state
from nova.exception import InstanceNotFound
from nova.notifier import api as notifier

from reddwarf.api import common
from reddwarf.api.views import flavors


LOG = logging.getLogger('reddwarf.api.views.instance')
LOG.setLevel(logging.DEBUG)


def _project_id(req):
    return getattr(req.environ['nova.context'], 'project_id', '')


def _base_url(req):
    return req.application_url

def _to_gb(bytes):
    return bytes/1024.0**3


class ViewBuilder(object):
    """Views for an instance"""

    def _build_basic(self, server, req, status_lookup):
        """Build the very basic information for an instance"""
        instance = {}
        instance['id'] = server['uuid']
        instance['name'] = server['name']
        instance['status'] = status_lookup.get_status_from_server(server).status
        instance['links'] = self._build_links(req, instance)
        return instance

    def _build_detail(self, server, req, instance):
        """Build out a more detailed view of the instance"""
        flavor_view = flavors.ViewBuilder(_base_url(req), _project_id(req))
        instance['flavor'] = server['flavor']
        instance['flavor']['links'] = flavor_view._build_links(instance['flavor'])
        instance['created'] = server['created']
        instance['updated'] = server['updated']
        # Add the hostname
        if 'hostname' in server:
            instance['hostname'] = server['hostname']

        # Add volume information
        dbvolume = self.build_volume(server)
        if dbvolume:
            instance['volume'] = dbvolume
        return instance

    @staticmethod
    def _build_links(req, instance):
        """Build the links for the instance"""

        # Fixup the base url to make sure we return https
        base_url = str(_base_url(req)).replace('http:', 'https:')

        href = os.path.join(base_url, _project_id(req),
                            "instances", str(instance['id']))
        bookmark = os.path.join(nova_common.remove_version_from_href(base_url),
                                "instances", str(instance['id']))
        links = [
            {
                'rel': 'self',
                'href': href
            },
            {
                'rel': 'bookmark',
                'href': bookmark
            }
        ]
        return links

    def build_index(self, server, req, status_lookup):
        """Build the response for an instance index call"""
        return self._build_basic(server, req, status_lookup)

    def build_detail(self, server, req, status_lookup):
        """Build the response for an instance detail call"""
        instance = self._build_basic(server, req, status_lookup)
        instance = self._build_detail(server, req, instance)
        return instance

    def build_single(self, server, req, status_lookup, create=False,
                     root_enabled=False, volume_info=None):
        """
        Given a server (obtained from the servers API) returns an instance.
        """
        instance = self._build_basic(server, req, status_lookup)
        instance = self._build_detail(server, req, instance)
        if not create:
            # Add root_enabled and volume_info
            instance['rootEnabled'] = root_enabled
            if volume_info:
                instance['volume']['used'] = _to_gb(volume_info['used'])

        return instance

    @staticmethod
    def build_volume(server):
        """Given a server dict returns the instance volume dict."""
        try:
            volumes = server['volumes']
            volume_dict = volumes[0]
        except (KeyError, IndexError):
            return None
        if len(volumes) > 1:
            error_msg = {'instanceId': server['id'],
                         'msg': "> 1 volumes in the underlying instance!"}
            LOG.error(error_msg)
            notifier.notify(notifier.publisher_id("reddwarf-api"),
                            'reddwarf.instance.list', notifier.ERROR,
                            error_msg)
        return {'size': volume_dict['size']}


class MgmtViewBuilder(ViewBuilder):
    """Management views for an instance"""

    def __init__(self):
        super(MgmtViewBuilder, self).__init__()

    def build_mgmt_single(self, server, instance_ref, req, status_lookup, volume_info):
        """Build out the management view for a single instance"""
        instance = self._build_basic(server, req, status_lookup)
        instance = self._build_detail(server, req, instance)
        instance = self._build_server_details(server, instance)
        instance = self._build_compute_api_details(instance_ref, instance)
        if volume_info:
            instance['volume']['used'] = _to_gb(volume_info['used'])
        return instance

    def build_guest_info(self, instance, status=None, dbs=None, users=None,
                         root_enabled=None):
        """Build out all possible information for a guest"""
        instance['guest_status'] = status.get_guest_status()
        instance['databases'] = dbs
        instance['users'] = users
        root_history = self.build_root_history(instance['id'],
                                                       root_enabled)
        instance['root_enabled_at'] = root_history['root_enabled_at']
        instance['root_enabled_by'] = root_history['root_enabled_by']
        return instance

    def build_root_history(self, id, root_enabled):
        if root_enabled is not None:
            return {
                    'id': id,
                    'root_enabled_at': root_enabled.created_at,
                    'root_enabled_by': root_enabled.user_id}
        else:
            return {
                    'id': id,
                    'root_enabled_at': 'Never',
                    'root_enabled_by': 'Nobody'
                   }

    @staticmethod
    def _build_server_details(server, instance):
        """Build more information from the servers api"""
        instance['addresses'] = server['addresses']
        del instance['links']
        return instance

    @staticmethod
    def _build_compute_api_details(instance_ref, instance):
        """Build out additional information from the compute api"""
        instance['server_state_description'] = instance_ref['vm_state']
        instance['host'] = instance_ref['host']
        instance['account_id'] = instance_ref['user_id']
        return instance

    @staticmethod
    def build_volume(server):
        """Build out a more detailed volumes view"""
        if 'volumes' in server:
            volumes = server['volumes']
            volume_dict = volumes[0]
        else:
            volume_dict = None
        return volume_dict
