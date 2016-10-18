import argparse
import getpass
import http.client
import os
import random
import re
import shlex
import socket
import string
import subprocess
import sys
import xml.etree.ElementTree as ET

import pexpect

DOCUMENT_ROOT = '/var/www/vhosts/'
DATABASE_REFS = 'wp-config.php|etc/local.xml|includes?/(config.xml|connect.php)'

parser = argparse.ArgumentParser(description='migrate a website from one server to another')
parser.add_argument('site', help='the site to be migrated')
parser.add_argument('destination', help='where to move the site')

parser.add_argument('-v', '--verbose', help='explain what you are doing', action='store_true')
parser.add_argument('--no-db', help='skip the database migration', action='store_true')
parser.add_argument('--freshen', help='site already exists at destination, just freshen contents', action='store_true')
parser.add_argument('-sdn', '--source-db-name', help='what the database is currently named')
parser.add_argument('-ddn', '--dest-db-name', help='what the database should be named, defaults to source-db-name')
parser.add_argument('-sdu', '--source-db-user',
                    help='what user currently uses the database, defaults to source-db-name')
parser.add_argument('-ddu', '--dest-db-user', help='what user will use the database, defaults to dest-db-name')
parser.add_argument('-sdp', '--source-db-pass', nargs='?',
                    help='what the password for the user currently is, defaults to prompt', const='prompt')
parser.add_argument('-ddp', '--dest-db-pass', nargs='?',
                    help='what the password for the user should be, defaults to source-db-pass', const='prompt')
parser.add_argument('-sdh', '--source-db-host', help='where the database currently resides')
parser.add_argument('-ddh', '--dest-db-host', help='where the database should go', default='aws-db1.cluster-czcqe9ojhauq.us-east-1.rds.amazonaws.com')
parser.add_argument('-dsu', '--dest-sftp-user', help='the username for the customer SFTP account')
parser.add_argument('-dsp', '--dest-sftp-pass', help='the password for the customer SFTP account', nargs='?', const='prompt')
parser.add_argument('-dss', '--dest-sftp-site', help='the site name on the destination server, if different')

parser.add_argument('--no-plesk', help="don't try to mess with plesk", action='store_true')
parser.add_argument('-sph', '--source-plesk-host', help='the hostname of the source plesk instance, defaults to the current host', default=socket.gethostname())
parser.add_argument('-spu', '--source-plesk-user', help='the username of the source plesk instance, defaults to admin', default='admin')
parser.add_argument('-spp', '--source-plesk-pass', help='the password of the source plesk instance, defaults to prompt', nargs='?', const='prompt')
parser.add_argument('-dph', '--dest-plesk-host', help='the hostname of the destination plesk instance')
parser.add_argument('-dpu', '--dest-plesk-user', help='the username of the destination plesk instance, defaults to admin', default='admin')
parser.add_argument('-dpp', '--dest-plesk-pass', help='the password of the destination plesk instance, defaults to prompt', nargs='?', const='prompt')
parser.add_argument('-dpi', '--dest-plesk-ip', help='the ip address of the destination plesk instance')
parser.add_argument('-ec', '--existing-customer', help='the login id of the customer to append to')
parser.add_argument('-nc', '--new-customer', help='the name of the customer as it should appear in plesk')

args = parser.parse_args()

if args.dest_sftp_site is None:
    args.dest_sftp_site = args.site

# Shorthands for me

site_httpdocs = DOCUMENT_ROOT + args.site + '/httpdocs'
dest_httpdocs = DOCUMENT_ROOT + args.dest_sftp_site + '/httpdocs'

# Before we get too far, let's make sure we didn't fat finger the site name...

if not os.path.isdir(site_httpdocs):
    print('I cannot find that site.  Make sure you typed it correctly.')
    exit(1)

class WpInstance:
    """A class to represent an installation of WordPress"""

    def __init__(self, base_path):
        self.base_path = base_path
        self.config_path = base_path + '/wp-config.php'

        with open(self.config_path, 'r') as conf_fh:
            t_result = re.findall(r"""^define\(\s*['"]*(.*?)['"]*[\s,]+['"]*(.*?)['"]*\s*\)""", conf_fh.read(),
                                  re.IGNORECASE | re.DOTALL | re.MULTILINE)

        result = dict(t_result)

        self.user = result['DB_USER']
        self.password = result['DB_PASSWORD']
        self.name = result['DB_NAME']
        self.host = result['DB_HOST']

    def update_config(self, user=None, password=None, name=None, host=None):
        if user is None:
            user = self.user
        if password is None:
            password = self.password
        if name is None:
            name = self.name
        if host is None:
            host = self.host

        with open(self.config_path, 'r') as conf_fh:
            conf_data = conf_fh.read()

        with open(self.config_path, 'w') as conf_fh:
            replace_pairs = {
                "'DB_NAME', '{0}'".format(self.name): "'DB_NAME', '{0}'".format(name),
                "'DB_USER', '{0}'".format(self.user): "'DB_USER', '{0}'".format(user),
                "'DB_PASSWORD', '{0}'".format(self.password): "'DB_PASSWORD', '{0}'".format(password),
                "'DB_HOST', '{0}'".format(self.host): "'DB_HOST', '{0}'".format(host)
            }

            regexp = re.compile('|'.join(map(re.escape, replace_pairs)))

            new_conf_data = regexp.sub(lambda match: replace_pairs[match.group(0)], conf_data)
            conf_fh.write(new_conf_data)

        self.user = user
        self.name = name
        self.password = password
        self.host = host


class PleskApiClient:
    """A class to interact with Plesk Installations"""

    def __init__(self, host, port=8443, protocol='https', ssl_unverified=False, verbose=False):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.secret_key = None
        self.ssl_unverified = ssl_unverified
        self.verbose = verbose

    def set_credentials(self, login, password):
        self.login = login
        self.password = password

    def set_secret_key(self, secret_key):
        self.secret_key = secret_key

    def __query(self, request):
        headers = {}
        headers["Content-type"] = "text/xml"
        headers["HTTP_PRETTY_PRINT"] = "TRUE"

        if self.secret_key:
            headers["KEY"] = self.secret_key
        else:
            headers["HTTP_AUTH_LOGIN"] = self.login
            headers["HTTP_AUTH_PASSWD"] = self.password

        if 'https' == self.protocol:
            if self.ssl_unverified:
                conn = http.client.HTTPSConnection(self.host, self.port,
                                                   context=ssl._create_unverified_context())
            else:
                conn = http.client.HTTPSConnection(self.host, self.port)
        else:
            conn = http.client.HTTPConnection(self.host, self.port)

        conn.request("POST", "/enterprise/control/agent.php", request, headers)
        response = conn.getresponse()
        data = response.read()
        return data.decode("utf-8")

    def get_info(self, req_type, req_info, req_filter=None):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.

        :param req_type: The type of request, can be customer, webspace (subscription), or site (domain)
        :param req_info: The type of information we're looking for.  Probably gen_info or hosting
        :param req_filter: A filter to specify what object we're looking for
        :return: An XML element object rooted at the response section.  Returns False if entity not found
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        req_type_elm = ET.SubElement(packet_elm, req_type)
        get_elm = ET.SubElement(req_type_elm, 'get')
        req_filter_elm = ET.SubElement(get_elm, 'filter')
        if req_filter:
            for entity_filter in req_filter.items():
                req_filter_key_elm = ET.SubElement(req_filter_elm, entity_filter[0])
                req_filter_key_elm.text = entity_filter[1]
        dataset_elm = ET.SubElement(get_elm, 'dataset')
        ET.SubElement(dataset_elm, req_info)

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_et = ET.fromstring(response)

        if res_et.find('.//status').text == 'error':
            return False
        else:
            return res_et.find('.//id').text

    def get_customer_id(self, login_id):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.

        :param login_id: The username for the control panel user
        :return: A list with the customer id and the customer pretty name.  Returns False if entity not found
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        req_type_elm = ET.SubElement(packet_elm, 'customer')
        get_elm = ET.SubElement(req_type_elm, 'get')
        req_filter_elm = ET.SubElement(get_elm, 'filter')
        req_filter_key_elm = ET.SubElement(req_filter_elm, 'login')
        req_filter_key_elm.text = login_id
        dataset_elm = ET.SubElement(get_elm, 'dataset')
        ET.SubElement(dataset_elm, 'gen_info')

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_et = ET.fromstring(response)

        if res_et.find('.//status').text == 'error':
            return False
        else:
            returnee = []
            returnee[0] = res_et.find('.//id').text
            returnee[1] = res_et.find('.//pname').text
            return returnee

    def set_info(self, set_entity, set_type, set_info, set_filter=None):
        """
        Submits a query to the Plesk API to set some information, such as create customer
        :param set_entity: What type of entity we're modifying - webspace, customer, etc.
        :param set_type: What type of information we're giving plesk - gen_info, hosting, etc.
        :param set_info: A dict containing key/value pairs of hosting/gen_info information
        :param set_filter: A dict with two members, 'key' and 'value' describing what we're modifying
        :return: Boolean with success
        """
        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        set_entity_elm = ET.SubElement(packet_elm, set_entity)
        set_elm = ET.SubElement(set_entity_elm, 'set')
        set_filter_elm = ET.SubElement(set_elm, 'filter')
        if set_filter:
                reqFilterKeyElm = ET.SubElement(set_filter_elm, set_filter['key'])
                reqFilterKeyElm.text = set_filter['value']
        dataset_elm = ET.SubElement(set_elm, 'dataset')
        setTypeElm = ET.SubElement(dataset_elm, set_type)
        for infolet in set_info.items():
            infolet_elm = ET.SubElement(setTypeElm, infolet[0])
            infolet_elm.text = infolet[1]

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)
        res_info_elm = res_elm.find('result')

        if res_info_elm.text == 'ok':
            return True
        else:
            return False

    def set_webspace(self, hosting_info, site_id):
        """
        Creates an entity in plesk of type add_entity, and pre-populates it with information.

        :param hosting_info: A dict containing key/value pairs of hosting information
        :param site_id: This is the ID for the site to update
        :return: list with status and Id if success, or status and error if failure
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        set_entity_elm = ET.SubElement(packet_elm, 'webspace')
        set_elm = ET.SubElement(set_entity_elm, 'set')
        filter_elm = ET.SubElement(set_elm, 'filter')
        id_elm = ET.SubElement(filter_elm, 'id')
        id_elm.text = site_id
        values_elm = ET.SubElement(set_elm, 'values')
        hosting_elm = ET.SubElement(values_elm, 'hosting')
        vrt_hst_elm = ET.SubElement(hosting_elm, 'vrt_hst')
        for hostlet in hosting_info.items():
            property_elm = ET.SubElement(vrt_hst_elm, 'property')
            hostlet_name_elm = ET.SubElement(property_elm, 'name')
            hostlet_name_elm.text = hostlet[0]
            hostlet_value_elm = ET.SubElement(property_elm, 'value')
            hostlet_value_elm.text = hostlet[1]

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)

        if res_elm.find('.//status').text == 'ok':
            return ['ok', res_elm.find('.//id').text]
        else:
            return [res_elm.find('.//status').text, res_elm.find('.//errtext').text]

    def add_webspace(self, gen_setup, hosting_type, hosting_info, hosting_ip, hosting_plan):
        """
        Creates an entity in plesk of type add_entity, and pre-populates it with information.

        :param gen_setup: A dict containing key/value pairs of gen_info information
        :param hosting_type: If creating a webspace or forward, what kind of entity we're creating
        :param hosting_info: If creating a webspace or forward, a dict containing key/value pairs of hosting information
        :param hosting_plan: If creating a webspace, which plan to use
        :param hosting_ip: If creating a webspace, which IP address to bind to
        :return: list with status and Id if success, or status and error if failure
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        add_entity_elm = ET.SubElement(packet_elm, 'webspace')
        add_elm = ET.SubElement(add_entity_elm, 'add')
        gen_info_elm = ET.SubElement(add_elm, 'gen_setup')
        gen_setup['htype'] = hosting_type
        gen_setup['ip_address'] = hosting_ip
        for infolet in gen_setup.items():
            infolet_elm = ET.SubElement(gen_info_elm, infolet[0])
            infolet_elm.text = infolet[1]
        hosting_elm = ET.SubElement(add_elm, 'hosting')
        hosting_type_elm = ET.SubElement(hosting_elm, hosting_type)
        for hostlet in hosting_info.items():
            property_elm = ET.SubElement(hosting_type_elm, 'property')
            hostlet_name_elm = ET.SubElement(property_elm, 'name')
            hostlet_name_elm.text = hostlet[0]
            hostlet_value_elm = ET.SubElement(property_elm, 'value')
            hostlet_value_elm.text = hostlet[1]
        hosting_ip_elm = ET.SubElement(hosting_type_elm, 'ip_address')
        hosting_ip_elm.text = hosting_ip
        hosting_plan_elm = ET.SubElement(add_elm, 'plan-name')
        hosting_plan_elm.text = hosting_plan

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)

        if res_elm.find('.//status').text == 'ok':
            return ['ok', res_elm.find('.//id').text]
        else:
            return [res_elm.find('.//status').text, res_elm.find('.//errtext').text]

    def add_customer(self, customer_name):
        """
        Creates an entity in plesk of type add_entity, and pre-populates it with information.

        :param customer_name: A pretty version of the customer's name.
        :return: id of created entity
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        add_entity_elm = ET.SubElement(packet_elm, 'customer')
        add_elm = ET.SubElement(add_entity_elm, 'add')
        gen_info_elm = ET.SubElement(add_elm, 'gen_info')
        pname_elm = ET.SubElement(gen_info_elm, 'pname')
        pname_elm.text = customer_name
        login_elm = ET.SubElement(gen_info_elm, 'login')

        # Make a friendly customer login - strip out non-alphanum, limit to 20 characters, add _cp
        login_id = re.sub('[\W_]+', '', customer_name).lower()[:20] + '_cp'
        login_elm.text = login_id

        passwd_elm = ET.SubElement(gen_info_elm, 'passwd')
        passwd_elm.text = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.ascii_lowercase +
                                                               string.digits + '!@#$%^&*()/[]{}') for _ in range(34))

        email_elm = ET.SubElement(gen_info_elm, 'email')
        email_elm.text = 'hostmaster@firstscribe.com'

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)

        if res_elm.find('.//status').text == 'ok':
            return res_elm.find('.//id').text
        else:
            return False



def step_placeholder(action):
    print('Did you {0}?'.format(action))
    input('Press enter when done.')


def get_folder_size(folder):
    total_size = os.path.getsize(folder)
    for item in os.listdir(folder):
        itempath = os.path.join(folder, item)
        if os.path.isfile(itempath):
            total_size += os.path.getsize(itempath)
        elif os.path.isdir(itempath):
            total_size += get_folder_size(itempath)
    return total_size


def query_yes_no(question, default="yes"):  # http://code.activestate.com/recipes/577058/
    """
    Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    :param question: What's to be asked
    :param default: The default answer
    :return: Boolean
    """

    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        choice = input(question + prompt).lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

if not args.no_db:
    # Let's try to find a wordpress install

    db_ref_regexr = re.compile(DATABASE_REFS)

    wp_roots = []
    magento_roots = []
    possible_db_refs = []

    if args.verbose:
        print('Looking for magento/wordpress installs...')

    for root, dirs, files in os.walk(site_httpdocs):
        if 'app' in dirs:
            magento_roots.append(root)
        if 'wp-config.php' in files:
            wp_roots.append(root)

        # Although inefficient, build full paths so we can search for patterns with paths
        for name in files:
            full_path = os.path.join(root, name)
            if db_ref_regexr.search(full_path):
                possible_db_refs.append(full_path)

    if (len(possible_db_refs) > 1) and not all((args.source_db_name, args.source_db_pass, args.source_db_host)):
        print('I see possible database references in:')
        for item in possible_db_refs:
            print(item)
        print('This setup is too rich for my blood.  Try again manually specifying -sdn, -sdp, and -sdh.')
        exit(2)

    if (len(possible_db_refs) == 1) and (len(wp_roots) == 1) and not any(args.source_db_name, args.source_db_pass, args.source_db_host):
    # Sweet!  Single wordpress install.  I can handle this.
        wp_install = WpInstance(wp_roots[0])

        args.source_db_host = wp_install.host
        args.source_db_name = wp_install.name
        args.source_db_pass = wp_install.password
        args.source_db_user = wp_install.user

    if len(possible_db_refs) == 0:
        print('I did not see any possible database references.  Assuming --no-db, but you should probably check.')
        args.no_db = True

    # Populate the rest of the arguments

    if args.dest_db_name is None:
        args.dest_db_name = args.source_db_name
    if args.source_db_user is None:
        args.source_db_user = args.source_db_name
    if args.dest_db_user is None:
        args.dest_db_user = args.source_db_user
    if args.source_db_pass is 'prompt':
        args.source_db_pass = getpass.getpass(prompt='Please enter the source database password: ')
    if args.dest_db_pass is None:
        args.dest_db_pass = args.source_db_pass
    elif args.dest_db_pass is 'prompt':
        args.dest_db_pass = getpass.getpass(prompt='Please enter the destination database password: ')

if args.dest_sftp_pass is 'prompt':
    args.dest_sftp_pass = getpass.getpass(prompt='Please enter the password for the customer SFTP account: ')

# Create new customer/domains on plesk

if not args.no_plesk:
    if not args.dest_plesk_host:
        args.dest_plesk_host = args.destination
    if args.source_plesk_pass is 'prompt':
        args.source_plesk_pass = getpass.getpass(prompt="Please enter the password for {0}'s {1} account: ".format(args.source_plesk_host, args.source_plesk_user))
    if args.dest_plesk_pass is 'prompt':
        args.dest_plesk_pass = getpass.getpass(prompt="Please enter the password for {0}'s {1} account: ".format(args.dest_plesk_host, args.dest_plesk_user))
    if not all((args.source_plesk_host, args.source_plesk_user, args.source_plesk_pass, args.dest_plesk_host,
                args.dest_plesk_user, args.dest_plesk_pass, args.dest_plesk_ip)) and any((args.new_customer, args.existing_customer)):
        print('If I am to modify plesk, I will need the host, user, and password for both instances as well as a customer name')
        exit(1)

    # Now that that's taken care of

    # If the source system is in trustwave, make the outgoing port 8333 because their firewalls are silly.  Assumes
    #   iptables on the receiving end is redirecting 8333 to 8443, which should be set up on aws-web[1-3].
    if args.source_plesk_host in ['web3.firstscribe.com', 'web4.firstscribe.com']:
        port = 8333
    else:
        port = 8443

    source_plesk = PleskApiClient(args.source_plesk_host, verbose=args.verbose)
    source_plesk.set_credentials(args.source_plesk_user, args.source_plesk_pass)
    destination_plesk = PleskApiClient(args.dest_plesk_host, port=port, verbose=args.verbose)
    destination_plesk.set_credentials(args.dest_plesk_user, args.dest_plesk_pass)

    print('Creating customer... ', end='')
    if args.existing_customer:
        customer_id = destination_plesk(args.existing_customer)
    else:
        customer_id = destination_plesk.add_customer(args.new_customer)
    if customer_id:
        print('OK')
    else:
        print('')
        print('Failed to create customer!')
        exit(1)

    print('Creating site... ', end='')
    webspace_result = destination_plesk.add_webspace({'name': args.site, 'owner-id': customer_id}, 'vrt_hst',
                                                     {'ftp_login': args.dest_sftp_user,
                                                      'ftp_password': args.dest_sftp_pass, 'shell': '/bin/bash'},
                                                     args.dest_plesk_ip, 'Default Domain')

    if webspace_result[0] == 'ok':
        print('OK')
    else:
        print('')
        print('Failed to create site!')
        print('{0}: {1}'.format(webspace_result[0], webspace_result[1]))
        exit(1)

else:
    step_placeholder('make the new customer in plesk - use bash as shell')

# Copy SSL certs if any
step_placeholder('copy the SSL certificates')

# Copy any special hosting settings/php settings
step_placeholder('verify the PHP and hosting settings')

# Look for the existence of a vhost.conf file
if os.path.isfile('{0}/{1}/conf/vhost.conf'.format(DOCUMENT_ROOT, args.site)):
    see_conf = query_yes_no('I see custom vhost settings.  Would you like to see them?', default='no')
    if see_conf:
        with open('{0}/{1}/conf/vhost.conf'.format(DOCUMENT_ROOT, args.site), 'r') as conf_file:
            for line in conf_file:
                print(line, end='')

if not args.no_db:

    # Make database (through plesk, to get ref)
    step_placeholder('create the database mysql://{0}/{1}?user={2}&password={3} '.format(args.dest_db_host,
                                                                                        args.dest_db_name,
                                                                                        args.dest_db_user,
                                                                                        args.dest_db_pass))

    # Transfer the Database
    print('OK, I am going to try to migrate the database now...')

    db_proc = """mysqldump -u{0} -p{1} -h{2} {3} | sed "s/TIME_ZONE='+00:00'/TIME_ZONE='+06:00'/" | pv | xz -c -4 | ssh {4}@{5} "xz -d -c | mysql -u{6} -p{7} -h{8} {9}" """.format(
        args.source_db_user, shlex.quote(args.source_db_pass), args.source_db_host, args.source_db_name,
        args.dest_sftp_user, args.destination, args.dest_db_user, shlex.quote(args.dest_db_pass), args.dest_db_host,
        args.dest_db_name)
    if args.verbose:
        print(db_proc)
    try:
        # This is the "wrong" way to do it, but I can't get the nested Popen's to work
        if args.dest_sftp_pass is None:
            exitcode = subprocess.call(db_proc, shell=True)
        else:
            child = pexpect.spawnu('/bin/bash', ['-c', db_proc], timeout=None)
            child.expect(['password: '])
            child.sendline(args.dest_sftp_pass)
            child.logfile = sys.stdout
            child.expect(pexpect.EOF)
            child.close()

            exitcode = child.exitstatus
    except KeyboardInterrupt:
        exit(130)

    if exitcode != 0:
        print('DB copy failed.  Abort!')
        exit(1)

    # Update the DB refs in local.xmls or wp-config.php

    if (len(possible_db_refs) == 1) and (len(wp_roots) == 1):
        print('Updating wordpress configuration')
        wp_install.update_config(user=args.dest_db_user, password=args.dest_db_pass, name=args.dest_db_name,
                                 host=args.dest_db_host)
    else:
        step_placeholder('update database refs')

    # Clear magento cache
    if len(magento_roots) != 0:
        step_placeholder('clear the magento cache')

    # Make sure you didn't break anything
    step_placeholder('test the original site')

# Transfer the site

print('OK, I am going to try to migrate the site now...')
if args.freshen:
    print('Performing rsync, as freshen was defined.')
    if args.verbose:
        rsync_verbose = '--verbose '
    else:
        rsync_verbose = ''
    tar_proc = 'rsync -rtlD --delete {3}{0}/ {1}@{2}:{4}/'.format(site_httpdocs, args.dest_sftp_user, args.destination,
                                                                  rsync_verbose, dest_httpdocs)
else:
    tar_proc = 'tar cf - -C {0} . | pv -s {1} | xz -c |  ssh {2}@{3} "tar xJf - -C {4}"'.format(site_httpdocs,
                                                                                                get_folder_size(
                                                                                                    site_httpdocs),
                                                                                                args.dest_sftp_user,
                                                                                                args.destination,
                                                                                                dest_httpdocs)
    # The destination directory has crap, clear it out.
    if args.verbose:
        print('Clearing crap')
    crap_proc = 'ssh {0}@{1} "rm -rf {2}/*"'.format(args.dest_sftp_user, args.destination, dest_httpdocs)
    if args.dest_sftp_pass is None:
        exitcode = subprocess.call(crap_proc, shell=True)
    else:
        child = pexpect.spawnu('/bin/bash', ['-c', crap_proc], timeout=None)
        child.expect(['password: '])
        child.sendline(args.dest_sftp_pass)
        child.logfile = sys.stdout
        child.expect(pexpect.EOF)
        child.close()
if args.verbose:
    print(tar_proc)
try:
    # This is the "wrong" way to do it, but I can't get the nested Popen's to work
    if args.dest_sftp_pass is None:
        exitcode = subprocess.call(tar_proc, shell=True)
    else:
        child = pexpect.spawnu('/bin/bash', ['-c', tar_proc], timeout=None)
        child.expect(['password: '])
        child.sendline(args.dest_sftp_pass)
        child.logfile = sys.stdout
        child.expect(pexpect.EOF)
        child.close()

        exitcode = child.exitstatus
except KeyboardInterrupt:
    exit(130)

if exitcode != 0:
    print('Site copy failed.  Abort!')
    exit(1)

# If we host DNS, copy records
step_placeholder('update new DNS if on plesk')

# Test the site in the new location
step_placeholder('test the site in the new location')

# Update DNS/Switch Nameserver
step_placeholder('update the real DNS')

# Transfer cron jobs
if not args.no_db and (len(magento_roots) != 0):
    step_placeholder('transfer any cron jobs')

# Switch shell back to /chroot
if not args.no_plesk:
    print('Switching shell back to chroot... ', end='')
    shell_result = destination_plesk.set_webspace({'shell': '/usr/local/psa/bin/chrootsh'}, webspace_result[1])

    if shell_result[0] == 'ok':
        print('OK')
    else:
        print('')
        print('Failed to switch the shell back.  Take a look.')
        print('{0}: {1}'.format(webspace_result[0], webspace_result[1]))
        exit(1)
else:
    step_placeholder('switch that shell back')

exit(0)
