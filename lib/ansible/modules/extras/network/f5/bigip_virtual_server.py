#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2015, Etienne Carriere <etienne.carriere@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: bigip_virtual_server
short_description: "Manages F5 BIG-IP LTM virtual servers"
description:
    - "Manages F5 BIG-IP LTM virtual servers via iControl SOAP API"
version_added: "2.0"
author: Etienne Carriere
notes:
    - "Requires BIG-IP software version >= 11"
    - "F5 developed module 'bigsuds' required (see http://devcentral.f5.com)"
    - "Best run as a local_action in your playbook"
requirements:
    - bigsuds
options:
    server:
        description:
            - BIG-IP host
        required: true
        default: null
        choices: []
        aliases: []
    user:
        description:
            - BIG-IP username
        required: true
        default: null
        choices: []
        aliases: []
    password:
        description:
            - BIG-IP password
        required: true
        default: null
        choices: []
        aliases: []
    validate_certs:
        description:
            - If C(no), SSL certificates will not be validated. This should only be used
              on personally controlled sites using self-signed certificates.
        required: false
        default: 'yes'
        choices: ['yes', 'no']
        version_added: 2.0
    state:
        description:
            - Pool member state
        required: true
        default: present
        choices: ['present', 'absent', 'enabled', 'disabled']
        aliases: []
    partition:
        description:
            - Partition
        required: false
        default: 'Common'
        choices: []
        aliases: []
    name:
        description:
            - "Virtual server name."
        required: true
        default: null
        choices: []
        aliases: ['vs']
    destination:
        description:
            - "Destination IP of the virtual server (only host is currently supported) . Required when state=present and vs does not exist. Error when state=absent."
        required: true
        default: null
        choices: []
        aliases: ['address', 'ip']
    port:
        description:
            - "Port of the virtual server . Required when state=present and vs does not exist"
        required: true
        default: null
        choices: []
        aliases: []
    all_profiles:
        description:
            - "List of all Profiles (HTTP,ClientSSL,ServerSSL,etc) that must be used by the virtual server"
        required: false
        default: null
        choices: []
        aliases: []
    pool:
        description:
            - "Default pool for the virtual server"
        required: false
        default: null
        choices: []
        aliases: []
    snat:
        description:
            - "Source network address policy"
        required: false
        default: None
        choices: []
        aliases: []

    description:
        description:
            - "Virtual server description."
        required: false
        default: null
        choices: []
'''

EXAMPLES = '''

## playbook task examples:

---
# file bigip-test.yml
# ...
  - name: Add VS
    local_action:
        module: bigip_virtual_server
        server: lb.mydomain.net
        user: admin
        password: secret
        state: present
        partition: MyPartition
        name: myvirtualserver
        destination: "{{ ansible_default_ipv4["address"] }}"
        port: 443
        pool: "{{ mypool }}"
        snat: Automap
        description: Test Virtual Server
        all_profiles:
            - http
            - clientssl

  - name: Modify Port of the Virtual Server
    local_action:
        module: bigip_virtual_server
        server: lb.mydomain.net
        user: admin
        password: secret
        state: present
        partition: MyPartition
        name: myvirtualserver
        port: 8080

  - name: Delete pool
    local_action:
        module: bigip_virtual_server
        server: lb.mydomain.net
        user: admin
        password: secret
        state: absent
        partition: MyPartition
        name: myvirtualserver
'''

try:
    import bigsuds
except ImportError:
    bigsuds_found = False
else:
    bigsuds_found = True

# ==========================
# bigip_node module specific
#

# map of state values
STATES={'enabled': 'STATE_ENABLED',
        'disabled': 'STATE_DISABLED'}
STATUSES={'enabled': 'SESSION_STATUS_ENABLED',
          'disabled': 'SESSION_STATUS_DISABLED',
          'offline': 'SESSION_STATUS_FORCED_DISABLED'}

def bigip_api(bigip, user, password):
    api = bigsuds.BIGIP(hostname=bigip, username=user, password=password)
    return api

def disable_ssl_cert_validation():
    # You probably only want to do this for testing and never in production.
    # From https://www.python.org/dev/peps/pep-0476/#id29
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context

def fq_name(partition,name):
    if name is None:
        return None
    if name[0] is '/':
        return name
    else:
        return '/%s/%s' % (partition,name)

def fq_list_names(partition,list_names):
    if list_names is None:
        return None
    return map(lambda x: fq_name(partition,x),list_names)


def vs_exists(api, vs):
    # hack to determine if pool exists
    result = False
    try:
        api.LocalLB.VirtualServer.get_object_status(virtual_servers=[vs])
        result = True
    except bigsuds.OperationFailed, e:
        if "was not found" in str(e):
            result = False
        else:
            # genuine exception
            raise
    return result

def vs_create(api,name,destination,port,pool):
    _profiles=[[{'profile_context': 'PROFILE_CONTEXT_TYPE_ALL', 'profile_name': 'tcp'}]]
    try:
        api.LocalLB.VirtualServer.create(
            definitions = [{'name': [name], 'address': [destination], 'port': port, 'protocol': 'PROTOCOL_TCP'}],
            wildmasks = ['255.255.255.255'],
            resources = [{'type': 'RESOURCE_TYPE_POOL', 'default_pool_name': pool}],
            profiles = _profiles)
        result = True 
        desc = 0
    except Exception, e :
        print e.args

def vs_remove(api,name):
    api.LocalLB.VirtualServer.delete_virtual_server(virtual_servers = [name ])

def get_profiles(api,name):
    return api.LocalLB.VirtualServer.get_profile(virtual_servers = [name])[0]



def set_profiles(api,name,profiles_list):
    if profiles_list is None:
        return False
    current_profiles=map(lambda x:x['profile_name'], get_profiles(api,name))
    to_add_profiles=[]
    for x in profiles_list:
        if x not in current_profiles:
            to_add_profiles.append({'profile_context': 'PROFILE_CONTEXT_TYPE_ALL', 'profile_name': x})
    to_del_profiles=[]
    for x in current_profiles:
        if (x not in profiles_list) and (x!= "/Common/tcp"):
            to_del_profiles.append({'profile_context': 'PROFILE_CONTEXT_TYPE_ALL', 'profile_name': x})
    changed=False
    if len(to_del_profiles)>0:
        api.LocalLB.VirtualServer.remove_profile(virtual_servers = [name],profiles = [to_del_profiles])
        changed=True
    if len(to_add_profiles)>0:
        api.LocalLB.VirtualServer.add_profile(virtual_servers = [name],profiles= [to_add_profiles])
        changed=True
    return changed


def set_snat(api,name,snat):
    current_state=get_snat_type(api,name)
    update = False
    if snat is None:
        return update
    if snat == 'None' and current_state != 'SRC_TRANS_NONE':
        api.LocalLB.VirtualServer.set_source_address_translation_none(virtual_servers = [name])
        update = True
    if snat == 'Automap' and current_state != 'SRC_TRANS_AUTOMAP':
        api.LocalLB.VirtualServer.set_source_address_translation_automap(virtual_servers = [name])
        update = True
    return update

def get_snat_type(api,name):
    return api.LocalLB.VirtualServer.get_source_address_translation_type(virtual_servers = [name])[0]


def get_pool(api,name):
    return api.LocalLB.VirtualServer.get_default_pool_name(virtual_servers = [name])[0]

def set_pool(api,name,pool):
    current_pool = get_pool (api,name)
    updated=False
    if pool is not None and (pool != current_pool):
        api.LocalLB.VirtualServer.set_default_pool_name(virtual_servers = [name],default_pools = [pool])
        updated=True
    return updated



def get_destination(api,name):
    return api.LocalLB.VirtualServer.get_destination_v2(virtual_servers = [name])[0]

def set_destination(api,name,destination,port):
    current_destination = get_destination(api,name)
    updated=False
    if (destination is not None and port is not None) and (destination != current_destination['address'] or port != current_destination['port']):
        api.LocalLB.VirtualServer.set_destination_v2(virtual_servers = [name],destinations=[{'address': destination, 'port':port}])
        updated=True
    return updated


def get_description(api,name):
    return api.LocalLB.VirtualServer.get_description(virtual_servers = [name])[0]

def set_description(api,name,description):
    current_description = get_description(api,name)
    updated=False
    if description is not None and current_description != description:
        api.LocalLB.VirtualServer.set_description(virtual_servers =[name],descriptions=[description])
        updated=True
    return updated


def main():
    module = AnsibleModule(
        argument_spec = dict(
            server = dict(type='str', required=True),
            user = dict(type='str', required=True),
            password = dict(type='str', required=True),
            validate_certs = dict(default='yes', type='bool'),
            state = dict(type='str', default='present',
                         choices=['present', 'absent', 'disabled', 'enabled']),
            partition = dict(type='str', default='Common'),
            name = dict(type='str', required=True,aliases=['vs']),
            destination = dict(type='str', aliases=['address', 'ip']),
            port = dict(type='int'),
            all_profiles = dict(type='list'),
            pool=dict(type='str'),
            description = dict(type='str'),
            snat=dict(type='str')
        ),
        supports_check_mode=True
    )

    if not bigsuds_found:
        module.fail_json(msg="the python bigsuds module is required")
    server = module.params['server']
    user = module.params['user']
    password = module.params['password']
    validate_certs = module.params['validate_certs']
    state = module.params['state']
    partition = module.params['partition']
    name = fq_name(partition,module.params['name'])
    destination=module.params['destination']
    port=module.params['port']
    all_profiles=fq_list_names(partition,module.params['all_profiles'])
    pool=fq_name(partition,module.params['pool'])
    description = module.params['description']
    snat = module.params['snat']
    if not validate_certs:
        disable_ssl_cert_validation()

    if 1 > port > 65535:
        module.fail_json(msg="valid ports must be in range 1 - 65535")
  
    try:
        api = bigip_api(server, user, password)
        result = {'changed': False}  # default

        if state == 'absent':
                if not module.check_mode:
                    if vs_exists(api,name):
                        # hack to handle concurrent runs of module
                        # pool might be gone before we actually remove
                        try:
                            vs_remove(api,name)
                            result = {'changed' : True, 'deleted' : name }
                        except bigsuds.OperationFailed, e:
                            if "was not found" in str(e):
                                result['changed']= False
                            else:
                                raise
                else:
                    # check-mode return value
                    result = {'changed': True}

        elif state == 'present':
            update = False
            if not vs_exists(api, name):
                if (not destination) or (not port):
                    module.fail_json(msg="both destination and port must be supplied to create a VS")
                if not module.check_mode:
                    # a bit of a hack to handle concurrent runs of this module.
                    # even though we've checked the pool doesn't exist,
                    # it may exist by the time we run create_pool().
                    # this catches the exception and does something smart
                    # about it!
                    try:
                        vs_create(api,name,destination,port,pool)
                        result = {'changed': True}
                    except bigsuds.OperationFailed, e:
                        if "already exists" in str(e):
                            update = True
                        else:
                            raise
                    else:
                        set_profiles(api,name,all_profiles)
                        set_snat(api,name,snat)
                        set_description(api,name,description)
                else:
                    # check-mode return value
                    result = {'changed': True}
            else:
                update = True
            if update:
                # VS exists
                if not module.check_mode:
                    # Have a transaction for all the changes
                    api.System.Session.start_transaction()
                    result['changed']|=set_destination(api,name,fq_name(partition,destination),port)
                    result['changed']|=set_pool(api,name,pool)
                    result['changed']|=set_description(api,name,description)
                    result['changed']|=set_snat(api,name,snat)
                    result['changed']|=set_profiles(api,name,all_profiles)
                    api.System.Session.submit_transaction()
                else:
                    # check-mode return value
                    result = {'changed': True}

        elif state in ('disabled', 'enabled'):
            if name is None:
                module.fail_json(msg="name parameter required when " \
                                     "state=enabled/disabled")
            if not module.check_mode:
                pass
            else:
                # check-mode return value
                result = {'changed': True}

    except Exception, e:
        module.fail_json(msg="received exception: %s" % e)

    module.exit_json(**result)
# import module snippets
from ansible.module_utils.basic import *
main()
