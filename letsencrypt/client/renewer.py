"""Renewer tool to handle autorenewal and autodeployment of renewed
certs within lineages of successor certificates, according to
configuration."""

# os.path.islink
# os.readlink
# os.path.dirname / os.path.basename
# os.path.join

# TODO: sanity checking consistency, validity, freshness?

# TODO: call new installer API to restart servers after deployment

# TODO: when renewing or deploying, update config file to
#       memorialize the fact that it happened

import code #XXX: remove

import configobj
import copy
import datetime
import os
import OpenSSL
import pkg_resources
import pyrfc3339
import pytz
import re
import time

from letsencrypt.client import configuration
from letsencrypt.client import client
from letsencrypt.client import crypto_util
from letsencrypt.client import le_util
from letsencrypt.client import notify
from letsencrypt.client import storage
from letsencrypt.client.plugins import disco as plugins_disco

DEFAULTS = configobj.ConfigObj("renewal.conf")
DEFAULTS["renewal_configs_dir"] = "/tmp/etc/letsencrypt/configs"
DEFAULTS["official_archive_dir"] = "/tmp/etc/letsencrypt/archive"
DEFAULTS["live_dir"] = "/tmp/etc/letsencrypt/live"

class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

def renew(cert, old_version):
    """Perform automated renewal of the referenced cert, if possible."""
    # TODO: handle partial success
    # TODO: handle obligatory key rotation vs. optional key rotation vs.
    #       requested key rotation
    if not cert.configfile.has_key("renewalparams"):
        # TODO: notify user?
        return False
    renewalparams = cert.configfile["renewalparams"]
    if not renewalparams.has_key("authenticator"):
        # TODO: notify user?
        return False
    # Instantiate the appropriate authenticator
    plugins = plugins_disco.PluginsRegistry.find_all()
    try:
        config = configuration.NamespaceConfig(AttrDict(renewalparams))
        # XXX: this loses type data (for example, the fact that key_size
        #      was an int, not a str)
        config.rsa_key_size = int(config.rsa_key_size)
        authenticator = plugins[renewalparams["authenticator"]]
        authenticator = authenticator.init(config)
    except KeyError:
        # TODO: Notify user? (authenticator could not be found)
        return False


    authenticator.prepare()
    account = client.determine_account(config)
    # TODO: are there other ways to get the right account object, e.g.
    #       based on the email parameter that might be present in
    #       renewalparams?

    our_client = client.Client(config, account, authenticator, None)
    # XXX: find the domains
    with open(cert.version("cert", old_version)) as f:
        sans = crypto_util.get_sans_from_cert(f.read())
    new_cert, new_key, new_chain = our_client.obtain_certificate(sans)
    if new_cert and new_key and new_chain:
        # XXX: Assumes that there was no key change.  We need logic
        #      for figuring out whether there was or not.  Probably
        #      best is to have obtain_certificate return None for
        #      new_key if the old key is to be used (since save_successor
        #      already understands this distinction!)
        cert.save_successor(old_version, new_cert, new_key, new_chain)
    #    Notify results
    else:
    #    Notify negative results
        pass
    # TODO: Consider the case where the renewal was partially successful

def main(config=DEFAULTS):
    """main function for autorenewer script."""
    for i in os.listdir(config["renewal_configs_dir"]):
        print "Processing", i
        if not i.endswith(".conf"):
            continue
        try:
            cert = storage.RenewableCert(
                os.path.join(config["renewal_configs_dir"], i))
        except ValueError:
            # This indicates an invalid renewal configuration file, such
            # as one missing a required parameter (in the future, perhaps
            # also one that is internally inconsistent or is missing a
            # required parameter).  As a TODO, maybe we should warn the
            # user about the existence of an invalid or corrupt renewal
            # config rather than simply ignoring it.
            continue
        if cert.should_autodeploy():
            cert.update_all_links_to(cert.latest_common_version())
            # TODO: restart web server
            notify.notify("Autodeployed a cert!!!", "root", "It worked!")
            # TODO: explain what happened
        if cert.should_autorenew():
            # Note: not cert.current_version() because the basis for
            # the renewal is the latest version, even if it hasn't been
            # deployed yet!
            old_version = cert.latest_common_version()
            renew(cert, old_version)
            notify.notify("Autorenewed a cert!!!", "root", "It worked!")
            # TODO: explain what happened
