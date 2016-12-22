import plesk.apiclient

source_plesk = plesk.apiclient.Client('web3.firstscribe.com', verbose=True)

source_plesk.lookup_plesk_info()

ssl_certs = source_plesk.get_ssl_certs('failure.com')

print(ssl_certs)