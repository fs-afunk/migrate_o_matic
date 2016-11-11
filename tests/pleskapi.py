import plesk.apiclient

aws_web3 = plesk.apiclient.Client(host='aws-web3.firstscribe.com', verbose=False)
success = aws_web3.lookup_plesk_info()

print(aws_web3.internal_ip)

if success:
    customer = aws_web3.get_site_id('nuaire.com')
    response = aws_web3.get_protected_dirs(customer)
    print(customer, response)
