import re

class WpInstance:
    """A class to represent an installation of WordPress"""

    def __init__(self, base_path):
        self.base_path = base_path
        self.config_path = base_path + '/wp-config.php'

        with open(self.config_path, 'r') as conf_fh:
            t_result  = re.findall(r"""^define\(\s*['"]*(.*?)['"]*[\s,]+['"]*(.*?)['"]*\s*\)""", conf_fh.read(),
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


brownsworth_wp = WpInstance('/var/www/vhosts/brownsworth.com/httpdocs/')

print(brownsworth_wp.name)
print(brownsworth_wp.password)
print(brownsworth_wp.host)
print(brownsworth_wp.user)

brownsworth_wp.update_config(name='greensworth_db', user='greensworth_user', password='fly1nGM0nk3ys', host='aws-db1.firstscribe.com')

print(brownsworth_wp.name)
print(brownsworth_wp.password)
print(brownsworth_wp.host)
print(brownsworth_wp.user)
greensworth_wp = WpInstance('/var/www/vhosts/brownsworth.com/httpdocs/')

print(greensworth_wp.name)
print(greensworth_wp.password)
print(greensworth_wp.host)
print(greensworth_wp.user)
