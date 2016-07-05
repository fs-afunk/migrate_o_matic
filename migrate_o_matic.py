import argparse
import subprocess
import os
import getpass
import re
import shlex
import xml.dom.minidom

DOCUMENT_ROOT = '/var/www/vhosts/'
DATABASE_REFS = 'wp-config.php|etc/local.xml|includes?/(config.xml|connect.php)$'

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
parser.add_argument('-ddh', '--dest-db-host', help='where the database should go', default='aws-db1.firstscribe.com')
parser.add_argument('-dsu', '--dest-sftp-user', help='the username for the customer SFTP account')
#parser.add_argument('-dsp', '--dest-sftp-pass', help='the password for the customer SFTP account', nargs='?', const='prompt')  # I can't figure out how to do anything with this...
args = parser.parse_args()

# If no-db is not defined, we need at least sdn, sdp, and sdh

if not args.no_db and (
not (not (args.source_db_name is None) and not (args.source_db_pass is None) and not (args.source_db_host is None))):
    print('If --no-db is not specified, you must define at least -sdn, -sdp, and -sdh.')
    exit(2)

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
#if args.dest_sftp_pass is 'prompt':
#    args.dest_sftp_pass = getpass.getpass(prompt='Please enter the password for the customer SFTP account: ')

# Shorthands for me

site_httpdocs = DOCUMENT_ROOT + args.site + '/httpdocs'

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

def magento_cred_parse(path):
    xmldoc = xml.dom.minidom.parse(path)
    config = xmldoc.documentElement
    conn = config.find('.//connection')

def wp_cred_parse(path):
    f = open(path,'r')
    result = re.findall(r"""^define\(\s*['"]*(.*?)['"]*[\s,]+['"]*(.*?)['"]*\s*\)""", f.read(), re.IGNORECASE | re.DOTALL | re.MULTILINE)
    f.close()
    return dict(result)

def query_yes_no(question, default="yes"):  # http://code.activestate.com/recipes/577058/
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
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
        sys.stdout.write(question + prompt)
        choice = raw_input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")



# Verify DNS abilities
step_placeholder('verify that we can alter DNS')

# Notify customer
step_placeholder('notify the customer')

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
        with open('{0}/{1}/conf/vhost.conf'.format(DOCUMENT_ROOT, args.site), 'rb') as conf_file:
            for line in conf_file:
                print(line, end='')

if not args.no_db:
    # Try to find Magento and Wordpress installs, as well as other DB refs
    db_ref_regexr = re.compile(DATABASE_REFS)

    wp_roots = []
    magento_roots = []
    possible_db_refs = []

    for root, dirs, files in os.walk(site_httpdocs):
        if 'app' in dirs:
            magento_roots.append(root)
        if 'wp-config.php' in files:
            wp_roots.append(root)

        # Although inefficient, build full paths so we can search for patterns with paths
        for name in files:
            full_path=os.path.join(root, name)
            if db_ref_regexr.search(full_path):
                possible_db_refs.append(full_path)

    print('I see possible database references in:')
    for item in possible_db_refs:
        print(item)

    print('Does that look right?')
    input('Press enter to continue.')

    # Make database (through plesk, to get ref)
    step_placeholder('create the database {0}'.format(args.dest_db_name))

    # Transfer the Database

    # I bit off more than I can chew...

    # mysqldump_proc = subprocess.Popen(
    #     ('mysqldump', '-u', args.source_db_user, '-h', args.source_db_host, '-p', args.source_db_pass, args.source_db_name),
    #     stdout=subprocess.PIPE)
    # sed_proc = subprocess.Popen(('sed', 's/TIME_ZONE=\'+00:00\'/TIME_ZONE=\'+06:00\'/'), stdout=subprocess.PIPE,
    #                             stdin=mysqldump_proc.stdout)
    # mysqldump_proc.stdout.close()
    # pv_proc = subprocess.Popen('pv',
    #                            stdin=sed_proc.stdout, stdout=subprocess.PIPE)
    # sed_proc.stdout.close()
    # xz_proc = subprocess.Popen(('xz', '-c', '-4'), stdout=subprocess.PIPE, stdin=pv_proc.stdout)
    # pv_proc.stdout.close()
    # # noinspection PyPep8
    # ssh_mysql_proc = subprocess.Popen(('ssh', args.destination,
    #                                    '\"xz -d -c | mysql -u ' + args.dest_db_user + ' -p \\\"' + args.dest_db_pass + '\\\" -h ' + args.dest_db_host + ' ' + args.dest_db_name),
    #                                   stdin=xz_proc.stdout)
    # pv_proc.stdout.close()
    #
    # ssh_mysql_proc.communicate()
    # ssh_mysql_proc.wait()

    print('OK, I am going to try to migrate the database now...')


    db_proc = """mysqldump -u{0} -p{1} -h{2} {3} | sed "s/TIME_ZONE='+00:00'/TIME_ZONE='+06:00'/" | pv | xz -c -4 | ssh {4}@{5} "xz -d -c | mysql -u{6} -p{7} -h{8} {9}" """.format(
            args.source_db_user, shlex.quote(args.source_db_pass), args.source_db_host, args.source_db_name,
            args.dest_sftp_user, args.destination, args.dest_db_user, shlex.quote(args.dest_db_pass), args.dest_db_host, args.dest_db_name)
    if args.verbose:
        print(db_proc)
    try:
        subprocess.call(db_proc, shell=True)  # This is the "wrong" way to do it, but I can't get the nested Popen's to work
    except KeyboardInterrupt:
        exit(0)

    # Update the DB refs in local.xmls or wp-config.php
    step_placeholder('update database refs')

    # Clear magento cache
    if len(magento_roots) != 0:
        step_placeholder('clear the magento cache')

    # Make sure you didn't break anything
    step_placeholder('test the original site')

# Transfer the site

# subprocess.call(('sudo chmod g+w {0}'.format(site_httpdocs)))
# subprocess.call(('ssh', '-t', args.destination, 'sudo chmod g+w {0}'.format(site_httpdocs)))

# Bit off more than I can chew...

# tar_proc = subprocess.Popen(('tar', 'cf', '-', 'httpdocs', '-C', site_path), stdout=subprocess.PIPE)
# pv2_proc = subprocess.Popen(('pv', '-s', get_folder_size(site_path)), stdin=tar_proc.stdout, stdout=subprocess.PIPE)
# tar_proc.stdout.close()
# xz2_proc = subprocess.Popen(('xz', '-c'), stdin=pv2_proc.stdout, stdout=subprocess.PIPE)
# pv2_proc.stdout.close()
# ssh_tar_proc = subprocess.Popen(('ssh', args.description, '\"tar xJf - -C ' + site_path + '\"'), stdin=xz2_proc.stdout)
#
# ssh_tar_proc.communicate()
# ssh_tar_proc.wait()

print('OK, I am going to try to migrate the site now...')
if args.freshen:
    print('Performing rsync, as freshen was defined.')
    if args.verbose:
        rsync_verbose = ' --verbose'
    else:
        rsync_verbose = ''
    tar_proc = 'rsync -rtlD --delete {3}{0}/ {1}@{2}:{0}/'.format(site_httpdocs, args.dest_sftp_user, args.destination, rsync_verbose)
else:
    tar_proc = 'tar cf - -C {0} . | pv -s {1} | xz -c |  ssh {2}@{3} "tar xJf - -C {0}"'.format(site_httpdocs,
                                                                                                get_folder_size(
                                                                                                    site_httpdocs),
                                                                                                args.dest_sftp_user,
                                                                                                args.destination)
    # The destination directory has crap, clear it out.
    if args.verbose:
        print('Clearing crap')
    subprocess.call(('ssh', args.dest_sftp_user + '@' + args.destination, 'rm -rf {0}/*'.format(site_httpdocs)))
if args.verbose:
    print(tar_proc)

try:
    subprocess.call(tar_proc, shell=True)
except KeyboardInterrupt:
    exit(0)

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
