import argparse
import subprocess

parser = argparse.ArgumentParser(description='migrate a website from one server to another')
parser.add_argument('site', help='the site to be migrated')
parser.add_argument('destination', help='where to move the site')

parser.add_argument('-v', '--verbose', help='explain what you are doing', action='store_true')
parser.add_argument('--no-db', help='skip the database migration', action='store_true')
parser.add_argument('-sdn', '--source-db-name', help='what the database is currently named')
parser.add_argument('-ddn', '--dest-db-name', help='what the database should be named, defaults to source-db-name')
parser.add_argument('-sdu', '--source-db-user',
                    help='what user currently uses the database, defaults to source-db-name')
parser.add_argument('-ddu', '--dest-db-user', help='what user will use the database, defaults to dest-db-name')
parser.add_argument('-sdp', '--source-db-pass', nargs='?',
                    help='what the password for the user currently is, defaults to prompt')
parser.add_argument('-ddp', '--dest-db-pass',
                    help='what the password for the user should be, defaults to source-db-pass')
parser.add_argument('-sdh', '--source-db-host', help='where the database currently resides')
parser.add_argument('-ddh', '--dest-db-host', help='where the database should go', default='aws-db1.firstscribe.com')
parser.parse_args()


# Verify DNS abilities
# Notify customer
# Create new customer/domains on plesk
# Copy SSL certs if any
# Copy any special hosting settings/php settings
# Clear the canned 'welcome to plesk' pages
# Find database references.  I like grep -R '\.firstscribe\.com'
# Make database (through plesk, to get ref)
# Transfer the Database
# Update the DB refs in local.xmls or wp-config.php
# Make sure you didn't break anything
# Transfer the site
# If we host DNS, copy records
# Update DNS/Switch Nameserver
# Clear magento cache
