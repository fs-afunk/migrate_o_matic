import plesk.apiclient

aws_web3 = plesk.apiclient.Client(host='aws-web3.firstscribe.com', verbose=False)
aws_web3.set_credentials('admin', '2ZNnFyTnyGUcvVChqu2e4TY3NR7Uxu')
customer = aws_web3.get_site_id('nuaire.com')

response = aws_web3.get_protected_dirs(customer)
print(response)
