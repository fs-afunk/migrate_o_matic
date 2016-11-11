import argparse
import getpass
import os
import re
import shlex
import socket
import subprocess
import sys

import pexpect

import cms.wordpress
import plesk.apiclient

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

    possible_db_refs = []
    wp_roots = []
    magento_roots = []

    # Let's try to find a database references...

    db_ref_regexr = re.compile(DATABASE_REFS)

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

    if any((args.source_db_name, args.source_db_pass, args.source_db_host)):
        # They tried to define database parameters.  Let's see if they got it right
        if not all((args.source_db_name, args.source_db_pass, args.source_db_host)):
            print('If specifying database parameters, I need at a minimum -sdn, -sdp, and -sdh.')
            exit(2)
    else:  # Try to autodetect

        if (len(possible_db_refs) > 1):
            print('I see possible database references in:')
            for item in possible_db_refs:
                print(item)
            print('This setup is too rich for my blood.  Try again manually specifying -sdn, -sdp, and -sdh.')
            exit(2)

        if (len(possible_db_refs) == 1) and (len(wp_roots) == 1):
            # Sweet!  Single wordpress install.  I can handle this.
            wp_install = cms.wordpress.Instance(wp_roots[0])

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

    # Create the objects first

    # If the source system is in trustwave, make the outgoing port 8333 because their firewalls are silly.  Assumes
    #   iptables on the receiving end is redirecting 8333 to 8443, which should be set up on aws-web[1-3].
    if args.source_plesk_host in ['web3.firstscribe.com', 'web4.firstscribe.com']:
        dest_port = 8333
    else:
        dest_port = 8443

    source_plesk = plesk.apiclient.Client(args.source_plesk_host, verbose=args.verbose)
    destination_plesk = plesk.apiclient.Client(args.dest_plesk_host, port=dest_port, verbose=args.verbose)

    # Let's autofill as much information as we can.

    source_plesk.lookup_plesk_info()
    destination_plesk.lookup_plesk_info()

    if args.source_plesk_pass is 'prompt':
        args.source_plesk_pass = getpass.getpass(
            prompt="Please enter the password for {0}'s {1} account: ".format(args.source_plesk_host,
                                                                              args.source_plesk_user))
        source_plesk.set_credentials(args.source_plesk_user, args.source_plesk_pass)

    if args.dest_plesk_pass is 'prompt':
        args.dest_plesk_pass = getpass.getpass(
            prompt="Please enter the password for {0}'s {1} account: ".format(args.dest_plesk_host,
                                                                              args.dest_plesk_user))
        destination_plesk.set_credentials(args.dest_plesk_user, args.dest_plesk_pass)

    if args.dest_plesk_ip:
        destination_plesk.internal_ip = args.dest_plesk_ip

    if not (all((source_plesk.host, source_plesk.login, source_plesk.password, destination_plesk.host,
                 destination_plesk.login, destination_plesk.password, destination_plesk.internal_ip)) or not any(
            (args.new_customer, args.existing_customer))):
        print(
            'If I am to modify plesk, I will need the host, user, and password for both instances as well as a customer name')
        exit(1)



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
        dest_site_id = webspace_result[1]
    else:
        print('')
        print('Failed to create site!')
        print('{0}: {1}'.format(webspace_result[0], webspace_result[1]))
        exit(1)

    source_site_id = source_plesk.get_site_id(args.site)

else:
    step_placeholder('make the new customer in plesk - use bash as shell')

# Copy SSL certs if any
step_placeholder('copy the SSL certificates')

# Copy any special hosting settings/php settings
step_placeholder('verify the PHP and hosting settings')

# Make sure there aren't protected directories
if not args.no_plesk:
    protected_dirs = source_plesk.get_protected_dirs(source_site_id)
    if len(protected_dirs) > 0:
        print('There are protected directories.  Please create them on the destination.')
else:
    step_placeholder('verify any protected directories')


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
