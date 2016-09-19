import argparse
import subprocess
import os
import getpass
import re
import shlex
import http.client
import ssl
import xml.dom.minidom
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
args = parser.parse_args()

if args.dest_sftp_site is None:
    args.dest_sftp_site = args.site

# Shorthands for me

site_httpdocs = DOCUMENT_ROOT + args.site + '/httpdocs'
dest_httpdocs = DOCUMENT_ROOT + args.dest_sftp_site + '/httpdocs'


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

    def __init__(self, host, port=8443, protocol='https', ssl_unverified=False):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.secret_key = None
        self.ssl_unverified = ssl_unverified

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

    def getInfo(self, reqType, reqInfo, reqFilter = None):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.  Basically, a big DOM wrapper.

        :param reqType: The type of request, can be customer, webspace (subscription), or site (domain)
        :param reqInfo: The type of information we're looking for.  Probably gen_info or hosting
        :param reqFilter: A filter to specify what object we're looking for
        :return: A dict that contains key:value pairs of the data
        """
        impl = xml.dom.minidom.getDOMImplementation()

        reqDom = impl.createDocument(None,"request",None)

        packetElm = reqDom.createElement('packet')
        packetElm.setAttribute('version', '1.6.3.5')
        customerElm = reqDom.createElement( reqType )
        getElm = reqDom.createElement('get')
        reqFilterElm = reqDom.createElement('reqFilter')
        if reqFilter is not None:
                reqFilterKeyElm = reqDom.createElement( reqFilter['key'])
                reqFilterKeyElm.appendChild(reqDom.createTextNode( reqFilter['value']))
                reqFilterElm.appendChild(reqFilterKeyElm)
        getElm.appendChild(reqFilterElm)
        datasetElm = reqDom.createElement( 'dataset' )
        datasetElm.appendChild(reqDom.createElement( reqInfo ))
        getElm.appendChild(datasetElm)
        customerElm.appendChild( getElm )
        packetElm.appendChild(customerElm)
        reqDom.appendChild(packetElm)
        reqDom.formatOutput = True

        response = self.__query(reqDom.saveXML())

        resDom = xml.dom.minidom.parseString(response)
        reqInfoDom = resDom.getElementsByTagName(reqInfo)[0]

        responseDict = {}
        for element in reqInfoDom:
            responseDict[element.nodeName] = element.nodeValue

        return responseDict
    
    def setInfo(self, setEntity, setType, setInfo, setFilter=None):
        """
        Submits a query to the Plesk API to set some information, such as create customer
        :param setEntity: What type of entity we're modifying - webspace, customer, etc.
        :param setType: What type of information we're giving plesk, gen_info, hosting, etc.
        :param setInfo: A dict containing key/value pairs of hosting/gen_info information
        :param setFilter: A dict with two members, 'key' and 'value' describing what we're modifying
        :return: Boolean with success
        """
        impl = xml.dom.minidom.getDOMImplementation()

        setDom = impl.createDocument(None,"request",None)

        packetElm = setDom.createElement('packet')
        packetElm.setAttribute('version', '1.6.3.5')
        customerElm = setDom.createElement( setEntity )
        getElm = setDom.createElement('set')
        setFilterElm = setDom.createElement('setFilter')
        if setFilter is not None:
                setFilterKeyElm = setDom.createElement( setFilter['key'])
                setFilterKeyElm.appendChild(setDom.createTextNode( setFilter['value']))
                setFilterElm.appendChild(setFilterKeyElm)
        getElm.appendChild(setFilterElm)
        datasetElm = setDom.createElement( 'dataset' )
        setTypeElm = setDom.createElement( setType )
        for infolet in setInfo:
            infoletElm = setDom.createElement(infolet[0])
            infoletElm.appendChild(setDom.createTextNode(infolet[1]))
            setTypeElm.appendChild(infoletElm)
        datasetElm.appendChild(setTypeElm)

        getElm.appendChild(datasetElm)
        customerElm.appendChild( getElm )
        packetElm.appendChild(customerElm)
        setDom.appendChild(packetElm)
        setDom.formatOutput = True

        response = self.__query(setDom.saveXML())
        
        resDom = xml.dom.minidom.parseString(response)
        result = resDom.getElementsByTagName('result')

        if result == 'ok':
            return True
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


def ssh(host, cmd, user, password, bg_run=False):
    """SSH'es to a host using the supplied credentials and executes a command.
    Throws an exception if the command doesn't return 0.
    bgrun: run command in the background"""





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

    if len(possible_db_refs) > 1:
        if (not (not (args.source_db_name is None) and not (args.source_db_pass is None) and not (
                    args.source_db_host is None))):
            print('I see possible database references in:')
            for item in possible_db_refs:
                print(item)
            print('This setup is too rich for my blood.  Try again manually specifying -sdn, -sdp, and -sdh.')
            exit(2)

    if (len(possible_db_refs) == 1) and (len(wp_roots) == 1) and (args.source_db_name is None) and (args.source_db_pass is None) and (args.source_db_host is None):
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

# Verify DNS abilities
step_placeholder('verify that we can alter DNS')

# Create new customer/domains on plesk
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
            child = pexpect.spawn('/bin/bash', ['-c', db_proc], timeout=None)
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
        child = pexpect.spawn('/bin/bash', ['-c', crap_proc], timeout=None)
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
        child = pexpect.spawn('/bin/bash', ['-c', tar_proc], timeout=None)
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
if not args.no_db:
    if len(magento_roots) != 0:
        step_placeholder('transfer any cron jobs')

# Transfer cron jobs
step_placeholder('switch that shell back')

# Disable old site next day
step_placeholder('make a reminder to disable the site the next day')
