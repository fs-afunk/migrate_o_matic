import plesk.apiclient

aws_web3 = plesk.apiclient.Client(host='aws-web3.firstscribe.com', verbose=True)
success = aws_web3.lookup_plesk_info()

if success:
    print(aws_web3.get_hosting_info('testsite.com'))
