# encoding: utf-8
from __future__ import unicode_literals

import json

from .ssh import SSHClient
from . import k8s

from .ocboot import GROUP_PRIMARY_MASTER_NODE, GROUP_MASTER_NODES, GROUP_WORKER_NODES

A_OCBOOT_UPGRADE_CURRENT_VERSION = 'upgrade.ocboot.yunion.io/current-version'


def construct_cluster(primary_master_host, ssh_user, ssh_private_file, ssh_port):
    cli = SSHClient(
        primary_master_host,
        ssh_user,
        ssh_private_file,
        ssh_port,
    )

    cluster = OnecloudCluster(cli)
    return cluster


class OnecloudCluster(object):

    def __init__(self, ssh_client):
        self.ssh_client = ssh_client

        cluster = json.loads(ssh_client.exec_command(
            'kubectl -n onecloud get onecloudclusters default -o json'))
        self.cluster = k8s.Resource(cluster)

        self.k8s_nodes = None
        self.primary_master_node = None
        self.master_nodes = None
        self.worker_nodes = None
        self._construct_nodes()

    def get_primary_master_node_ip(self):
        endpoint = self.get_spec().get('loadBalancerEndpoint')
        if endpoint:
            return endpoint
        return self.ssh_client.get_host()

    def get_metadata(self):
        return self.cluster.get_metadata()

    def get_annotations(self):
        return self.cluster.get_annotations()

    def get_spec(self):
        return self.cluster.get_spec()

    def get_current_version(self):
        version = self.get_annotations().get(A_OCBOOT_UPGRADE_CURRENT_VERSION, None)
        if version:
            return version
        return self.get_spec().get('version')

    def _construct_nodes(self):
        k8s_nodes = json.loads(self.ssh_client.exec_command('kubectl get nodes -o json')).get('items')
        self.k8s_nodes = [k8s.Node(obj) for obj in k8s_nodes]
        self.master_nodes = [node for node in self.k8s_nodes if node.is_master()]
        self.worker_nodes = [node for node in self.k8s_nodes if not node.is_master()]
        self.primary_master_node = self.find_primary_master_node(self.master_nodes)

    def find_primary_master_node(self, master_nodes):
        master_nodes.sort(key=lambda node: node.creationTimestamp())
        p_m_node = master_nodes[0]
        master_nodes.remove(p_m_node)
        return p_m_node

    def find_node_by_ip_or_hostname(self, ip_hostname):
        k = ip_hostname
        for node in self.k8s_nodes:
            if node.get_hostname() == k or node.get_ip() == k:
                return node
        return None

    def generate_playbook_inventory(self, bastion_host=None):
        inventory = AnsibleInventory()

        def add_i(node):
            if bastion_host:
                node.with_bastion(bastion_host)
            inventory.add(node)

        add_i(AnsiblePrimaryMasterHost(self.primary_master_node))

        for node in self.master_nodes:
            add_i(AnsibleMasterHost(node))

        for node in self.worker_nodes:
            add_i(AnsibleWorkerHost(node))

        return inventory.generate_content()

    def set_current_version(self, version):
        cmd = 'kubectl -n onecloud annotate --overwrite=true onecloudclusters default %s=%s' % (
            A_OCBOOT_UPGRADE_CURRENT_VERSION,
            version)
        self.ssh_client.exec_command(cmd)


class AnsibleInventory(object):

    def __init__(self):
        self.all_hosts = []
        self.primary_master_host = None
        self.master_hosts = []
        self.worker_hosts = []

    def _append(self, hosts, host):
        for a_host in hosts:
            if host.get_hostname() == a_host.get_hostname():
                return
        hosts.append(host)

    def _add(self, host):
        self._append(self.all_hosts, host)
        role = host.get_role()
        if role == GROUP_PRIMARY_MASTER_NODE:
            self.primary_master_host = host
        elif role == GROUP_MASTER_NODES:
            self._append(self.master_hosts, host)
        elif role == GROUP_WORKER_NODES:
            self._append(self.worker_hosts, host)
        else:
            raise Exception("Unsupported role %s" % role)


    def add(self, *hosts):
        for host in hosts:
            self._add(host)

    def generate_content(self):
        ret = ['[all]']
        ret.extend([host.get_content() for host in self.all_hosts])

        ret.append('[%s]' % GROUP_PRIMARY_MASTER_NODE)
        ret.append(self.primary_master_host.get_hostname())

        ret.append('[%s]' % GROUP_MASTER_NODES)
        ret.extend([host.get_hostname() for host in self.master_hosts])

        ret.append('[%s]' % GROUP_WORKER_NODES)
        ret.extend([host.get_hostname() for host in self.worker_hosts])

        return '\n'.join(ret)


class ansibleHost(object):

    def __init__(self, node, role, user='root'):
        self.hostname = node.get_hostname()
        self.ip = node.get_ip()
        self.role = role
        self.user = user
        self.bastion_host = None

    def get_hostname(self):
        return self.hostname

    def get_ip(self):
        return self.ip

    def get_role(self):
        return self.role

    def with_bastion(self, bastion_host):
        self.bastion_host = bastion_host
        return self

    def get_content(self):
        config = '%s ansible_host=%s ansible_ssh_user=%s' % (
            self.hostname,
            self.ip,
            self.user)
        if self.bastion_host:
            config += " ansible_ssh_common_args='%s'" % self.bastion_host.to_option()
        return config


class AnsiblePrimaryMasterHost(ansibleHost):

    def __init__(self, node, user='root'):
        super(AnsiblePrimaryMasterHost, self).__init__(
            node, GROUP_PRIMARY_MASTER_NODE, user)


class AnsibleMasterHost(ansibleHost):

    def __init__(self, node, user='root'):
        super(AnsibleMasterHost, self).__init__(
            node, GROUP_MASTER_NODES, user)


class AnsibleWorkerHost(ansibleHost):

    def __init__(self, node, user='root'):
        super(AnsibleWorkerHost, self).__init__(
            node, GROUP_WORKER_NODES, user)
