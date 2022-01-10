# encoding: utf-8
from __future__ import unicode_literals

import argparse
import os

from .ansible import AnsibleBastionHost
from .cmd import run_ansible_playbook
from .utils import get_major_version
from .cluster import construct_cluster


UPGRADE_MSG = """
┌───────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│      The system has been upgraded to the latest version.                      │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘

"""



def add_command(subparsers):
    parser = subparsers.add_parser(
        "upgrade", help="upgrade onecloud cluster to specified version")
    #parser.add_argument('config', help="config file")
    # requirement options
    parser.add_argument("primary_master_host",
                        metavar="FIRST_MASTER_HOST",
                        help="onecloud cluster primary master host, \
                              e.g., 10.1.2.56")
    parser.add_argument("version",
                        metavar="VERSION",
                        help="onecloud version to be upgrade, \
                              e.g., v3.6.9")

    # optional options
    help_d = lambda help: help + " (default: %(default)s)"

    parser.add_argument("--user", "-u",
                        dest="ssh_user",
                        default="root",
                        help=help_d("primary master host ssh user"))

    parser.add_argument("--key-file", "-k",
                        dest="ssh_private_file",
                        default=os.path.expanduser("~/.ssh/id_rsa"),
                        help=help_d("primary master ssh private key file"))

    parser.add_argument("--port", "-p",
                        dest="ssh_port",
                        type=int,
                        default="22",
                        help=help_d("primary master host ssh port"))

    parser.add_argument("--as-bastion", "-B",
                        dest="primary_as_bastion",
                        action="store_true",
                        help="use primary master node as ssh bastion host to run ansible")

    parser.set_defaults(func=do_upgrade)


def do_upgrade(args):
    cluster = construct_cluster(
        args.primary_master_host,
        args.ssh_user,
        args.ssh_private_file,
        args.ssh_port)
    cur_ver = cluster.get_current_version()

    config = UpgradeConfig(cur_ver, args.version)

    bastion_host = None
    if args.primary_as_bastion:
        bastion_host = AnsibleBastionHost(args.primary_master_host)

    inventory_content = cluster.generate_playbook_inventory(bastion_host)
    inventory_f = '/tmp/test-hosts.ini'
    with open(inventory_f, 'w') as f:
        f.write(inventory_content)
    # start run upgrade playbook
    return_code = run_ansible_playbook(
        inventory_f,
        './onecloud/upgrade-cluster.yml',
        vars=config.to_ansible_vars(),
    )
    if return_code is not None and return_code != 0:
        return return_code
    cluster.set_current_version(args.version)
    print(UPGRADE_MSG.encode('utf-8'))


class UpgradeConfig(object):

    def __init__(self, cur_ver, upgrade_ver):
        self.current_onecloud_version = cur_ver
        self.current_onecloud_major_version = get_major_version(cur_ver)
        self.upgrade_onecloud_version = upgrade_ver
        self.upgrade_onecloud_major_version = get_major_version(upgrade_ver)

    def is_major_upgrade(self):
        return self.current_onecloud_major_version != self.upgrade_onecloud_major_version

    def get_yunion_yum_repo(self):
        ver = self.upgrade_onecloud_major_version.replace('_', '.')
        ver = ver[1:]
        return "https://iso.yunion.cn/yumrepo-%s/yunion.repo" % (ver)

    def to_ansible_vars(self):
        return {
            "current_onecloud_version": self.current_onecloud_version,
            "current_onecloud_major_version": self.current_onecloud_major_version,
            "upgrade_onecloud_version": self.upgrade_onecloud_version,
            "upgrade_onecloud_major_version": self.upgrade_onecloud_major_version,
            "is_major_upgrade": self.is_major_upgrade(),
            "yunion_yum_repo": self.get_yunion_yum_repo(),
        }
