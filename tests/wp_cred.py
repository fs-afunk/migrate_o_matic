import cms.wordpress

brownsworth_wp = cms.wordpress.Instance('/var/www/vhosts/brownsworth.com/httpdocs/')

print(brownsworth_wp.name)
print(brownsworth_wp.password)
print(brownsworth_wp.host)
print(brownsworth_wp.user)

brownsworth_wp.update_config(name='greensworth_db', user='greensworth_user', password='fly1nGM0nk3ys', host='aws-db1.firstscribe.com')

print(brownsworth_wp.name)
print(brownsworth_wp.password)
print(brownsworth_wp.host)
print(brownsworth_wp.user)
greensworth_wp = cms.wordpress.Instance('/var/www/vhosts/brownsworth.com/httpdocs/')

print(greensworth_wp.name)
print(greensworth_wp.password)
print(greensworth_wp.host)
print(greensworth_wp.user)
